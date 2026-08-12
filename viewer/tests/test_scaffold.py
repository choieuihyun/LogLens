"""config 자동 생성 테스트.

특히 **개인정보**: 표본을 읽되 메시지 본문이 산출물에 새어나가면 안 된다.
그게 이 기능의 전제다.
"""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens.config import Config  # noqa: E402
from loglens.parser import Parser  # noqa: E402
from loglens.scaffold import LogLandscape, build_config, report  # noqa: E402

P = Parser("APP")


def line(pid, tag, body, level="I"):
    return f"08-12 11:23:45.678 {pid:5d} {pid:5d} {level} {tag}: {body}"


class TestStem(unittest.TestCase):
    def s(self, tag):
        return LogLandscape.stem(tag)

    def test_strips_class_suffixes(self):
        self.assertEqual(self.s("ChatListFragment"), "CHAT")
        self.assertEqual(self.s("NotificationTask"), "NOTIFICATION")
        self.assertEqual(self.s("MemberFragment"), "MEMBER")

    def test_merges_singular_and_plural(self):
        # Chats 와 ChatListFragment 가 다른 탭이 되면 탭 기능이 무의미해진다
        self.assertEqual(self.s("Chats"), self.s("ChatListFragment"))

    def test_keeps_double_s(self):
        self.assertEqual(self.s("Address"), "ADDRESS")

    def test_acronym_prefix_gets_second_token(self):
        # DBLog → DB 만 남으면 정보가 없다
        self.assertEqual(self.s("DBLog"), "DBLOG")

    def test_dotted_tag_uses_last_segment(self):
        self.assertEqual(self.s("com.example.SyncWorker"), "SYNC")

    def test_plain_tag(self):
        self.assertEqual(self.s("EventBus"), "EVENT")


class TestLandscape(unittest.TestCase):
    def build(self, app_pid=None):
        land = LogLandscape(prefix="APP", app_pid=app_pid)
        rows = [
            line(551, "APP_AUTH", "evt=LOGIN_OK uid=1"),
            line(551, "APP_AUTH", "evt=LOGIN_FAIL reason=X", "W"),
            line(551, "ChatListFragment", "onCreate 비밀번호=hunter2"),
            line(551, "Chats", "list size 12"),
            line(551, "Chats", "list size 13"),
            line(999, "wpa_supplicant", "wlan0 CTRL-EVENT"),
            line(999, "cnss-daemon", "noise"),
        ]
        for r in rows:
            land.observe(P.parse(r))
        return land

    def test_pid_filter_excludes_other_processes(self):
        land = self.build(app_pid=551)
        self.assertNotIn("wpa_supplicant", land.legacy_tags)
        self.assertIn("wpa_supplicant", land.other_tags)
        self.assertIn("Chats", land.legacy_tags)

    def test_denylist_used_when_pid_unknown(self):
        land = self.build(app_pid=None)
        self.assertNotIn("wpa_supplicant", land.legacy_tags,
                         "pid 를 몰라도 시스템 태그는 2차 방어선이 걸러야 한다")

    def test_structured_records_become_domains(self):
        land = self.build(app_pid=551)
        self.assertEqual(land.domains["AUTH"], 2)
        self.assertEqual(land.structured, 2)
        self.assertIn("LOGIN_OK", land.events["AUTH"])

    def test_clusters_merge_related_tags(self):
        land = self.build(app_pid=551)
        chat = next(c for c in land.clusters() if c[0] == "CHAT")
        self.assertEqual(sorted(chat[1]), ["ChatListFragment", "Chats"])
        self.assertEqual(chat[2], 3)


class TestBuildConfig(unittest.TestCase):
    def setUp(self):
        land = LogLandscape(prefix="APP", app_pid=551)
        for _ in range(6):
            land.observe(P.parse(line(551, "APP_AUTH", "evt=LOGIN_OK uid=1")))
        for _ in range(6):
            land.observe(P.parse(line(551, "ChatListFragment", "@@@ 내 전화번호 010-1234-5678")))
        land.observe(P.parse(line(551, "RareTag", "한 번만 찍힌 태그")))
        self.land = land
        self.cfg = build_config(land, package="com.example.app")

    def test_migrated_domain_becomes_domain_tab(self):
        auth = next(t for t in self.cfg["tabs"] if t["id"] == "auth")
        self.assertEqual(auth["domains"], ["AUTH"])
        self.assertNotIn("legacyTagPattern", auth)

    def test_legacy_cluster_becomes_pattern_tab(self):
        chat = next(t for t in self.cfg["tabs"] if t["id"] == "chat")
        self.assertIn("legacyTagPattern", chat)
        self.assertEqual(chat["domains"], ["CHAT"],
                         "이관되면 채워질 도메인을 미리 적어 둔다")

    def test_rare_tags_dropped(self):
        self.assertNotIn("raretag", [t["id"] for t in self.cfg["tabs"]])

    def test_generated_config_actually_loads(self):
        # 자동 생성물이 스스로 만든 스키마를 통과하지 못하면 아무 의미가 없다
        cfg = Config.from_dict({k: v for k, v in self.cfg.items() if k != "$schema"})
        self.assertEqual(cfg.prefix, "APP")
        self.assertEqual(cfg.package, "com.example.app")
        self.assertTrue(cfg.issue_rules)
        chat = next(t for t in cfg.tabs if t.id == "chat")
        self.assertTrue(chat.matches(P.parse(line(551, "ChatListFragment", "x"))))
        self.assertTrue(chat.matches(P.parse(line(551, "APP_CHAT", "evt=X"))),
                        "이관 후에도 같은 탭이 잡아야 한다")

    def test_no_message_content_leaks_into_output(self):
        blob = json.dumps(self.cfg, ensure_ascii=False)
        for secret in ("010-1234-5678", "전화번호", "@@@", "uid=1", "LOGIN_OK"):
            self.assertNotIn(secret, blob,
                             f"메시지 본문이 config 로 새어나갔다: {secret}")

    def test_report_has_no_message_content(self):
        txt = report(self.land)
        self.assertNotIn("010-1234-5678", txt)
        self.assertNotIn("@@@", txt)
        self.assertIn("ChatListFragment", txt, "태그 이름은 보여줘야 쓸모가 있다")

    def test_report_flags_unmigrated_project(self):
        land = LogLandscape(prefix="APP", app_pid=1)
        land.observe(P.parse(line(1, "SomeTag", "x")))
        self.assertIn("구조화 로그가 없습니다", report(land))


if __name__ == "__main__":
    unittest.main(verbosity=2)
