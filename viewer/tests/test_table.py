"""표로 묶기 + 묶음 비교 테스트.

서버 설정 목록처럼 항목 하나당 한 줄로 오는 로그를 전제로 한다.
실제 데이터가 가진 성질 셋을 그대로 흉내낸다:
  - 한 묶음 안에서 같은 key 가 여러 번 나온다 (같은 코드에 값이 여럿)
  - 묶음마다 순서가 다르다
  - 앱이 "몇 개 보냈다" 를 따로 찍어 준다
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens.analytics import build_table, diff_groups  # noqa: E402
from loglens.config import Config  # noqa: E402
from loglens.parser import Parser  # noqa: E402

CFG = Config.from_dict({
    "prefix": "APP",
    "tables": [{
        "id": "rules", "label": "서버 설정", "domain": "AUTH",
        "events": ["RULE_ITEM"], "key": "code", "groupBy": "flowId",
        "countEvent": "RULE_SUMMARY", "countField": "count",
    }],
})
TABLE = CFG.tables[0]
P = Parser("APP")


def item(flow, code, v1="-", v2="-", ts="10:00:00.000"):
    return (f"08-12 {ts}  1  1 D APP_AUTH: evt=RULE_ITEM flowId={flow} "
            f"code={code} value1={v1} value2={v2}")


def summary(flow, n):
    return f"08-12 10:00:01.000  1  1 I APP_AUTH: evt=RULE_SUMMARY flowId={flow} count={n} | 수신 완료"


def build(lines):
    return build_table(P.parse_lines(lines), TABLE)


class TestBuild(unittest.TestCase):
    def test_groups_by_flow_and_keeps_repeated_keys(self):
        t = build([
            item("f1", "FEAT_A", "1"),
            item("f1", "FEAT_MULTI", "TYPE=INT,IDENT=a"),
            item("f1", "FEAT_MULTI", "TYPE=INT,IDENT=b"),
            item("f2", "FEAT_A", "2"),
        ])
        self.assertEqual([g["id"] for g in t["groups"]], ["f1", "f2"])
        f1 = t["groups"][0]
        self.assertEqual(f1["count"], 3)
        # 같은 key 가 두 번이어도 둘 다 남는다
        self.assertEqual([r["key"] for r in f1["rows"]], ["FEAT_A", "FEAT_MULTI", "FEAT_MULTI"])

    def test_columns_exclude_key_and_group(self):
        t = build([item("f1", "FEAT_A", "1", "x")])
        self.assertEqual(t["columns"], ["value1", "value2"])
        self.assertEqual(t["groups"][0]["rows"][0]["values"], {"value1": "1", "value2": "x"})

    def test_other_events_are_ignored(self):
        t = build([
            "08-12 10:00:00.000  1  1 I APP_AUTH: evt=LOGIN_START flowId=f1 uid=1",
            item("f1", "FEAT_A"),
            "08-12 10:00:00.000  1  1 D SomeLegacyTag: RULE_ITEM code=FEAT_A",
        ])
        self.assertEqual(t["groups"][0]["count"], 1)

    def test_complete_only_when_app_said_how_many(self):
        t = build([item("f1", "A"), item("f1", "B"), summary("f1", 2),
                   item("f2", "A"), summary("f2", 5),
                   item("f3", "A")])
        g = {x["id"]: x for x in t["groups"]}
        self.assertIs(g["f1"]["complete"], True)
        # 버퍼가 앞부분을 밀어낸 경우: 기대 5개인데 1개만 있다
        self.assertIs(g["f2"]["complete"], False)
        self.assertEqual(g["f2"]["expected"], 5)
        # 기대 개수를 모르면 단정하지 않는다
        self.assertIsNone(g["f3"]["complete"])

    def test_bad_count_is_unknown_not_crash(self):
        t = build([item("f1", "A"), summary("f1", "abc")])
        self.assertIsNone(t["groups"][0]["complete"])

    def test_without_group_by_everything_is_one_group(self):
        cfg = Config.from_dict({"prefix": "APP", "tables": [{
            "id": "r", "domain": "AUTH", "events": ["RULE_ITEM"]}]})
        t = build_table(P.parse_lines([item("f1", "A"), item("f2", "B")]), cfg.tables[0])
        self.assertEqual(len(t["groups"]), 1)
        self.assertEqual(t["groups"][0]["count"], 2)


class TestDiff(unittest.TestCase):
    def diff(self, lines):
        t = build(lines)
        g = {x["id"]: x for x in t["groups"]}
        return diff_groups(g["f1"], g["f2"], t["columns"])

    def by_key(self, d):
        return {r["key"]: r for r in d["rows"]}

    def test_order_does_not_matter(self):
        d = self.diff([
            item("f1", "A", "1"), item("f1", "B", "2"), item("f1", "C", "3"),
            item("f2", "C", "3"), item("f2", "A", "1"), item("f2", "B", "2"),
        ])
        self.assertEqual(d["summary"], {"added": 0, "removed": 0, "changed": 0, "same": 3})

    def test_added_removed_changed(self):
        d = self.by_key(self.diff([
            item("f1", "SAME", "1"), item("f1", "GONE", "x"), item("f1", "EDIT", "old"),
            item("f2", "SAME", "1"), item("f2", "NEW", "y"), item("f2", "EDIT", "new"),
        ]))
        self.assertEqual(d["SAME"]["status"], "same")
        self.assertEqual(d["GONE"]["status"], "removed")
        self.assertEqual(d["NEW"]["status"], "added")
        self.assertEqual(d["EDIT"]["status"], "changed")
        self.assertEqual(d["EDIT"]["a"], [{"value1": "old", "value2": "-"}])
        self.assertEqual(d["EDIT"]["b"], [{"value1": "new", "value2": "-"}])

    def test_repeated_key_compares_each_value(self):
        # 같은 코드에 값이 여럿이면 그중 하나만 바뀌어도 잡아야 하고, 안 바뀐 것은 공통으로 남는다
        d = self.by_key(self.diff([
            item("f1", "MULTI", "IDENT=a"), item("f1", "MULTI", "IDENT=b"),
            item("f2", "MULTI", "IDENT=b"), item("f2", "MULTI", "IDENT=c"),
        ]))["MULTI"]
        self.assertEqual(d["status"], "changed")
        self.assertEqual([x["value1"] for x in d["a"]], ["IDENT=a"])
        self.assertEqual([x["value1"] for x in d["b"]], ["IDENT=c"])
        self.assertEqual([x["value1"] for x in d["common"]], ["IDENT=b"])

    def test_count_change_is_a_change(self):
        # 집합으로 비교하면 놓치는 경우: 같은 값이 두 번 → 한 번
        d = self.by_key(self.diff([
            item("f1", "DUP", "1"), item("f1", "DUP", "1"),
            item("f2", "DUP", "1"),
        ]))["DUP"]
        self.assertEqual(d["status"], "changed")
        self.assertEqual(len(d["a"]), 1)
        self.assertEqual(d["b"], [])

    def test_completeness_is_passed_through(self):
        d = self.diff([item("f1", "A"), summary("f1", 9), item("f2", "A"), summary("f2", 1)])
        self.assertIs(d["aComplete"], False)
        self.assertIs(d["bComplete"], True)


class TestCatalog(unittest.TestCase):
    """앱이 구현해 둔 key 목록. 값 유무가 아니라 "들어왔나" 를 보기 위한 것."""

    def cfg(self, catalog):
        return Config.from_dict({"prefix": "APP", "tables": [{
            "id": "r", "domain": "AUTH", "events": ["RULE_ITEM"], "catalog": catalog}]}).tables[0]

    def test_strings_and_objects_are_normalized(self):
        t = self.cfg(["FEAT_A", {"code": "FEAT_B", "name": "조직도 탭", "note": "값 없이 동작"}])
        self.assertEqual(t.catalog, [
            {"code": "FEAT_A", "name": None, "note": None},
            {"code": "FEAT_B", "name": "조직도 탭", "note": "값 없이 동작"},
        ])

    def test_malformed_entries_are_dropped_not_fatal(self):
        t = self.cfg(["FEAT_A", {"name": "코드 없음"}, 3, None])
        self.assertEqual([c["code"] for c in t.catalog], ["FEAT_A"])

    def test_catalog_reaches_table_and_client(self):
        t = self.cfg(["FEAT_A"])
        self.assertEqual(build_table([], t)["catalog"][0]["code"], "FEAT_A")
        self.assertEqual(t.to_dict()["catalog"][0]["code"], "FEAT_A")

    def test_no_catalog_is_empty(self):
        self.assertEqual(TABLE.catalog, [])


class TestConfig(unittest.TestCase):
    def test_tables_reach_the_client(self):
        d = CFG.to_dict()["tables"][0]
        self.assertEqual(d["groupBy"], "flowId")
        self.assertEqual(d["events"], ["RULE_ITEM"])
        self.assertEqual(d["countEvent"], "RULE_SUMMARY")

    def test_no_tables_is_empty_list(self):
        self.assertEqual(Config.default().to_dict()["tables"], [])


if __name__ == "__main__":
    unittest.main()
