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
        "childCount": "subDept", "depthField": "depth",
        "scope": "orgId",
        "leaf": {"events": ["ORG_USER"], "node": "uid", "parent": "dept",
                 "name": "name", "truncatedEvent": "ORG_USER_TRUNCATED",
                 "truncatedCount": "skipped"},
    }],
})
TREE = CFG.trees[0]
P = Parser("UC")


def line(dept, parent="-", name=None, event="ORG_FETCH_OK", domain="MEMBER",
         org="ucware", **f):
    parts = [f"evt={event}", f"orgId={org}", f"dept={dept}", f"parent={parent}"]
    if name:
        parts.append(f"deptName={name}")
    parts += [f"{k}={v}" for k, v in f.items()]
    return f"08-12 10:00:00.000  1  1 D UC_{domain}: " + " ".join(parts)


def user(dept, uid, name, org="ucware"):
    """부서 아래 사람 한 명."""
    return (f"08-12 10:00:00.000  1  1 D UC_MEMBER: evt=ORG_USER "
            f"orgId={org} dept={dept} uid={uid} name={name}")


def truncated(dept, skipped, org="ucware"):
    return (f"08-12 10:00:00.000  1  1 D UC_MEMBER: evt=ORG_USER_TRUNCATED "
            f"orgId={org} dept={dept} shown=50 skipped={skipped}")


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

    def test_식별자가_비어도_최상위로_살린다(self):
        # 예전에는 이 줄을 버렸다. 그러면 "자식이 몇 개여야 하는지" 가 통째로 날아간다.
        t = build([line("-", parent="-", name="조직도"), line("D1", parent="-")])
        self.assertEqual(t["nodeCount"], 2)
        self.assertEqual(t["rootCount"], 1)
        self.assertEqual(t["roots"][0]["name"], "조직도")

    def test_노드_식별자_자체가_없으면_건너뛴다(self):
        bad = "08-12 10:00:00.000  1  1 D UC_MEMBER: evt=ORG_FETCH_OK deptName=이름만"
        t = build([bad, line("D1")])
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


class TestRootSentinel(unittest.TestCase):
    """최상위 노드는 식별자가 비어 있다("-"). 이걸 버리면 트리가 쪼개진다."""

    def test_식별자가_빈_최상위_노드를_살린다(self):
        t = build([line("-", name="조직도", subDept=7, depth=0)])
        self.assertEqual(t["nodeCount"], 1)
        self.assertEqual(t["roots"][0]["name"], "조직도")
        self.assertEqual(t["roots"][0]["expected"], 7)

    def test_parent_가_대시면_최상위의_자식이지_고아가_아니다(self):
        t = build([
            line("-", name="조직도", subDept=2, depth=0),
            line("D1", parent="-", name="CEO", depth=1),
            line("D2", parent="-", name="영업팀", depth=1),
        ])
        self.assertEqual(t["rootCount"], 1, "루트 하나로 모여야 한다")
        self.assertEqual(t["orphanCount"], 0)
        self.assertEqual([c["id"] for c in t["roots"][0]["children"]], ["D1", "D2"])

    def test_최상위를_못_봤으면_각자_뿌리가_된다(self):
        t = build([line("D1", parent="-"), line("D2", parent="-")])
        self.assertEqual(t["rootCount"], 2)
        self.assertEqual(t["orphanCount"], 0)


class TestUnexpanded(unittest.TestCase):
    """앱이 '자식 N개' 라고 했는데 몇 개만 본 경우 — 어디를 더 펼쳐야 하는지."""

    def test_안_펼친_자식_수를_센다(self):
        t = build([
            line("D1", name="본사", subDept=3),
            line("D2", parent="D1", subDept=0),
        ])
        root = t["roots"][0]
        self.assertEqual(root["expected"], 3)
        self.assertEqual(root["missing"], 2)
        self.assertEqual(t["missingTotal"], 2)

    def test_다_펼쳤으면_안_펼친_게_없다(self):
        t = build([
            line("D1", subDept=1),
            line("D2", parent="D1", subDept=0),
        ])
        self.assertEqual(t["missingTotal"], 0)


class TestDepthValidation(unittest.TestCase):
    """depth 는 parent 와 중복 정보다. 트리는 parent 로만 세우고 depth 는 검증에 쓴다."""

    def test_깊이가_맞으면_불일치_0(self):
        t = build([
            line("-", depth=0, subDept=1),
            line("D1", parent="-", depth=1),
            line("D2", parent="D1", depth=2),
        ])
        self.assertEqual(t["depthMismatch"], 0)

    def test_parent_가_잘못되면_깊이_불일치로_드러난다(self):
        # 앱은 depth=2 라는데 parent 로 세우면 0 이다 → parent 필드가 깨졌다는 신호
        t = build([line("D2", parent="없는부서", depth=2)])
        self.assertEqual(t["depthMismatch"], 1)
        self.assertTrue(t["roots"][0]["depthMismatch"])


class TestRealDeviceShape(unittest.TestCase):
    """실기기 표본 그대로 — 회귀 방지."""

    SAMPLE = [
        line("-", name="조직도", depth=0, subDept=7, users=0),
        line("D1523", parent="-", name="CEO", depth=1, subDept=1, users=1),
        line("D549", parent="D1523", name="연구소", depth=2, subDept=0, users=1),
        line("D123", parent="-", name="솔루션_사업본부", depth=1, subDept=2, users=1),
        line("D1532", parent="D123", name="개발팀", depth=2, subDept=2, users=1),
        line("D538", parent="D1532", name="서버", depth=3, subDept=1, users=3),
        line("D539", parent="D1532", name="클라이언트", depth=3, subDept=4, users=1),
        line("D1524", parent="-", name="영업팀", depth=1, subDept=0, users=3),
    ]

    def test_실기기_표본이_한_트리로_선다(self):
        t = build(self.SAMPLE)
        self.assertEqual(t["nodeCount"], 8)
        self.assertEqual(t["rootCount"], 1)
        self.assertEqual(t["orphanCount"], 0)
        self.assertEqual(t["maxDepth"], 3)
        self.assertEqual(t["depthMismatch"], 0, "parent 로 세운 깊이가 앱의 depth 와 맞아야 한다")

    def test_가지가_제대로_갈라진다(self):
        t = build(self.SAMPLE)
        root = t["roots"][0]
        self.assertEqual([c["name"] for c in root["children"]],
                         ["CEO", "솔루션_사업본부", "영업팀"])
        dev = root["children"][1]["children"][0]
        self.assertEqual(dev["name"], "개발팀")
        self.assertEqual([c["name"] for c in dev["children"]], ["서버", "클라이언트"])

    def test_안_펼친_가지가_보인다(self):
        t = build(self.SAMPLE)
        root = t["roots"][0]
        self.assertEqual(root["missing"], 4, "루트는 7개라는데 3개만 봤다")
        client = t["roots"][0]["children"][1]["children"][0]["children"][1]
        self.assertEqual(client["name"], "클라이언트")
        self.assertEqual(client["missing"], 4)


class TestDeepTree(unittest.TestCase):
    """6단계 실기기 표본 — 깊은 가지와 형제 분기 회귀 방지."""

    SAMPLE = [
        line("-", name="조직도", depth=0, subDept=7, users=0),
        line("D1523", parent="-", name="CEO", depth=1, subDept=1, users=1),
        line("D549", parent="D1523", name="연구소", depth=2, subDept=0, users=1),
        line("D123", parent="-", name="솔루션_사업본부", depth=1, subDept=2, users=1),
        line("D1532", parent="D123", name="개발팀", depth=2, subDept=2, users=1),
        line("D538", parent="D1532", name="서버", depth=3, subDept=1, users=3),
        line("D539", parent="D1532", name="클라이언트", depth=3, subDept=4, users=1),
        line("D540", parent="D539", name="PC", depth=4, subDept=0, users=2),
        line("D541", parent="D539", name="MOBILE", depth=4, subDept=2, users=1),
        line("D561", parent="D541", name="AOS", depth=5, subDept=0, users=2),
        line("D562", parent="D541", name="IOS", depth=5, subDept=0, users=2),
        line("D1524", parent="-", name="영업팀", depth=1, subDept=0, users=3),
    ]

    def setUp(self):
        self.t = build(self.SAMPLE)
        self.by = {}
        def walk(n):
            self.by[n.get("name") or n["id"]] = n
            for c in n["children"]:
                walk(c)
        for r in self.t["roots"]:
            walk(r)

    def test_6단계가_한_트리로_선다(self):
        self.assertEqual(self.t["nodeCount"], 12)
        self.assertEqual(self.t["rootCount"], 1)
        self.assertEqual(self.t["maxDepth"], 5)
        self.assertEqual(self.t["orphanCount"], 0)
        self.assertEqual(self.t["depthMismatch"], 0)

    def test_형제가_여러_깊이에서_갈라진다(self):
        self.assertEqual([c["name"] for c in self.by["개발팀"]["children"]], ["서버", "클라이언트"])
        self.assertEqual([c["name"] for c in self.by["클라이언트"]["children"]], ["PC", "MOBILE"])
        self.assertEqual([c["name"] for c in self.by["MOBILE"]["children"]], ["AOS", "IOS"])

    def test_안_펼친_개수가_맞는다(self):
        self.assertEqual(self.by["조직도"]["missing"], 4)
        self.assertEqual(self.by["서버"]["missing"], 1)
        self.assertEqual(self.by["클라이언트"]["missing"], 2)

    def test_말단은_안_펼친_게_없다(self):
        for leaf in ("연구소", "PC", "AOS", "IOS", "영업팀"):
            self.assertEqual(self.by[leaf]["missing"], 0, leaf)


class TestScope(unittest.TestCase):
    """최상위 컨테이너가 여럿일 때 서로 섞이면 안 된다."""

    def test_컨테이너가_둘이면_트리도_둘이다(self):
        t = build([
            line("-", name="조직도", org="ucware", subDept=1),
            line("D1", parent="-", name="CEO", org="ucware"),
            line("-", name="협력사", org="partner", subDept=1),
            line("P1", parent="-", name="협력사부서", org="partner"),
        ])
        self.assertEqual(t["scopeCount"], 2)
        self.assertEqual(t["rootCount"], 2)
        names = {r["name"] for r in t["roots"]}
        self.assertEqual(names, {"조직도", "협력사"})

    def test_남의_조직_부서가_섞이지_않는다(self):
        t = build([
            line("-", name="조직도", org="ucware", subDept=1),
            line("D1", parent="-", name="CEO", org="ucware"),
            line("-", name="협력사", org="partner", subDept=1),
            line("P1", parent="-", name="협력사부서", org="partner"),
        ])
        ucware = next(r for r in t["roots"] if r["name"] == "조직도")
        self.assertEqual([c["name"] for c in ucware["children"]], ["CEO"])

    def test_같은_식별자라도_범위가_다르면_다른_노드다(self):
        t = build([line("D1", name="우리부서", org="a"),
                   line("D1", name="남의부서", org="b")])
        self.assertEqual(t["nodeCount"], 2)


class TestPeople(unittest.TestCase):
    """부서 아래 사람을 말단 노드로."""

    def test_사람이_부서_아래에_붙는다(self):
        t = build([line("D1", name="개발팀", subDept=0),
                   user("D1", "kim", "김"), user("D1", "lee", "이")])
        dept = t["roots"][0]
        self.assertEqual([c["name"] for c in dept["children"]], ["김", "이"])
        self.assertTrue(all(c["kind"] == "leaf" for c in dept["children"]))

    def test_같은_사람이_두_부서에_나와도_안_덮인다(self):
        # 겸직이거나 상위 부서에도 소속으로 잡히는 경우. 실측에서 나왔다.
        t = build([
            line("D539", name="클라이언트", subDept=1),
            line("D540", parent="D539", name="PC", subDept=0),
            user("D539", "kim", "김"),
            user("D540", "kim", "김"),
        ])
        client = t["roots"][0]
        pc = next(c for c in client["children"] if c["kind"] == "node")
        self.assertEqual(len([c for c in client["children"] if c["kind"] == "leaf"]), 1)
        self.assertEqual(len([c for c in pc["children"] if c["kind"] == "leaf"]), 1)
        self.assertEqual(t["nodeCount"], 4, "사람 둘이 각각 살아 있어야 한다")

    def test_사람은_부서_수에_안_들어간다(self):
        # subDept 는 부서만 센다. 사람이 자식에 섞여도 "미관측" 계산이 틀리면 안 된다.
        t = build([line("D1", name="개발팀", subDept=2),
                   line("D2", parent="D1", subDept=0),
                   user("D1", "kim", "김")])
        self.assertEqual(t["roots"][0]["missing"], 1)

    def test_생략된_인원을_표시한다(self):
        t = build([line("D1", name="개발팀", subDept=0),
                   user("D1", "kim", "김"), truncated("D1", 7)])
        self.assertEqual(t["roots"][0]["truncated"], 7)
        self.assertEqual(t["truncatedTotal"], 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
