"""서버 API 계약 테스트.

브라우저 렌더는 여기서 확인할 수 없지만, **웹 UI 가 의존하는 JSON 모양**은 확인할 수 있다.
app.js 가 읽는 키가 빠지면 화면이 조용히 비는데, 그건 테스트 없이는 안 잡힌다.
"""

import json
import pathlib
import sys
import threading
import time
import unittest
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens.config import Config  # noqa: E402
from loglens.server import serve  # noqa: E402
from loglens.sources import build  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

CFG = Config.from_dict({
    "prefix": "APP",
    "tabs": [{"id": "auth", "label": "인증", "domains": ["AUTH"]}],
    "issueRules": [
        {"id": "anr", "label": "ANR", "severity": "fatal",
         "when": {"raw": r"\bANR in\b"},
         "group": {"regex": r"ANR in ([^\s(]+)", "fallback": "ANR"}},
        {"id": "structured_error", "label": "구조화 에러", "severity": "error",
         "when": {"kind": "^structured$", "level": "^E$"},
         "group": {"template": "{domain}/{event}"}},
    ],
    "funnels": [{"id": "login", "label": "로그인", "domain": "AUTH",
                 "steps": ["LOGIN_OK", "LOGOUT"]}],
})


class TestApi(unittest.TestCase):
    port = 8531

    @classmethod
    def setUpClass(cls):
        src = build("file", path=str(FIXTURES / "threadtime.log"))
        cls.httpd, cls.hub, cls.reader = serve(src, CFG, "127.0.0.1", cls.port)
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()
        # 리더가 픽스처를 다 읽을 때까지
        for _ in range(50):
            if cls.hub.seq >= 19:
                break
            time.sleep(0.02)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def raw(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return r.status, r.read()

    # -- UI 가 의존하는 모양 ---------------------------------------------------
    def test_config_shape(self):
        code, d = self.get("/api/config")
        self.assertEqual(code, 200)
        for k in ("prefix", "tabs", "issueRules", "funnels", "source"):
            self.assertIn(k, d)
        self.assertEqual(d["tabs"][0]["id"], "auth")
        self.assertIn("kind", d["source"])

    def test_source_describe_shape(self):
        # UI 의 "이 앱만" 필터가 cfg.source.pid / .package 를 읽는다.
        adb = build("adb", serial="ABC123", package="io.loglens.sample")
        d = adb.describe()
        for k in ("kind", "serial", "package", "pid", "format"):
            self.assertIn(k, d)
        self.assertEqual(d["format"], "threadtime",
                         "파서가 아는 포맷과 adb 호출 포맷은 같아야 한다")
        self.assertIsNone(d["pid"], "기기 없이는 pid 를 못 푼다 — None 이어야 한다")
        self.assertIn("kind", build("synth").describe())
        self.assertIn("path", build("file", path="x.log").describe())

    def test_bad_limit_does_not_500(self):
        code, d = self.get("/api/snapshot?limit=abc")
        self.assertEqual(code, 200)
        self.assertIn("records", d)

    def test_snapshot_shape(self):
        code, d = self.get("/api/snapshot?limit=100")
        self.assertEqual(code, 200)
        for k in ("records", "issues", "status", "total"):
            self.assertIn(k, d)
        rec = next(r for r in d["records"] if r["kind"] == "structured")
        for k in ("kind", "ts", "level", "tag", "domain", "event",
                  "fields", "msg", "pid", "tid", "truncated", "raw"):
            self.assertIn(k, rec)

    def test_issue_shape(self):
        _, d = self.get("/api/snapshot?limit=1")
        self.assertTrue(d["issues"], "픽스처에 ANR/구조화 에러가 있으므로 이슈가 나와야 한다")
        for g in d["issues"]:
            for k in ("ruleId", "ruleLabel", "severity", "key", "count", "sample"):
                self.assertIn(k, g)

    def test_stats_shape(self):
        code, d = self.get("/api/stats")
        self.assertEqual(code, 200)
        for k in ("total", "structured", "structuredRatio", "levels",
                  "domains", "topEvents", "successRates", "failureReasons", "funnels"):
            self.assertIn(k, d)
        for r in d["successRates"]:
            self.assertEqual(set(r), {"domain", "success", "failure", "rate"})
        f = d["funnels"][0]
        self.assertEqual(set(f), {"id", "label", "domain", "mode", "steps"})
        self.assertEqual(set(f["steps"][0]), {"event", "count", "dropoff"})

    def test_json_is_utf8_not_escaped(self):
        _, body = self.raw("/api/snapshot?limit=100")
        self.assertIn("로그인 성공".encode("utf-8"), body,
                      "한글이 \\uXXXX 로 이스케이프되면 안 된다")

    # -- 정적 서빙 / 안전성 ----------------------------------------------------
    def test_static_files(self):
        for path in ("/", "/static/app.js", "/static/app.css"):
            code, body = self.raw(path)
            self.assertEqual(code, 200, path)
            self.assertGreater(len(body), 100, path)

    def test_path_traversal_blocked(self):
        try:
            self.raw("/static/../../parser.py")
            self.fail("경로 탈출이 막히지 않았다")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_unknown_route_404(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.raw("/nope")

    # -- SSE -----------------------------------------------------------------
    def test_sse_headers_and_framing(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/stream")
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertTrue(r.headers["Content-Type"].startswith("text/event-stream"))
            self.assertEqual(r.headers["Cache-Control"], "no-cache")
            # 헤더를 받은 시점에 구독은 이미 성립해 있어야 한다.
            # (서버가 헤더보다 먼저 subscribe 하지 않으면 이 레코드를 놓친다)
            self.hub.ingest("08-12 12:00:00.000  1  1 I APP_AUTH: evt=SSE_PROBE k=v")
            saw_event = saw_data = False
            for _ in range(10):
                line = r.readline().decode("utf-8", "replace")
                if line.startswith("event: logs"):
                    saw_event = True
                if saw_event and line.startswith("data: "):
                    saw_data = "SSE_PROBE" in line
                    break
            self.assertTrue(saw_event, "SSE 이벤트 프레임이 오지 않았다")
            self.assertTrue(saw_data, "밀어넣은 레코드가 스트림에 나타나지 않았다")

    def test_clear_empties_buffer(self):
        src = build("file", path=str(FIXTURES / "brief.log"))
        httpd, hub, _ = serve(src, CFG, "127.0.0.1", self.port + 1)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            for _ in range(50):
                if hub.seq >= 4:
                    break
                time.sleep(0.02)
            self.assertGreater(len(hub.buffer), 0)
            urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{self.port + 1}/api/clear", method="POST"), timeout=5)
            self.assertEqual(len(hub.buffer), 0)
            self.assertEqual(hub.tray.snapshot(), [])
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
