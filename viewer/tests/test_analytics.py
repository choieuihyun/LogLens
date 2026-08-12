"""이슈 트레이 + 대시보드 집계 테스트."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens.analytics import IssueTray, aggregate  # noqa: E402
from loglens.config import Config  # noqa: E402
from loglens.parser import Parser  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

CFG = Config.from_dict({
    "prefix": "APP",
    "tabs": [
        {"id": "auth", "label": "인증", "domains": ["AUTH"], "legacyTagPattern": "(?i)legacy"},
        {"id": "chat", "label": "채팅", "domains": ["CHAT"]},
    ],
    "issueRules": Config.default().to_dict()["issueRules"] and [
        {"id": "crash", "label": "크래시", "severity": "fatal",
         "when": {"tag": "^AndroidRuntime$", "raw": r"[\w.$]+(?:Exception|Error)\b"},
         "group": {"regex": r"([\w.$]+(?:Exception|Error))\b", "fallback": "UnknownCrash"}},
        {"id": "anr", "label": "ANR", "severity": "fatal",
         "when": {"raw": r"\bANR in\b"},
         "group": {"regex": r"ANR in ([^\s(]+)", "fallback": "ANR"}},
        {"id": "structured_error", "label": "구조화 에러", "severity": "error",
         "when": {"kind": "^structured$", "level": "^E$"},
         "group": {"template": "{domain}/{event}"}},
    ],
    "funnels": [{"id": "login", "label": "로그인", "domain": "AUTH",
                 "steps": ["LOGIN_START", "TOKEN_ISSUE", "LOGIN_OK"]}],
})


def parse_fixture(name="threadtime.log"):
    p = Parser("APP")
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return p.parse_lines(lines)


class TestIssueTray(unittest.TestCase):
    def setUp(self):
        self.tray = IssueTray(CFG)
        for r in parse_fixture():
            self.tray.observe(r)
        self.snap = {(g["ruleId"], g["key"]): g for g in self.tray.snapshot()}

    def test_crash_grouped_by_exception_class(self):
        self.assertIn(("crash", "java.lang.NullPointerException"), self.snap)

    def test_crash_header_and_stack_frames_do_not_split_the_issue(self):
        crashes = [k for k in self.snap if k[0] == "crash"]
        self.assertEqual(crashes, [("crash", "java.lang.NullPointerException")],
                         "FATAL EXCEPTION 헤더나 `at ...` 프레임이 별도 이슈로 새면 안 된다")

    def test_anr_grouped_by_package(self):
        self.assertIn(("anr", "io.loglens.sample"), self.snap)

    def test_structured_errors_grouped_by_domain_event(self):
        self.assertIn(("structured_error", "NET/SOCKET_FAIL"), self.snap)
        self.assertIn(("structured_error", "CHAT/SEND_FAIL"), self.snap)

    def test_counts_accumulate(self):
        tray = IssueTray(CFG)
        recs = parse_fixture()
        for _ in range(3):
            for r in recs:
                tray.observe(r)
        g = next(x for x in tray.snapshot() if x["key"] == "io.loglens.sample")
        self.assertEqual(g["count"], 3)

    def test_fatal_sorts_before_error(self):
        sevs = [g["severity"] for g in self.tray.snapshot()]
        self.assertEqual(sevs, sorted(sevs, key=lambda s: {"fatal": 0, "error": 1}[s]))


class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.s = aggregate(parse_fixture(), CFG)

    def test_counts(self):
        self.assertEqual(self.s["structured"], 11)
        self.assertGreater(self.s["total"], self.s["structured"])
        self.assertLess(self.s["structuredRatio"], 1.0)

    def test_success_rate_uses_event_suffix(self):
        auth = next(r for r in self.s["successRates"] if r["domain"] == "AUTH")
        # LOGIN_OK(성공) vs LOGIN_FAIL(실패). TOKEN_REFRESH/LOGOUT 은 판정 대상 아님.
        self.assertEqual((auth["success"], auth["failure"]), (1, 1))
        self.assertEqual(auth["rate"], 0.5)

    def test_failure_reason_extracted_from_configured_field(self):
        auth = next(r for r in self.s["failureReasons"] if r["domain"] == "AUTH")
        self.assertEqual(auth["reasons"], [("WRONG_PW", 1)])

    def test_funnel_uses_count_mode_without_flowid(self):
        f = self.s["funnels"][0]
        self.assertEqual(f["mode"], "count")
        self.assertEqual([s["event"] for s in f["steps"]],
                         ["LOGIN_START", "TOKEN_ISSUE", "LOGIN_OK"])

    def test_funnel_uses_flowid_when_present(self):
        p = Parser("APP")
        lines = []
        # flow A 는 끝까지, flow B 는 중간에서 이탈
        for step in ["LOGIN_START", "TOKEN_ISSUE", "LOGIN_OK"]:
            lines.append(f"08-12 11:00:00.000  1  1 I APP_AUTH: evt={step} flowId=A")
        for step in ["LOGIN_START", "TOKEN_ISSUE"]:
            lines.append(f"08-12 11:00:00.000  1  1 I APP_AUTH: evt={step} flowId=B")
        f = aggregate(p.parse_lines(lines), CFG)["funnels"][0]
        self.assertEqual(f["mode"], "flowId")
        self.assertEqual([s["count"] for s in f["steps"]], [2, 2, 1])
        self.assertEqual(f["steps"][2]["dropoff"], 0.5)


class TestTabs(unittest.TestCase):
    def test_domain_and_legacy_tag_both_match(self):
        p = Parser("APP")
        auth = CFG.tabs[0]
        self.assertTrue(auth.matches(p.parse("I/APP_AUTH: evt=X")))
        self.assertTrue(auth.matches(p.parse("D/LegacyTag: @@@ blah")),
                        "레거시 태그도 같은 탭에 끌어와야 점진 도입이 매끄럽다")
        self.assertFalse(auth.matches(p.parse("I/APP_CHAT: evt=X")))


class TestConfigValidation(unittest.TestCase):
    def test_unknown_match_attribute_is_rejected_loudly(self):
        with self.assertRaises(ValueError):
            Config.from_dict({"issueRules": [
                {"id": "bad", "when": {"nope": "x"}}
            ]})

    def test_rule_with_empty_when_never_matches(self):
        cfg = Config.from_dict({"issueRules": [{"id": "empty", "when": {}}]})
        tray = IssueTray(cfg)
        self.assertIsNone(tray.observe(Parser("APP").parse("E/APP_NET: evt=BOOM")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
