"""세션 파일 · 도메인별 상세 로그 스위치 테스트."""

import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens.config import Config  # noqa: E402
from loglens.server import Hub, set_verbose, verbose_state  # noqa: E402
from loglens.sources import build  # noqa: E402
from loglens.sources.filesrc import SESSION_HEADER  # noqa: E402

TABLE = {"id": "rules", "domain": "AUTH", "events": ["RULE_ITEM"], "groupBy": "flowId",
         "countEvent": "RULE_SUMMARY", "countField": "count"}


def line(i, evt="E", flow="f1"):
    return f"08-12 10:00:0{i}.000  1  1 I APP_AUTH: evt={evt} flowId={flow} n={i}"


class TestSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_and_live_lines_are_dropped_while_viewing(self):
        a = Hub(Config.from_dict({"prefix": "APP"}))
        for i in range(3):
            a.ingest(line(i))
        text = a.export_session({"kind": "synth"})
        self.assertTrue(text.startswith(SESSION_HEADER))

        b = Hub(Config.from_dict({"prefix": "APP"}))
        b.ingest("08-12 09:00:00.000  1  1 I APP_AUTH: evt=MINE")
        r = b.import_session("팀원.loglens", text)
        self.assertEqual(r["lines"], 3)
        self.assertEqual([x.event for x in b.buffer], ["E", "E", "E"], "원래 버퍼는 비우고 파일 내용만")
        b.ingest(line(9, "LIVE"))                       # 실시간 줄
        self.assertNotIn("LIVE", [x.event for x in b.buffer], "보는 중에는 실시간 줄을 섞지 않는다")
        self.assertEqual(b.snapshot()["session"]["name"], "팀원.loglens")
        b.go_live()
        self.assertIsNone(b.snapshot()["session"])
        b.ingest(line(9, "LIVE"))
        self.assertEqual([x.event for x in b.buffer], ["LIVE"])

    def test_import_does_not_write_into_my_snapshots(self):
        snap = os.path.join(self.tmp.name, "snaps")
        other = Hub(Config.from_dict({"prefix": "APP", "tables": [TABLE]}))
        for ln in (line(1, "RULE_ITEM") + " code=A", line(2, "RULE_SUMMARY") + " count=1"):
            other.ingest(ln)
        mine = Hub(Config.from_dict({"prefix": "APP", "snapshotDir": snap, "tables": [TABLE]}))
        mine.import_session("x", other.export_session({}))
        self.assertFalse(os.path.exists(os.path.join(snap, "rules")),
                         "남의 세션에 든 묶음이 내 스냅샷으로 저장되면 안 된다")
        # 그래도 표에서는 보인다
        self.assertEqual(mine.tables()[0]["groups"][0]["id"], "f1")

    def test_file_source_skips_session_header(self):
        p = pathlib.Path(self.tmp.name, "s.loglens")
        a = Hub(Config.from_dict({"prefix": "APP"}))
        a.ingest(line(1))
        p.write_text(a.export_session({}), encoding="utf-8")
        got = [ln for ln in build("file", path=str(p)).lines() if not ln.startswith("---")]
        self.assertEqual(got, [line(1)])


class FakeAdb:
    name = "adb"

    def __init__(self, tags=None):
        self.tags = dict(tags or {})
        self.calls = []

    def forced_tags(self):
        return dict(self.tags)

    def set_forced(self, tag, on):
        self.calls.append((tag, on))
        if on:
            self.tags[tag] = "VERBOSE"
        else:
            self.tags.pop(tag, None)
        return True


class TestVerbose(unittest.TestCase):
    CFG = Config.from_dict({"prefix": "APP", "tabs": [
        {"id": "chat", "label": "채팅", "domains": ["CHAT"]},
        {"id": "net", "label": "네트워크", "domains": ["NET", "API2"]}]})

    def test_state_and_toggle(self):
        adb = FakeAdb({"APP_CHAT": "VERBOSE", "OTHER": "DEBUG"})
        st = verbose_state(self.CFG, adb)
        self.assertEqual(st["states"], {"CHAT": True, "NET": False, "API2": False})
        self.assertTrue(set_verbose(self.CFG, adb, "NET", True)["ok"])
        self.assertEqual(adb.calls, [("APP_NET", True)])

    def test_only_configured_domains(self):
        adb = FakeAdb()
        for bad in ("ORG", "CHAT; reboot", "chat", ""):
            self.assertFalse(set_verbose(self.CFG, adb, bad, True)["ok"], bad)
        self.assertEqual(adb.calls, [], "설정에 없는 도메인은 기기에 보내지 않는다")

    def test_non_adb_source(self):
        synth = build("synth")
        self.assertFalse(verbose_state(self.CFG, synth)["available"])
        self.assertFalse(set_verbose(self.CFG, synth, "CHAT", True)["ok"])

    def test_long_tag_is_flagged(self):
        cfg = Config.from_dict({"prefix": "APP", "tabs": [
            {"id": "x", "label": "x", "domains": ["A_VERY_LONG_DOMAIN_NAME"]}]})
        self.assertEqual(verbose_state(cfg, FakeAdb())["tooLong"], ["A_VERY_LONG_DOMAIN_NAME"])


if __name__ == "__main__":
    unittest.main()
