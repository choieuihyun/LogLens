"""표 보강 기능 테스트 — 묶음 이름 / 구현 목록 추출 / 값 형식 검사 / 스냅샷.

앱 소스와 스냅샷 폴더는 임시 디렉토리에 만든다. 실제 앱 소스에 기대지 않는다.
"""

import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens import catalog  # noqa: E402
from loglens.analytics import build_table, check_value, loose_json  # noqa: E402
from loglens.config import Config, merge_catalog  # noqa: E402
from loglens.parser import Parser  # noqa: E402
from loglens.server import Hub  # noqa: E402
from loglens.snapshots import SnapshotStore  # noqa: E402

P = Parser("APP")


def item(flow, code, v1="-", v2="-"):
    return (f"08-12 10:00:00.000  1  1 D APP_AUTH: evt=RULE_ITEM flowId={flow} "
            f"code={code} value1={v1} value2={v2}")


def summary(flow, n):
    return f"08-12 10:00:01.000  1  1 I APP_AUTH: evt=RULE_SUMMARY flowId={flow} count={n}"


def login(flow, uid):
    return f"08-12 09:59:59.000  1  1 I APP_AUTH: evt=LOGIN_START flowId={flow} uid={uid}"


def table_cfg(**extra):
    d = {"id": "rules", "label": "설정", "domain": "AUTH", "events": ["RULE_ITEM"],
         "key": "code", "groupBy": "flowId",
         "countEvent": "RULE_SUMMARY", "countField": "count"}
    d.update(extra)
    return d


class TestLabel(unittest.TestCase):
    def test_group_named_from_other_event(self):
        t = Config.from_dict({"prefix": "APP", "tables": [table_cfg(
            labelFrom={"event": "LOGIN_START", "field": "uid"})]}).tables[0]
        d = build_table(P.parse_lines([login("f1", "kim"), item("f1", "A"),
                                       item("f2", "A")]), t)
        g = {x["id"]: x for x in d["groups"]}
        self.assertEqual(g["f1"]["label"], "kim")
        self.assertIsNone(g["f2"]["label"], "이름 이벤트가 없으면 비워 둔다")


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        (root / "src").mkdir()
        (root / "src" / "Login.java").write_text(
            'if (n.equals("FEAT_A")) {  // 익명 채팅 사용\n'
            '} else if (n.equals("FEAT_B")) { // String u = x.read(y);\n'
            '} else if (n.equals("FEAT_C")) {\n', encoding="utf-8")
        (root / "src" / "Other.kt").write_text(
            'val x = "FEAT_C" // 다른 곳에서 설명\nval y = "FEAT_D"\n', encoding="utf-8")
        # 빌드 산출물에 든 사본은 훑지 않는다
        (root / "build").mkdir()
        (root / "build" / "Stub.java").write_text('"FEAT_STUB"', encoding="utf-8")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def extract(self, pattern=r'"(FEAT_[A-Z0-9_]+)"'):
        return catalog.extract({"root": str(self.root), "pattern": pattern})

    def test_codes_names_and_places(self):
        found, err = self.extract()
        self.assertIsNone(err)
        by = {e["code"]: e for e in found}
        self.assertEqual(sorted(by), ["FEAT_A", "FEAT_B", "FEAT_C", "FEAT_D"])
        self.assertEqual(by["FEAT_A"]["name"], "익명 채팅 사용")
        self.assertEqual(by["FEAT_A"]["where"], os.path.join("src", "Login.java") + ":1")
        # 주석 처리된 코드는 설명이 아니다
        self.assertIsNone(by["FEAT_B"]["name"])
        # 설명이 달린 곳이 대표 위치가 된다
        self.assertEqual(by["FEAT_C"]["name"], "다른 곳에서 설명")
        self.assertTrue(by["FEAT_C"]["where"].startswith(os.path.join("src", "Other.kt")))
        self.assertEqual(by["FEAT_C"]["refs"], 2)

    def test_build_dir_is_skipped(self):
        found, _ = self.extract()
        self.assertNotIn("FEAT_STUB", {e["code"] for e in found})

    def test_missing_root_is_error_not_crash(self):
        found, err = catalog.extract({"root": "/없는/경로", "pattern": "x"})
        self.assertEqual(found, [])
        self.assertIn("찾지 못했다", err)

    def test_bad_pattern_is_error_not_crash(self):
        found, err = self.extract(pattern="(")
        self.assertEqual(found, [])
        self.assertIn("정규식", err)

    def test_manual_entries_override_extracted(self):
        found, _ = self.extract()
        merged = {c["code"]: c for c in merge_catalog(found, [
            {"code": "FEAT_A", "name": "손으로 붙인 이름", "note": None, "type": "int"},
            {"code": "FEAT_Z", "name": "소스에 없음", "note": None}])}
        self.assertEqual(merged["FEAT_A"]["name"], "손으로 붙인 이름")
        self.assertEqual(merged["FEAT_A"]["type"], "int")
        self.assertIn("where", merged["FEAT_A"], "소스 위치는 살아 있어야 한다")
        self.assertIn("FEAT_Z", merged)


class TestCheck(unittest.TestCase):
    def test_types(self):
        self.assertEqual(check_value({"type": "int"}, {"value1": "100"}), [])
        self.assertTrue(check_value({"type": "int"}, {"value1": "1OO"}))
        self.assertEqual(check_value({"type": "bool"}, {"value1": "TRUE"}), [])
        self.assertTrue(check_value({"type": "url"}, {"value1": "ftp.x"}))
        self.assertEqual(check_value({"type": "json"}, {"value1": '{"a"_:_1}'}), [])
        self.assertTrue(check_value({"type": "kv"}, {"value1": "a,b"}))

    def test_empty_is_fine_unless_required(self):
        # 들어오기만 하면 동작하는 항목이 있다. 비어 있는 것 자체는 문제가 아니다.
        self.assertEqual(check_value({"type": "int"}, {"value1": "-"}), [])
        self.assertTrue(check_value({"type": "int", "required": True}, {"value1": "-"}))

    def test_keys_and_pattern_and_field(self):
        self.assertEqual(check_value({"keys": ["TYPE"]}, {"value1": "TYPE=1,X=2"}), [])
        self.assertIn("VALUE", check_value({"keys": ["VALUE"]}, {"value1": "TYPE=1"})[0])
        self.assertTrue(check_value({"pattern": r"\d+", "field": "value2"},
                                    {"value1": "1", "value2": "x"}))

    def test_bad_catalog_pattern_is_reported_not_raised(self):
        self.assertIn("정규식 오류", check_value({"pattern": "("}, {"value1": "x"})[0])

    def test_problems_reach_rows(self):
        t = Config.from_dict({"prefix": "APP", "tables": [table_cfg(
            catalog=[{"code": "SIZE", "type": "int"}])]}).tables[0]
        g = build_table(P.parse_lines([item("f1", "SIZE", "big"), item("f1", "OTHER", "x")]),
                        t)["groups"][0]
        self.assertEqual(g["problemCount"], 1)
        self.assertEqual(g["rows"][1]["problems"], [], "목록에 없는 항목은 검사하지 않는다")

    def test_loose_json_keeps_underscores_inside_strings(self):
        self.assertEqual(loose_json('{"k"_:_"a_b"}'), {"k": "a_b"})
        self.assertIsNone(loose_json("{not json"))


class TestSnapshots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_load_roundtrip_and_overwrite(self):
        s = SnapshotStore(self.tmp.name)
        s.save("rules", {"id": "f/1", "rows": [], "count": 0})
        s.save("rules", {"id": "f/1", "rows": [], "count": 3})
        got = s.load("rules")
        self.assertEqual(len(got), 1, "같은 묶음은 덮어쓴다")
        self.assertEqual(got[0]["count"], 3)
        self.assertTrue(got[0]["saved"])

    def test_broken_file_is_skipped(self):
        s = SnapshotStore(self.tmp.name)
        s.save("rules", {"id": "ok", "rows": []})
        with open(os.path.join(self.tmp.name, "rules", "broken.json"), "w") as f:
            f.write("{")
        self.assertEqual([g["id"] for g in s.load("rules")], ["ok"])

    def hub(self):
        cfg = Config.from_dict({"prefix": "APP", "snapshotDir": self.tmp.name,
                                "bufferSize": 3, "tables": [table_cfg()]})
        return Hub(cfg)

    def test_group_saved_when_summary_arrives_and_survives_buffer(self):
        h = self.hub()
        for ln in (item("f1", "A"), item("f1", "B"), summary("f1", 2)):
            h.ingest(ln)
        # 버퍼(3줄)를 새 묶음으로 밀어낸다
        for ln in (item("f2", "A"), item("f2", "C"), summary("f2", 2)):
            h.ingest(ln)
        t = h.tables()[0]
        ids = [g["id"] for g in t["groups"]]
        self.assertEqual(ids, ["f1", "f2"], "밀려난 f1 은 저장본에서 오고 시간 순서가 유지된다")
        f1 = t["groups"][0]
        self.assertTrue(f1["saved"])
        self.assertEqual(sorted(r["key"] for r in f1["rows"]), ["A", "B"])
        # 저장본끼리도 비교된다
        d = h.table_diff("rules", "f1", "f2")
        self.assertEqual(d["summary"], {"added": 1, "removed": 1, "changed": 0, "same": 1})

    def test_no_snapshot_dir_means_no_files(self):
        cfg = Config.from_dict({"prefix": "APP", "tables": [table_cfg()]})
        h = Hub(cfg)
        h.ingest(item("f1", "A"))
        h.ingest(summary("f1", 1))
        self.assertFalse(h.save_group("rules", "f1"))
        self.assertEqual(os.listdir(self.tmp.name), [])


class TestHubCatalog(unittest.TestCase):
    def test_catalog_source_loaded_at_start_and_reloadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / "A.java"
            src.write_text('"FEAT_A" // 설명 A\n', encoding="utf-8")
            cfg = Config.from_dict({"prefix": "APP", "tables": [table_cfg(
                catalogSource={"root": tmp, "pattern": r'"(FEAT_[A-Z_]+)"'},
                catalog=[{"code": "FEAT_A", "type": "int"}])]})
            h = Hub(cfg)
            cat = {c["code"]: c for c in h.tables()[0]["catalog"]}
            self.assertEqual(cat["FEAT_A"]["name"], "설명 A")
            self.assertEqual(cat["FEAT_A"]["type"], "int")
            src.write_text('"FEAT_A"\n"FEAT_B"\n', encoding="utf-8")
            self.assertEqual(h.reload_catalogs()["rules"]["found"], 2)
            self.assertIn("FEAT_B", {c["code"] for c in h.tables()[0]["catalog"]})

    def test_missing_source_shows_error_and_keeps_manual(self):
        cfg = Config.from_dict({"prefix": "APP", "tables": [table_cfg(
            catalogSource={"root": "/없는/경로", "pattern": "x"}, catalog=["FEAT_M"])]})
        t = Hub(cfg).tables()[0]
        self.assertIn("찾지 못했다", t["catalogError"])
        self.assertEqual([c["code"] for c in t["catalog"]], ["FEAT_M"])

    def test_source_link_reaches_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Config.from_dict({"prefix": "APP", "tables": [table_cfg(
                catalogSource={"root": tmp, "pattern": "x"},
                sourceLink="vscode://file{abs}:{line}")]}).to_dict()["tables"][0]
            self.assertEqual(d["sourceLink"], "vscode://file{abs}:{line}")
            self.assertEqual(d["sourceRoot"], os.path.abspath(tmp))

    def test_source_link_is_in_tables_response(self):
        # 표 창은 /api/tables 만 받는다. 거기에 없으면 링크가 조용히 사라진다.
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config.from_dict({"prefix": "APP", "tables": [table_cfg(
                catalogSource={"root": tmp, "pattern": "x"},
                sourceLink="vscode://file{abs}:{line}")]})
            t = Hub(cfg).tables()[0]
            self.assertEqual(t["sourceLink"], "vscode://file{abs}:{line}")
            self.assertEqual(t["sourceRoot"], os.path.abspath(tmp))


if __name__ == "__main__":
    unittest.main()


class TestOpenSource(unittest.TestCase):
    """catalog 위치를 설정의 명령으로 연다. 명령은 실제로 돌리지 않고 인자만 받는다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name) / "src"
        root.mkdir()
        (root / "A.java").write_text('x\n"FEAT_A" // 설명\n', encoding="utf-8")
        self.root = str(root)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def hub(self, open_cmd=("ide", "--line", "{line}", "{abs}"), catalog=()):
        return Hub(Config.from_dict({"prefix": "APP", "tables": [table_cfg(
            catalogSource={"root": self.root, "pattern": r'"(FEAT_[A-Z_]+)"'},
            sourceOpen=list(open_cmd), catalog=list(catalog))]}))

    def run_(self, argv, **kw):
        self.calls.append(argv)

    def test_opens_file_at_line_without_shell(self):
        r = self.hub().open_source("rules", "FEAT_A", runner=self.run_)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.calls, [["ide", "--line", "2",
                                       os.path.realpath(os.path.join(self.root, "A.java"))]])

    def test_path_outside_root_is_refused(self):
        # 손으로 적은 catalog 가 루트 밖을 가리켜도 열지 않는다
        h = self.hub(catalog=[{"code": "FEAT_X", "where": "../../etc/hosts:1"}])
        r = h.open_source("rules", "FEAT_X", runner=self.run_)
        self.assertFalse(r["ok"])
        self.assertIn("밖", r["error"])
        self.assertEqual(self.calls, [])

    def test_unknown_code_and_missing_command(self):
        self.assertFalse(self.hub().open_source("rules", "NOPE", runner=self.run_)["ok"])
        self.assertFalse(self.hub(open_cmd=()).open_source("rules", "FEAT_A", runner=self.run_)["ok"])
        self.assertEqual(self.calls, [])

    def test_missing_program_is_error_not_crash(self):
        def boom(argv, **kw):
            raise FileNotFoundError("없음")
        r = self.hub().open_source("rules", "FEAT_A", runner=boom)
        self.assertFalse(r["ok"])
        self.assertIn("실행하지 못했다", r["error"])

    def test_client_only_learns_that_it_can_open(self):
        t = self.hub().tables()[0]
        self.assertIs(t["sourceOpen"], True, "명령 자체는 브라우저로 보내지 않는다")
