"""이벤트 목록(커버리지·사전·이름 검사) 테스트. 가짜 앱 소스를 임시 디렉토리에 만든다."""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens import events  # noqa: E402
from loglens.config import Config  # noqa: E402
from loglens.server import Hub  # noqa: E402

JAVA = """class NetTrace {
    /** 예: LogLens.i(AppDomain.NET, "DOC_EXAMPLE", "k", v); */
    static void ok(String host) {
        LogLens.i(AppDomain.NET, "REQ_OK",
                "host", host,
                "size", String.format("%d, %d", a, b),
                "msg", "요청 성공, 다음 단계");
    }
    static void fail(Throwable t) {
        LogLens.w(AppDomain.NET, "REQ_FAIL", t, "host", host);
    }
    static void bad() {
        LogLens.e(AppDomain.NET, "SYNC_FAIL", "host", host);
        LogLens.i(AppDomain.NET, dynamicName(), "k", v);
    }
}
"""

KOTLIN = """object ChatTrace {
    fun sent(room: String) = LogLens.i(AppDomain.CHAT, "SEND_OK", "roomId" to room, "user_id" to u, "uid" to x)
    fun err(e: Throwable) = LogLens.e(AppDomain.CHAT, "SEND_FAIL", e, "room_id" to r)
    fun odd() = LogLens.d(AppDomain.CHAT, "loadDone", "userId" to u)
}
"""


class TestParse(unittest.TestCase):
    def test_split_respects_strings_and_nesting(self):
        args = events._split_args('(a, "b, c", f(x, y), "d\\", e")')
        self.assertEqual(args, ['a', '"b, c"', 'f(x, y)', '"d\\", e"'])

    def test_java_throwable_and_msg(self):
        self.assertEqual(events.parse_call(['AppDomain.NET', '"E"', 't', '"host"', 'h', '"msg"', '"x"']),
                         ("NET", "E", ["host", "err", "at"]))

    def test_kotlin_pairs_and_throwable(self):
        self.assertEqual(events.parse_call(['AppDomain.CHAT', '"E"', 'e', '"room" to r']),
                         ("CHAT", "E", ["room", "err", "at"]))

    def test_dynamic_event_name_is_skipped(self):
        self.assertIsNone(events.parse_call(['AppDomain.NET', 'name()', '"k"', 'v']))

    def test_unknown_domain_goes_to_other(self):
        self.assertEqual(events.parse_call(['dom', '"E"'])[0], "기타")


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        (root / "NetTrace.java").write_text(JAVA, encoding="utf-8")
        (root / "ChatTrace.kt").write_text(KOTLIN, encoding="utf-8")
        self.root = str(root)

    def tearDown(self):
        self.tmp.cleanup()

    def inv(self):
        found, err = events.inventory({"root": self.root})
        self.assertIsNone(err)
        return {e["event"]: e for e in found}

    def test_multiline_call_and_comma_in_string(self):
        e = self.inv()["REQ_OK"]
        # 문자열 속 쉼표와 중첩 호출이 필드를 만들어내지 않는다. msg 는 필드가 아니다
        self.assertEqual(e["declared"], ["host", "size"])
        self.assertEqual((e["domains"], e["levels"]), (["NET"], ["I"]))
        self.assertEqual(e["emits"][0]["method"], "ok")

    def test_comment_example_and_dynamic_name_skipped(self):
        inv = self.inv()
        self.assertNotIn("DOC_EXAMPLE", inv)
        self.assertEqual(sorted(inv), ["REQ_FAIL", "REQ_OK", "SEND_FAIL", "SEND_OK", "SYNC_FAIL", "loadDone"])

    def test_lint(self):
        seen = {"REQ_OK": {"count": 3, "domains": ["NET"], "fields": {"host": "a"}, "lastTs": "t"},
                "GHOST_EVT": {"count": 1, "domains": ["NET"], "fields": {}, "lastTs": "t"}}
        cfg = Config.from_dict({"prefix": "APP", "naming": {"synonyms": [["uid", "userId"], ["roomId", "room_id"]]}})
        r = events.build(list(events.inventory({"root": self.root})[0]), seen, cfg.outcome, cfg.synonyms)
        kinds = {(l["kind"], tuple(l["events"])) for l in r["lint"]}
        msgs = " ".join(l["message"] for l in r["lint"])
        self.assertIn("userId / user_id", msgs)                       # 표기만 다른 필드
        self.assertIn(("event-name", ("loadDone",)), kinds)            # 대문자_밑줄 아님
        self.assertIn(("no-reason", ("SYNC_FAIL",)), kinds)            # 실패인데 사유 없음
        self.assertNotIn(("no-reason", ("REQ_FAIL",)), kinds)          # 예외를 넘기면 err= 가 붙는다
        self.assertIn(("not-in-source", ("GHOST_EVT",)), kinds)        # 로그엔 왔는데 소스에 없음
        syn = [l["fields"] for l in r["lint"] if l["kind"] == "field-synonym"]
        self.assertEqual(syn, [["uid", "userId"]], "표기만 다른 쌍은 동의어로 또 알리지 않는다")
        by = {e["event"]: e for e in r["events"]}
        self.assertEqual(by["REQ_OK"]["seen"], 3)
        self.assertEqual(by["SEND_OK"]["seen"], 0)

    def test_synonyms_are_off_by_default(self):
        r = events.build(list(events.inventory({"root": self.root})[0]), {},
                         Config.default().outcome, Config.default().synonyms)
        self.assertFalse(any(l["kind"] == "field-synonym" for l in r["lint"]))


class TestHubCoverage(unittest.TestCase):
    def test_coverage_survives_buffer_eviction_and_clear_resets(self):
        h = Hub(Config.from_dict({"prefix": "APP", "bufferSize": 2}))
        for i in range(5):
            h.ingest(f"08-12 10:00:0{i}.000  1  1 I APP_NET: evt=E{i} k=v")
        by = {e["event"]: e for e in h.events()["events"]}
        self.assertEqual(sorted(by), ["E0", "E1", "E2", "E3", "E4"], "버퍼(2줄)보다 오래 센다")
        self.assertEqual(by["E0"]["example"], {"k": "v"})
        h.clear()
        self.assertEqual(h.events()["events"], [])

    def test_without_source_explains(self):
        d = Hub(Config.from_dict({"prefix": "APP"})).events()
        self.assertFalse(d["hasSource"])
        self.assertIn("eventSource", d["sourceError"])


if __name__ == "__main__":
    unittest.main()
