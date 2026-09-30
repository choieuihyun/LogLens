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
import re
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Deque, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from . import callsites
from . import events as events_mod
from . import migrate as migrate_mod
from . import catalog as catalog_src
from .analytics import (IssueTray, aggregate, build_table, build_tree, check_value,
                        diff_groups)
from .config import Config, merge_catalog
from .flows import BaselineStore, flow_detail, list_flows
from .snapshots import SnapshotStore
from .sources.filesrc import SESSION_HEADER
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
        self.baselines = BaselineStore(cfg.snapshot_dir) if cfg.snapshot_dir else None
        self.seen = events_mod.Seen()
        # 세션 파일을 보는 중이면 실시간 수신을 받지 않는다 (섞이면 무엇을 보는지 모른다)
        self.session: Optional[dict] = None
        self.catalog_errors: dict = {}
        self.reload_catalogs()

    # -- 쓰기 -----------------------------------------------------------------
    def ingest(self, line: str, live: bool = True, fanout: bool = True) -> None:
        if live and self.session:
            return                             # 세션 파일을 보는 중 — 실시간 줄은 버린다
        rec = self.parser.parse(line)
        if rec.raw.startswith(MARKER):
            self.status = rec.raw[len(MARKER):].strip()
        with self._lock:
            self.seq += 1
            self.buffer.append(rec)
            self.tray.observe(rec)
            if rec.kind == "structured" and rec.event:
                self.seen.observe(rec)
            payload = rec.to_dict()
            payload["seq"] = self.seq
            dead = []
            for q in (self._subs if fanout else []):
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
        # 남의 세션 파일을 여는 중에는 남기지 않는다 (내 스냅샷에 섞이면 안 된다).
        if self.snapshots and live:
            for t in self.cfg.tables:
                if t.count_matches(rec):
                    self._save_group(t, rec.fields.get(t.group_by, "") if t.group_by else "")

    def clear(self) -> None:
        with self._lock:
            self.buffer.clear()
            self.tray.clear()
            self.seen.clear()                  # 비우기 = 커버리지도 처음부터

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
                "session": self.session,
            }

    # -- 세션 파일 ---------------------------------------------------------------
    def export_session(self, source_desc: dict) -> str:
        """지금 버퍼를 세션 파일로. 첫 줄은 설명, 나머지는 받은 원본 줄 그대로."""
        import datetime
        with self._lock:
            lines = [r.raw for r in self.buffer]
        meta = {"version": 1, "lines": len(lines), "source": source_desc,
                "exportedAt": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
        return SESSION_HEADER + json.dumps(meta, ensure_ascii=False) + "\n" + "\n".join(lines) + "\n"

    def import_session(self, name: str, text: str) -> dict:
        """세션 파일을 연다. 실시간 수신을 멈추고 버퍼를 파일 내용으로 바꾼다."""
        meta = {}
        body = []
        for ln in text.splitlines():
            if ln.startswith(SESSION_HEADER):
                try:
                    meta = json.loads(ln[len(SESSION_HEADER):])
                except ValueError:
                    pass
                continue
            body.append(ln)
        self.clear()
        self.session = {"name": name[:120], "lines": len(body), "meta": meta}
        for ln in body:
            self.ingest(ln, live=False, fanout=False)
        return {"ok": True, "lines": len(body), "session": self.session}

    def go_live(self) -> None:
        """세션 파일 보기를 끝내고 실시간으로. 파일 내용은 버린다."""
        self.session = None
        self.clear()

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
        """
        t = next((x for x in self.cfg.tables if x.id == table_id), None)
        if t is None or not t.source_open:
            return {"ok": False, "error": "이 표에는 여는 명령(sourceOpen)이 없다"}
        entry = next((c for c in t.catalog if c["code"] == code), None)
        return open_at(t.source_root() or "", str((entry or {}).get("where") or ""),
                       t.source_open, runner)

    # -- 이벤트: 커버리지 · 사전 ------------------------------------------------
    def events(self) -> dict:
        src = self.cfg.event_source
        inv, err = (events_mod.inventory(src) if src.get("root")
                    else ([], "eventSource 가 없어 앱 소스를 읽지 않았다 (받은 이벤트만 보인다)"))
        with self._lock:
            seen = {k: dict(v, fields=dict(v["fields"])) for k, v in self.seen.events.items()}
        d = events_mod.build(inv, seen, self.cfg.outcome, self.cfg.synonyms)
        d["sourceError"] = err
        d["hasSource"] = bool(src.get("root")) and not err
        # adb 는 뜰 때 기기에 남아 있던 logcat 기록부터 읽는다. 그 기록도 "지나감" 으로 센다.
        d["scope"] = ("뷰어가 받은 로그 전부 — 뜰 때 읽은 기기의 예전 기록 포함. "
                      "이번 테스트만 보려면 시작 전에 '다시 세기'")
        return d

    # -- 예전 로그 이관 (읽기 전용) ---------------------------------------------
    def _migration_ctx(self):
        src = self.cfg.event_source
        inv, _ = events_mod.inventory(src) if src.get("root") else ([], None)
        known = {e["event"]: (e["domains"] or ["기타"])[0] for e in inv}
        by_dom: Dict[str, int] = {}
        for e in inv:
            d = (e["domains"] or ["기타"])[0]
            by_dom[d] = by_dom.get(d, 0) + len(e["emits"])
        return src, known, by_dom

    def migration(self) -> dict:
        src, known, by_dom = self._migration_ctx()
        if not src.get("root"):
            return {"error": "eventSource 가 없어 앱 소스를 읽지 않았다", "domains": [], "files": [], "totals": {}}
        files, err = migrate_mod.scan(src, self.cfg.migration, self.cfg, known)
        d = migrate_mod.summarize(files, by_dom)
        d["error"] = err
        d["calls"] = self.cfg.migration.get("calls") or migrate_mod.DEFAULT_CALLS
        return d

    def migration_file(self, rel: str) -> dict:
        src, known, _ = self._migration_ctx()
        root = os.path.abspath(os.path.expanduser(str(src.get("root") or "")))
        path = os.path.realpath(os.path.join(root, rel))
        if not root or not path.startswith(os.path.realpath(root) + os.sep) or not os.path.isfile(path):
            return {"error": "소스 루트 안의 파일이 아니다", "items": []}
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        mig = self.cfg.migration
        calls = [str(c) for c in (mig.get("calls") or migrate_mod.DEFAULT_CALLS) if re.fullmatch(r"\w+", str(c))]
        items = migrate_mod.scan_file(rel, lines, calls, migrate_mod.Resolver(self.cfg),
                                      "kt" if rel.endswith(".kt") else "java",
                                      str(mig.get("domainExpr") or "AppDomain.{domain}"), known)
        return {"file": rel, "items": items, "error": None}

    def reset_seen(self) -> None:
        with self._lock:
            self.seen.clear()

    # -- 흐름 ------------------------------------------------------------------
    def flows(self) -> dict:
        with self._lock:
            recs = list(self.buffer)
        base = self.baselines.all() if self.baselines else {}
        return {"flows": list_flows(recs, self.cfg, base),
                "baselines": {k: {x: v.get(x) for x in ("flowId", "label", "savedAt")}
                              for k, v in base.items()},
                "canBaseline": bool(self.baselines)}

    def flow(self, fid: str) -> Optional[dict]:
        with self._lock:
            recs = list(self.buffer)
        return flow_detail(recs, self.cfg, fid, self.baselines.all() if self.baselines else {})

    def set_baseline(self, fid: str) -> dict:
        if not self.baselines:
            return {"ok": False, "error": "기준선을 저장할 곳이 없다 — 설정에 snapshotDir 를 넣는다"}
        d = self.flow(fid)
        if d is None:
            return {"ok": False, "error": "이 흐름이 버퍼에 없다"}
        return {"ok": self.baselines.save(d), "kind": d["kind"]}

    def clear_baseline(self, kind: str) -> dict:
        return {"ok": bool(self.baselines and self.baselines.clear(kind))}

    # -- 로그 → 코드 줄 --------------------------------------------------------
    def event_where(self, event: str) -> dict:
        """이 이벤트를 만든 코드 줄 후보. 누를 때마다 소스를 새로 읽는다 (줄이 밀려도 맞게)."""
        src = self.cfg.event_source
        if not (src.get("root") and src.get("open")):
            return {"event": event, "emits": [], "targets": [], "error": "eventSource 가 설정되지 않았다"}
        r, err = callsites.find(src, event)
        r["error"] = err
        return r

    def frame_where(self, pkg: str, file: str) -> dict:
        src = self.cfg.event_source
        if not (src.get("root") and src.get("open")):
            return {"files": [], "error": "eventSource 가 설정되지 않았다"}
        files, err = callsites.find_frame(src, pkg, file)
        return {"files": files, "error": err}

    def open_frame(self, pkg: str, file: str, line: str, idx: int, runner=subprocess.Popen) -> dict:
        r = self.frame_where(pkg, file)
        if r["error"]:
            return {"ok": False, "error": r["error"]}
        if not str(line).isdigit():
            return {"ok": False, "error": "줄 번호가 아니다"}
        if not (0 <= idx < len(r["files"])):
            return {"ok": False, "error": "앱 소스에 없는 파일이다 (라이브러리나 프레임워크 코드일 수 있다)"}
        src = self.cfg.event_source
        root = os.path.abspath(os.path.expanduser(str(src["root"])))
        return open_at(root, f"{r['files'][idx]}:{line}", [str(a) for a in src["open"]], runner)

    def open_event(self, event: str, idx: int, runner=subprocess.Popen) -> dict:
        r = self.event_where(event)
        if r["error"]:
            return {"ok": False, "error": r["error"]}
        if not (0 <= idx < len(r["targets"])):
            return {"ok": False, "error": "이 이벤트를 찍는 코드를 소스에서 찾지 못했다"}
        src = self.cfg.event_source
        root = os.path.abspath(os.path.expanduser(str(src["root"])))
        return open_at(root, r["targets"][idx]["where"], [str(a) for a in src["open"]], runner)

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


# -- 도메인별 상세 로그 스위치 (adb 소스에서만) ---------------------------------
_TAG_MAX = 23          # 구형 기기에서 setprop 키 길이 제한에 걸리는 태그 길이


def _domains(cfg) -> List[str]:
    out = []
    for t in cfg.tabs:
        for d in t.domains:
            if re.fullmatch(r"[A-Z0-9_]+", d) and d not in out:
                out.append(d)
    return out


def verbose_state(cfg, source) -> dict:
    if getattr(source, "name", "") != "adb" or not re.fullmatch(r"[A-Z0-9_]+", cfg.prefix or ""):
        return {"available": False, "reason": "adb 소스에서만 쓸 수 있다"}
    tags = source.forced_tags()
    if tags is None:
        return {"available": False, "reason": "기기에 붙지 못했다"}
    states, long_ = {}, []
    for d in _domains(cfg):
        tag = f"{cfg.prefix}_{d}"
        states[d] = tags.get(tag, "").upper() in ("VERBOSE", "DEBUG")
        if len(tag) > _TAG_MAX:
            long_.append(d)
    return {"available": True, "prefix": cfg.prefix, "states": states, "tooLong": long_}


def set_verbose(cfg, source, domain: str, on: bool) -> dict:
    """설정의 탭에 있는 도메인만 받는다. 이 문자열은 기기 셸에서 실행된다."""
    if getattr(source, "name", "") != "adb":
        return {"ok": False, "error": "adb 소스에서만 쓸 수 있다"}
    if domain not in _domains(cfg) or not re.fullmatch(r"[A-Z0-9_]+", cfg.prefix or ""):
        return {"ok": False, "error": "설정의 탭에 없는 도메인이다"}
    ok = source.set_forced(f"{cfg.prefix}_{domain}", on)
    return {"ok": ok, "error": None if ok else "기기에 적용하지 못했다"}


def open_at(root: str, where: str, argv_tmpl: List[str], runner=subprocess.Popen) -> dict:
    """where(파일:줄)를 설정의 명령으로 연다.

    경로는 서버가 가진 목록에서만 온다. 그래도 소스 루트 밖이면 거절한다 (목록이 손으로 적힌 경우 대비).
    명령은 인자 목록 그대로 실행한다 — 셸을 거치지 않는다.
    """
    path, _, line = where.rpartition(":")
    if not path or not line.isdigit():
        return {"ok": False, "error": "소스 위치를 모른다"}
    abs_path = os.path.realpath(os.path.join(root, path))
    if not root or not abs_path.startswith(os.path.realpath(root) + os.sep):
        return {"ok": False, "error": "소스 루트 밖의 파일은 열지 않는다"}
    if not os.path.isfile(abs_path):
        return {"ok": False, "error": f"파일이 없다: {path}"}
    argv = [a.replace("{abs}", abs_path).replace("{path}", path).replace("{line}", line)
            for a in argv_tmpl]
    try:
        runner(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return {"ok": False, "error": f"명령을 실행하지 못했다: {e}"}
    return {"ok": True, "where": where}


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
            if path == "/api/adb/verbose":
                return self._json(verbose_state(hub.cfg, source))
            if path == "/api/session/export":
                body = hub.export_session(source.describe()).encode("utf-8")
                name = time.strftime("loglens-%Y%m%d-%H%M%S.loglens")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/migrate":
                return self._json(hub.migration())
            if path == "/api/migrate/file":
                return self._json(hub.migration_file(q.get("path", [""])[0]))
            if path == "/api/events":
                return self._json(hub.events())
            if path == "/api/flows":
                return self._json(hub.flows())
            if path == "/api/flows/detail":
                d = hub.flow(q.get("id", [""])[0])
                if d is None:
                    return self._json({"error": "이 흐름이 버퍼에 없다 (밀려났거나 비워졌다)"}, 404)
                return self._json(d)
            if path == "/api/frames/where":
                return self._json(hub.frame_where(q.get("pkg", [""])[0], q.get("file", [""])[0]))
            if path == "/api/events/where":
                return self._json(hub.event_where(q.get("event", [""])[0]))
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
            if u.path == "/api/session/import":
                n = int(self.headers.get("Content-Length") or 0)
                if n > 64 * 1024 * 1024:
                    return self._json({"ok": False, "error": "파일이 너무 크다 (64MB 초과)"}, 413)
                text = self.rfile.read(n).decode("utf-8", "replace")
                return self._json(hub.import_session(q.get("name", ["세션"])[0], text))
            if u.path == "/api/session/live":
                hub.go_live()
                return self._json({"ok": True})
            if u.path == "/api/adb/verbose":
                r = set_verbose(hub.cfg, source, q.get("domain", [""])[0], q.get("on", ["0"])[0] == "1")
                return self._json(r, 200 if r["ok"] else 400)
            if u.path == "/api/adb/verbose/off-all":
                st = verbose_state(hub.cfg, source)
                for dom, on in (st.get("states") or {}).items():
                    if on:
                        set_verbose(hub.cfg, source, dom, False)
                return self._json(verbose_state(hub.cfg, source))
            if u.path == "/api/migrate/open":
                src = hub.cfg.event_source
                if not (src.get("root") and src.get("open")):
                    return self._json({"ok": False, "error": "eventSource 가 설정되지 않았다"}, 400)
                line = q.get("line", [""])[0]
                r = open_at(os.path.abspath(os.path.expanduser(str(src["root"]))),
                            f"{q.get('path', [''])[0]}:{line}", [str(a) for a in src["open"]])
                return self._json(r, 200 if r["ok"] else 400)
            if u.path == "/api/events/reset":
                hub.reset_seen()
                return self._json({"ok": True})
            if u.path == "/api/flows/baseline":
                r = hub.set_baseline(q.get("id", [""])[0])
                return self._json(r, 200 if r["ok"] else 400)
            if u.path == "/api/flows/baseline/clear":
                return self._json(hub.clear_baseline(q.get("kind", [""])[0]))
            if u.path == "/api/frames/open":
                a = lambda k: q.get(k, [""])[0]  # noqa: E731
                try:
                    idx = int(a("i") or "0")
                except ValueError:
                    idx = -1
                r = hub.open_frame(a("pkg"), a("file"), a("line"), idx)
                return self._json(r, 200 if r["ok"] else 400)
            if u.path == "/api/events/open":
                try:
                    idx = int(q.get("i", ["0"])[0])
                except ValueError:
                    idx = -1
                r = hub.open_event(q.get("event", [""])[0], idx)
                return self._json(r, 200 if r["ok"] else 400)
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
