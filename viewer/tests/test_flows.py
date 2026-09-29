"""흐름 타임라인 · 기준선 · 스택 줄 → 파일 테스트."""

import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens import callsites  # noqa: E402
from loglens.config import Config  # noqa: E402
from loglens.flows import (BaselineStore, compare, flow_detail, list_flows,  # noqa: E402
                           ts_ms, _gap)
from loglens.parser import Parser  # noqa: E402
from loglens.server import Hub  # noqa: E402

P = Parser("APP")
CFG = Config.from_dict({
    "prefix": "APP",
    "funnels": [{"id": "login", "label": "로그인", "domain": "AUTH",
                 "steps": ["LOGIN_START", "CHECK", "TOKEN", "LOGIN_OK"]}],
    "tables": [{"id": "rules", "domain": "AUTH", "events": ["RULE_ITEM"], "groupBy": "flowId"}],
})


def ev(ts, event, flow="f1", level="I", **f):
    extra = "".join(f" {k}={v}" for k, v in f.items())
    return f"08-12 {ts}  1  1 {level} APP_AUTH: evt={event} flowId={flow}{extra}"


def sysline(ts, level, tag, text):
    return f"08-12 {ts}  1  1 {level} {tag}: {text}"


def recs(lines):
    return P.parse_lines(lines)


class TestTime(unittest.TestCase):
    def test_both_formats(self):
        self.assertEqual(ts_ms("08-12 10:00:01.500") - ts_ms("08-12 10:00:00.000"), 1500)
        self.assertEqual(ts_ms("2026-08-12 10:00:01.500") - ts_ms("2026-08-12 10:00:00.000"), 1500)
        self.assertIsNone(ts_ms("아무거나"))
        self.assertIsNone(ts_ms(None))

    def test_midnight_rollover(self):
        # 연도가 없어도 자정을 넘긴 간격이 음수가 되지 않는다
        self.assertEqual(_gap(ts_ms("08-12 23:59:59.900"), ts_ms("08-13 00:00:00.100")), 200)
        self.assertEqual(_gap(ts_ms("12-31 23:59:59.900"), ts_ms("01-01 00:00:00.100")), 200)


class TestFlows(unittest.TestCase):
    LINES = [
        ev("10:00:00.000", "LOGIN_START", uid="kim"),
        ev("10:00:00.010", "RULE_ITEM", code="A"),
        ev("10:00:00.011", "RULE_ITEM", code="B"),
        ev("10:00:00.012", "RULE_ITEM", code="C"),
        ev("10:00:00.100", "CHECK"),
        sysline("10:00:00.150", "E", "OkHttp", "java.net.SocketTimeoutException: timeout"),
        sysline("10:00:00.160", "D", "Other", "잡음 — 경고/에러가 아니라 안 보여야 함"),
        ev("10:00:00.400", "LOGIN_FAIL", level="W", reason="NETWORK"),
        ev("10:00:05.000", "LOGIN_START", flow="f2", uid="lee"),
        ev("10:00:05.100", "CHECK", flow="f2"),
        ev("10:00:05.300", "TOKEN", flow="f2"),
        ev("10:00:05.350", "LOGIN_OK", flow="f2"),
        ev("10:00:06.000", "LOGIN_START", flow="f3"),
    ]

    def test_list_statuses_and_labels(self):
        by = {f["id"]: f for f in list_flows(recs(self.LINES), CFG)}
        self.assertEqual(by["f1"]["status"], "failure")
        self.assertEqual(by["f2"]["status"], "success")
        self.assertEqual(by["f3"]["status"], "open")
        self.assertEqual(by["f1"]["label"], "kim")
        self.assertEqual(by["f2"]["durationMs"], 350)
        self.assertEqual(by["f1"]["kind"], "login")

    def test_stalled_when_old_and_unfinished(self):
        lines = self.LINES + [sysline("10:01:00.000", "I", "X", "한참 뒤")]
        by = {f["id"]: f for f in list_flows(recs(lines), CFG)}
        self.assertEqual(by["f3"]["status"], "stalled", "오래 멈춘 흐름은 진행 중이 아니다")

    def test_detail_collapses_table_events_and_measures_gaps(self):
        d = flow_detail(recs(self.LINES), CFG, "f1")
        self.assertEqual([s["event"] for s in d["steps"]], ["LOGIN_START", "RULE_ITEM", "CHECK", "LOGIN_FAIL"])
        rule = d["steps"][1]
        self.assertEqual((rule["count"], rule["delta"]), (3, 10))
        self.assertEqual(d["steps"][2]["delta"], 88, "접힌 묶음의 마지막 줄부터 잰다")
        self.assertEqual(d["steps"][3]["offset"], 400)

    def test_context_is_limited_to_the_flow_process(self):
        other = "08-12 10:00:00.200  999  999 E SystemService: 다른 프로세스의 에러"
        d = flow_detail(recs(self.LINES[:6] + [other] + self.LINES[6:]), CFG, "f1")
        self.assertEqual([c["tag"] for c in d["context"]], ["OkHttp"], "다른 앱의 경고는 섞지 않는다")

    def test_detail_context_shows_only_warnings_and_errors_nearby(self):
        d = flow_detail(recs(self.LINES), CFG, "f1")
        self.assertEqual([c["tag"] for c in d["context"]], ["OkHttp"])
        self.assertEqual(d["context"][0]["offset"], 150)

    def test_detail_missing_funnel_steps(self):
        d = flow_detail(recs(self.LINES), CFG, "f1")
        self.assertEqual(d["missing"], ["TOKEN", "LOGIN_OK"])

    def test_unknown_flow_is_none(self):
        self.assertIsNone(flow_detail(recs(self.LINES), CFG, "nope"))

    def test_custom_flow_field(self):
        cfg = Config.from_dict({"prefix": "APP", "flow": {"field": "tx", "labelField": "who"}})
        lines = ["08-12 10:00:00.000  1  1 I APP_NET: evt=REQ tx=t9 who=me",
                 "08-12 10:00:00.200  1  1 I APP_NET: evt=REQ_OK tx=t9"]
        f = list_flows(recs(lines), cfg)[0]
        self.assertEqual((f["id"], f["label"], f["status"]), ("t9", "me", "success"))


class TestCompare(unittest.TestCase):
    BASE = {"steps": [{"event": "LOGIN_START", "delta": 0}, {"event": "CHECK", "delta": 100},
                      {"event": "TOKEN", "delta": 150}, {"event": "LOGIN_OK", "delta": 50}]}

    def step(self, e, d):
        return {"event": e, "delta": d}

    def test_slow_needs_ratio_and_gap(self):
        c = compare([self.step("LOGIN_START", 0), self.step("CHECK", 110),
                     self.step("TOKEN", 900), self.step("LOGIN_OK", 120)], self.BASE, "success")
        st = {p["event"]: p["state"] for p in c["steps"]}
        self.assertEqual(st["TOKEN"], "slow")
        # 50 → 120 은 2배를 넘지만 +70ms 라 느림이 아니다
        self.assertEqual(st["LOGIN_OK"], "same")
        self.assertEqual(c["summary"]["slow"], 1)

    def test_missing_extra_reordered(self):
        c = compare([self.step("LOGIN_START", 0), self.step("TOKEN", 100), self.step("CHECK", 100),
                     self.step("NEW_STEP", 10)], self.BASE, "failure")
        self.assertEqual(c["missing"], ["LOGIN_OK"])
        self.assertTrue(c["reordered"])
        self.assertEqual(c["summary"]["extra"], 1)
        self.assertFalse(c["summary"]["ok"])

    def test_open_flow_is_not_missing_yet(self):
        c = compare([self.step("LOGIN_START", 0), self.step("CHECK", 100)], self.BASE, "open")
        self.assertEqual(c["missing"], [], "진행 중인 흐름의 뒤쪽은 '안 온' 게 아니라 '아직' 이다")
        self.assertTrue(c["summary"]["ok"])


class TestBaselineStoreAndHub(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_and_clear(self):
        s = BaselineStore(self.tmp.name)
        d = flow_detail(recs(TestFlows.LINES), CFG, "f2")
        self.assertTrue(s.save(d))
        self.assertEqual(s.all()["login"]["flowId"], "f2")
        self.assertTrue(s.clear("login"))
        self.assertEqual(s.all(), {})

    def test_hub_baseline_flow(self):
        cfg = Config.from_dict({"prefix": "APP", "snapshotDir": self.tmp.name,
                                "funnels": CFG.to_dict()["funnels"]})
        h = Hub(cfg)
        for ln in TestFlows.LINES:
            h.ingest(ln)
        self.assertTrue(h.set_baseline("f2")["ok"])
        d = h.flow("f1")
        self.assertEqual(d["baseline"]["flowId"], "f2")
        self.assertIn("LOGIN_OK", d["compare"]["missing"])
        listed = {f["id"]: f for f in h.flows()["flows"]}
        self.assertFalse(listed["f1"]["deviation"]["ok"])
        self.assertFalse(listed["f1"]["deviation"]["flag"], "실패는 '실패' 로 보인다 — '다름' 으로 또 띄우지 않는다")
        self.assertTrue(listed["f2"]["deviation"]["ok"])

    def test_slow_success_is_flagged(self):
        cfg = Config.from_dict({"prefix": "APP", "snapshotDir": self.tmp.name,
                                "funnels": CFG.to_dict()["funnels"]})
        h = Hub(cfg)
        for ln in TestFlows.LINES + [
                ev("10:00:08.000", "LOGIN_START", flow="f9"), ev("10:00:08.100", "CHECK", flow="f9"),
                ev("10:00:09.500", "TOKEN", flow="f9"), ev("10:00:09.550", "LOGIN_OK", flow="f9")]:
            h.ingest(ln)
        h.set_baseline("f2")
        f9 = {f["id"]: f for f in h.flows()["flows"]}["f9"]
        self.assertEqual(f9["status"], "success")
        self.assertTrue(f9["deviation"]["flag"], "성공했지만 느려진 흐름을 찾는 게 이 표시의 목적이다")

    def test_hub_without_snapshot_dir_explains(self):
        h = Hub(Config.from_dict({"prefix": "APP"}))
        for ln in TestFlows.LINES:
            h.ingest(ln)
        r = h.set_baseline("f2")
        self.assertFalse(r["ok"])
        self.assertIn("snapshotDir", r["error"])
        self.assertFalse(h.flows()["canBaseline"])


class TestFrames(unittest.TestCase):
    def test_find_by_package_path_and_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            for sub in ("main/java/com/x/chat", "debug/java/com/x/chat", "main/java/com/y"):
                d = pathlib.Path(tmp, sub)
                d.mkdir(parents=True)
                (d / "Repo.kt").write_text("x", encoding="utf-8")
            files, err = callsites.find_frame({"root": tmp}, "com.x.chat", "Repo.kt")
            self.assertIsNone(err)
            # 소스 세트가 둘이면 후보도 둘. 다른 패키지의 같은 이름 파일은 아니다
            self.assertEqual(files, [os.path.join("debug", "java", "com", "x", "chat", "Repo.kt"),
                                     os.path.join("main", "java", "com", "x", "chat", "Repo.kt")])

    def test_rejects_non_frame_input(self):
        for pkg, fn in (("a.b", "../../etc/passwd"), ("a/b", "Repo.kt"), ("a.b", "Repo.txt")):
            self.assertEqual(callsites.find_frame({"root": "/"}, pkg, fn)[1], "스택 줄 모양이 아니다")


if __name__ == "__main__":
    unittest.main()
