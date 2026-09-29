"""로컬 서버 + SSE 브리지.

기획서 §6 의 핵심 트릭: 브라우저는 USB/adb 에 직접 접근할 수 없다.
그래서 로컬 프로세스가 adb 를 물고, 파싱하고, SSE 로 브라우저에 밀어준다.
Electron 도, 파일 주입도 필요 없다.

    [기기] --adb logcat--> [이 서버(파싱)] --SSE--> [브라우저 GUI]

의존성 0 (표준 라이브러리만). pip 한 줄이나 PyInstaller 단일 바이너리로 배포 가능.
"""

from __future__ import annotations

import json
import mimetypes
import pathlib
import os
import queue
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Deque, List, Optional
from urllib.parse import parse_qs, urlparse

from . import catalog as catalog_src
from .analytics import (IssueTray, aggregate, build_table, build_tree, check_value,
                        diff_groups)
from .config import Config, merge_catalog
from .snapshots import SnapshotStore
from .parser import Parser, Record
from .sources.base import MARKER, LogSource

WEB_DIR = pathlib.Path(__file__).parent / "web"

# SSE 배치: 브라우저를 이벤트로 익사시키지 않는다.
FLUSH_INTERVAL = 0.1
SUBSCRIBER_QUEUE_MAX = 2000
HEARTBEAT = 15.0


class Hub:
    """링 버퍼 + 구독자 팬아웃. 서버의 전부다."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.parser = Parser(cfg.prefix)
        self.tray = IssueTray(cfg)
        self.buffer: Deque[Record] = deque(maxlen=cfg.buffer_size)
        self.status: str = "시작 중"
        self.seq = 0
        self._lock = threading.Lock()
        self._subs: List[queue.Queue] = []
        self.snapshots = SnapshotStore(cfg.snapshot_dir) if cfg.snapshot_dir else None
        self.catalog_errors: dict = {}
        self.reload_catalogs()

    # -- 쓰기 -----------------------------------------------------------------
    def ingest(self, line: str) -> None:
        rec = self.parser.parse(line)
        if rec.raw.startswith(MARKER):
            self.status = rec.raw[len(MARKER):].strip()
        with self._lock:
            self.seq += 1
            self.buffer.append(rec)
            self.tray.observe(rec)
            payload = rec.to_dict()
            payload["seq"] = self.seq
            dead = []
            for q in self._subs:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    # 느린 구독자 때문에 스트림 전체가 막히면 안 된다. 가장 오래된 걸 버린다.
                    try:
                        q.get_nowait()
                        q.put_nowait(payload)
                    except Exception:
                        dead.append(q)
            for q in dead:
                self._subs.remove(q)
        # 묶음이 끝났다는 표시(countEvent)가 오면 그 묶음을 파일로 남긴다. 락 밖에서 한다.
        if self.snapshots:
            for t in self.cfg.tables:
                if t.count_matches(rec):
                    self._save_group(t, rec.fields.get(t.group_by, "") if t.group_by else "")

    def clear(self) -> None:
        with self._lock:
            self.buffer.clear()
            self.tray.clear()

    # -- 읽기 -----------------------------------------------------------------
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=SUBSCRIBER_QUEUE_MAX)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def snapshot(self, limit: int = 2000) -> dict:
        with self._lock:
            recs = list(self.buffer)[-limit:]
            return {
                "records": [r.to_dict() for r in recs],
                "issues": self.tray.snapshot(),
                "status": self.status,
                "total": len(self.buffer),
            }

    def stats(self) -> dict:
        with self._lock:
            recs = list(self.buffer)
        return aggregate(recs, self.cfg)

    def trees(self) -> list:
        """설정에 적힌 계층 규칙대로 트리를 세워 돌려준다."""
        with self._lock:
            recs = list(self.buffer)
        return [build_tree(recs, x) for x in self.cfg.trees]

    def tables(self) -> list:
        """설정에 적힌 표 규칙대로 묶음별 표를 돌려준다. 저장해 둔 묶음도 합친다."""
        with self._lock:
            recs = list(self.buffer)
        out = []
        for t in self.cfg.tables:
            d = build_table(recs, t)
            d["catalogError"] = self.catalog_errors.get(t.id)
            # 상세 창이 앱 코드 위치를 링크로 만들 때 쓴다. 표 응답만으로 그릴 수 있게 싣는다.
            d["sourceRoot"] = t.source_root()
            d["sourceLink"] = t.source_link
            d["sourceOpen"] = bool(t.source_open)
            if self.snapshots:
                self._merge_saved(t, d)
            out.append(d)
        return out

    # -- 구현 목록 -------------------------------------------------------------
    def reload_catalogs(self) -> dict:
        """앱 소스에서 구현 목록을 다시 뽑는다. 손으로 적은 목록을 그 위에 덮는다."""
        counts = {}
        for t in self.cfg.tables:
            if not t.catalog_source:
                continue
            found, err = catalog_src.extract(t.catalog_source)
            self.catalog_errors[t.id] = err
            t.catalog = merge_catalog(found, t.catalog_manual)
            counts[t.id] = {"found": len(found), "total": len(t.catalog), "error": err}
        return counts

    def open_source(self, table_id: str, code: str, runner=subprocess.Popen) -> dict:
        """catalog 에 적힌 위치를 설정의 명령으로 연다.

        브라우저는 표와 코드만 보낸다. 경로는 서버가 catalog 에서 찾고, 소스 루트 밖이면 거절한다.
        명령은 설정에 적힌 인자 목록 그대로 — 셸을 거치지 않는다.
        """
        t = next((x for x in self.cfg.tables if x.id == table_id), None)
        if t is None or not t.source_open:
            return {"ok": False, "error": "이 표에는 여는 명령(sourceOpen)이 없다"}
        entry = next((c for c in t.catalog if c["code"] == code), None)
        where = str((entry or {}).get("where") or "")
        path, _, line = where.rpartition(":")
        if not path or not line.isdigit():
            return {"ok": False, "error": "이 코드의 소스 위치를 모른다"}
        root = t.source_root() or ""
        abs_path = os.path.realpath(os.path.join(root, path))
        if not root or not abs_path.startswith(os.path.realpath(root) + os.sep):
            return {"ok": False, "error": "소스 루트 밖의 파일은 열지 않는다"}
        if not os.path.isfile(abs_path):
            return {"ok": False, "error": f"파일이 없다: {path}"}
        argv = [a.replace("{abs}", abs_path).replace("{path}", path).replace("{line}", line)
                for a in t.source_open]
        try:
            runner(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            return {"ok": False, "error": f"명령을 실행하지 못했다: {e}"}
        return {"ok": True, "where": where}

    # -- 스냅샷 ---------------------------------------------------------------
    def _save_group(self, t, gid: str) -> None:
        with self._lock:
            recs = list(self.buffer)
        for g in build_table(recs, t)["groups"]:
            if g["id"] == gid:
                self.snapshots.save(t.id, g)
                return

    def save_group(self, table_id: str, gid: str) -> bool:
        """사용자가 누른 저장. 끝 표시(countEvent)가 없는 표도 남길 수 있게."""
        if not self.snapshots:
            return False
        for t in self.cfg.tables:
            if t.id == table_id:
                self._save_group(t, gid)
                return True
        return False

    def _merge_saved(self, t, d: dict) -> None:
        # 저장본의 검사 결과는 저장 당시 목록 기준이라 지금 목록으로 다시 매긴다
        cat = {c["code"]: c for c in t.catalog}
        live = {g["id"]: g for g in d["groups"]}
        older = []
        for g in self.snapshots.load(t.id):
            if g.get("id") in live:
                live[g["id"]]["saved"] = True
                live[g["id"]]["savedAt"] = g.get("savedAt")
                continue
            for r in g.get("rows", []):
                r["problems"] = check_value(cat.get(r.get("key")), r.get("values") or {})
                for c in (r.get("values") or {}):
                    if c not in d["columns"]:
                        d["columns"].append(c)
            g["problemCount"] = sum(1 for r in g.get("rows", []) if r["problems"])
            older.append(g)
        # 저장본(버퍼에서 이미 밀려난 것)을 앞에, 지금 버퍼의 묶음을 뒤에 — 시간 순서가 된다
        d["groups"] = older + d["groups"]

    def table_diff(self, table_id: str, a: str, b: str) -> Optional[dict]:
        """한 표 안의 두 묶음을 비교한다. 표나 묶음이 없으면 None."""
        for t in self.tables():
            if t["id"] != table_id:
                continue
            by_id = {g["id"]: g for g in t["groups"]}
            if a not in by_id or b not in by_id:
                return None
            return diff_groups(by_id[a], by_id[b], t["columns"])
        return None


class Reader(threading.Thread):
    """소스를 읽어 Hub 에 밀어넣는 단일 스레드."""

    daemon = True

    def __init__(self, source: LogSource, hub: Hub):
        super().__init__(name="loglens-reader")
        self.source = source
        self.hub = hub

    def run(self):
        try:
            for line in self.source.lines():
                self.hub.ingest(line)
        except Exception as e:  # 리더가 죽어도 서버는 살아 있어야 한다
            self.hub.ingest(f"{MARKER} 리더 종료: {type(e).__name__}: {e}")


def _handler_factory(hub: Hub, source: LogSource):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "LogLens"

        # 콘솔이 요청 로그로 도배되지 않게
        def log_message(self, fmt, *args):
            pass

        # -- helpers ----------------------------------------------------------
        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, rel: str):
            # 정적 파일은 WEB_DIR 안으로 가둔다 (경로 탈출 방지).
            target = (WEB_DIR / rel).resolve()
            if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
                self.send_error(404)
                return
            body = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        # -- routes -----------------------------------------------------------
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            path = u.path

            if path == "/":
                return self._file("index.html")
            if path.startswith("/static/"):
                return self._file(path[len("/static/"):])
            if path == "/api/config":
                d = hub.cfg.to_dict()
                d["source"] = source.describe()
                return self._json(d)
            if path == "/api/snapshot":
                try:
                    limit = int(q.get("limit", ["2000"])[0])
                except ValueError:
                    limit = 2000          # 쿼리 오타로 요청이 500 나면 안 된다
                return self._json(hub.snapshot(max(1, limit)))
            if path == "/api/stats":
                return self._json(hub.stats())
            if path == "/api/tree":
                return self._json(hub.trees())
            if path == "/api/tables":
                return self._json(hub.tables())
            if path == "/api/tables/diff":
                arg = lambda k: q.get(k, [""])[0]  # noqa: E731
                d = hub.table_diff(arg("table"), arg("a"), arg("b"))
                if d is None:
                    # 버퍼가 비워졌거나 묶음이 밀려났을 수 있다. 500 이 아니라 사유를 준다.
                    return self._json({"error": "표 또는 묶음을 찾지 못했다"}, 404)
                return self._json(d)
            if path == "/api/stream":
                return self._sse()
            self.send_error(404)

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/clear":
                hub.clear()
                return self._json({"ok": True})
            if u.path == "/api/tables/save":
                ok = hub.save_group(q.get("table", [""])[0], q.get("group", [""])[0])
                return self._json({"ok": ok}, 200 if ok else 400)
            if u.path == "/api/catalog/reload":
                return self._json(hub.reload_catalogs())
            if u.path == "/api/open":
                r = hub.open_source(q.get("table", [""])[0], q.get("code", [""])[0])
                return self._json(r, 200 if r["ok"] else 400)
            self.send_error(404)

        # -- SSE --------------------------------------------------------------
        def _sse(self):
            # 헤더보다 **먼저** 구독한다. 순서가 반대면 클라이언트가 헤더를 받은 시점과
            # 구독이 성립하는 시점 사이에 들어온 레코드를 조용히 놓친다.
            sub = hub.subscribe()

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            batch = []
            last_flush = last_beat = time.monotonic()
            try:
                while True:
                    try:
                        batch.append(sub.get(timeout=FLUSH_INTERVAL))
                    except queue.Empty:
                        pass
                    now = time.monotonic()
                    if batch and now - last_flush >= FLUSH_INTERVAL:
                        self._emit("logs", batch)
                        batch = []
                        last_flush = last_beat = now
                    elif now - last_beat >= HEARTBEAT:
                        # 프록시/브라우저가 유휴 연결을 끊지 않도록
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_beat = now
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass                                  # 탭 닫힘 — 정상
            finally:
                hub.unsubscribe(sub)

        def _emit(self, event: str, data):
            payload = json.dumps(data, ensure_ascii=False)
            self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()

    return Handler


def serve(source: LogSource, cfg: Config, host: str = "127.0.0.1",
          port: int = 8420) -> tuple:
    """서버와 리더를 띄우고 (httpd, hub, reader) 를 돌려준다."""
    hub = Hub(cfg)
    reader = Reader(source, hub)
    httpd = ThreadingHTTPServer((host, port), _handler_factory(hub, source))
    httpd.daemon_threads = True
    reader.start()
    return httpd, hub, reader
