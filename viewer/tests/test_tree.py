"""계층 재구성 테스트.

뷰어는 언제나 **부분 트리**만 본다. 사용자가 펼친 것만 로그가 남기 때문이다.
그래서 이 테스트는 "완전한 트리"보다 **불완전한 입력을 어떻게 견디는가**에 집중한다.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens.analytics import build_tree  # noqa: E402
from loglens.config import Config  # noqa: E402
from loglens.parser import Parser  # noqa: E402

CFG = Config.from_dict({
    "prefix": "UC",
    "trees": [{
        "id": "org", "label": "조직도", "domain": "MEMBER",
        "events": ["ORG_FETCH_OK"],
        "node": "dept", "parent": "parent", "name": "deptName",
        "metrics": ["subDept", "users"],
    }],
})
TREE = CFG.trees[0]
P = Parser("UC")


def line(dept, parent="-", name=None, event="ORG_FETCH_OK", domain="MEMBER", **f):
    parts = [f"evt={event}", f"dept={dept}", f"parent={parent}"]
    if name:
        parts.append(f"deptName={name}")
    parts += [f"{k}={v}" for k, v in f.items()]
    return f"08-12 10:00:00.000  1  1 D UC_{domain}: " + " ".join(parts)


def build(lines):
    return build_tree(P.parse_lines(lines), TREE)


class TestTreeShape(unittest.TestCase):

    def test_부모_자식이_이어진다(self):
        t = build([
            line("D1", name="본사"),
            line("D2", parent="D1", name="개발팀"),
            line("D3", parent="D2", name="AOS"),
        ])
        self.assertEqual(t["nodeCount"], 3)
        self.assertEqual(t["rootCount"], 1)
        self.assertEqual(t["maxDepth"], 2)
        root = t["roots"][0]
        self.assertEqual(root["id"], "D1")
        self.assertEqual(root["children"][0]["id"], "D2")
        self.assertEqual(root["children"][0]["children"][0]["id"], "D3")

    def test_깊이가_뿌리부터_0(self):
        t = build([line("D1"), line("D2", parent="D1")])
        self.assertEqual(t["roots"][0]["depth"], 0)
        self.assertEqual(t["roots"][0]["children"][0]["depth"], 1)

    def test_이름과_숫자필드를_가져온다(self):
        t = build([line("D1", name="개발팀", subDept=2, users=7)])
        n = t["roots"][0]
        self.assertEqual(n["name"], "개발팀")
        self.assertEqual(n["metrics"], {"subDept": "2", "users": "7"})


class TestPartialTree(unittest.TestCase):
    """실제로는 이쪽이 더 중요하다 — 부분 트리를 견디는지."""

    def test_부모를_못_본_노드도_버리지_않는다(self):
        # 사용자가 중간 부서부터 펼친 경우. 부모 줄이 로그에 없다.
        t = build([line("D9", parent="D_없음", name="고아부서")])
        self.assertEqual(t["nodeCount"], 1)
        self.assertEqual(t["orphanCount"], 1)
        self.assertTrue(t["roots"][0]["orphan"])
        self.assertEqual(t["roots"][0]["name"], "고아부서")

    def test_뿌리가_여러_개일_수_있다(self):
        t = build([line("D1"), line("D2"), line("D3", parent="D1")])
        self.assertEqual(t["rootCount"], 2)
        self.assertEqual(t["orphanCount"], 0)

    def test_같은_노드를_다시_펼치면_횟수만_늘고_중복되지_않는다(self):
        t = build([
            line("D1", name="개발팀", subDept=2),
            line("D1", name="개발팀", subDept=3),   # 접었다 다시 펼침
        ])
        self.assertEqual(t["nodeCount"], 1)
        n = t["roots"][0]
        self.assertEqual(n["hits"], 2)
        self.assertEqual(n["metrics"]["subDept"], "3", "마지막 값으로 갱신되어야 한다")

    def test_부모를_나중에_본_경우에도_이어진다(self):
        # 자식이 먼저 찍히고 부모가 나중에 찍힐 수 있다
        t = build([line("D2", parent="D1"), line("D1")])
        self.assertEqual(t["rootCount"], 1)
        self.assertEqual(t["roots"][0]["id"], "D1")
        self.assertEqual(t["roots"][0]["children"][0]["id"], "D2")


class TestRobustness(unittest.TestCase):

    def test_순환_참조에도_멈춘다(self):
        t = build([line("A", parent="B"), line("B", parent="A")])
        self.assertEqual(t["nodeCount"], 2)
        self.assertLessEqual(t["maxDepth"], 64)

    def test_자기_자신을_부모로_가리켜도_안전하다(self):
        t = build([line("A", parent="A")])
        self.assertEqual(t["rootCount"], 1)

    def test_빈_값은_건너뛴다(self):
        t = build([line("-", parent="-"), line("D1")])
        self.assertEqual(t["nodeCount"], 1)

    def test_다른_도메인과_다른_이벤트는_안_섞인다(self):
        t = build([
            line("D1"),
            line("X1", domain="CHAT"),
            line("X2", event="OTHER_EVENT"),
        ])
        self.assertEqual(t["nodeCount"], 1)

    def test_로그가_없으면_빈_트리(self):
        t = build([])
        self.assertEqual((t["nodeCount"], t["rootCount"], t["maxDepth"]), (0, 0, 0))


class TestRealDeviceShape(unittest.TestCase):
    """실기기에서 관찰한 모양 — 회귀 방지."""

    def test_실기기에서_본_구조가_그대로_선다(self):
        t = build([
            line("D1523", name="CEO", subDept=1, users=1),
            line("D123", name="솔루션본부", subDept=2, users=1),
            line("D1532", parent="D123", name="개발팀", subDept=2, users=1),
            line("D1524", name="영업팀", subDept=0, users=3),
        ])
        self.assertEqual(t["nodeCount"], 4)
        self.assertEqual(t["rootCount"], 3)
        self.assertEqual(t["orphanCount"], 0)
        self.assertEqual(t["maxDepth"], 1)
        sol = next(r for r in t["roots"] if r["id"] == "D123")
        self.assertEqual([c["id"] for c in sol["children"]], ["D1532"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
