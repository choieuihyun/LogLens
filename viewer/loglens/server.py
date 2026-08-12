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
import queue
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Deque, List, Optional
from urllib.parse import parse_qs, urlparse

from .analytics import IssueTray, aggregate
from .config import Config
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
            if path == "/api/stream":
                return self._sse()
            self.send_error(404)

        def do_POST(self):
            if urlparse(self.path).path == "/api/clear":
                hub.clear()
                return self._json({"ok": True})
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
