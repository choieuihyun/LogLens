"""로그 → 코드 줄 테스트. 가짜 앱 소스를 임시 디렉토리에 만든다.

실제 앱이 가진 모양을 흉내낸다: 로그를 도우미 클래스로 감싸고, 업무 코드가 도우미를 부른다.
"""

import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens import callsites  # noqa: E402
from loglens.config import Config  # noqa: E402
from loglens.server import Hub, open_at  # noqa: E402

HELPER = """package x;
/**
 * 사용 예:
 * LogLens.i(AppDomain.AUTH, "LOGIN_OK", "uid", uid);
 */
public final class AuthTrace {
    public static void loginStart(String flowId, String uid) {
        LogLens.i(AppDomain.AUTH, "LOGIN_START",
                "uid", uid);
    }

    public static void profileFetch(String flowId) {
        LogLens.i(AppDomain.AUTH, "PROFILE_FETCH", "flowId", flowId);
    }

    static void loginResult(String flowId, boolean ok) {
        if (ok) {
            LogLens.i(AppDomain.AUTH, "LOGIN_OK", "flowId", flowId);
        } else {
            LogLens.w(AppDomain.AUTH, "LOGIN_FAIL", "flowId", flowId);
        }
    }
}
"""

TASK = """package x;
class SignInFlow {
    void run() {
        AuthTrace.loginStart(id, name);
        if (cached) {
            AuthTrace.profileFetch(id);
        } else {
            AuthTrace.profileFetch(id);
        }
        AuthTrace.loginResult(id, true);
        LogLens.d(AppDomain.AUTH, "DIRECT_EVT", "k", v);
    }
}
"""

KT_HELPER = """package x
object ChatLog {
    fun send(room: String, ok: Boolean) {
        LogLens.i(AppDomain.CHAT, "SEND_OK", "room" to room)
    }
}
"""

KT_CALLER = """package x
class Sender {
    fun go() { ChatLog.send(room, true) }
}
"""


class TestFind(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        src = pathlib.Path(self.tmp.name) / "src"
        (src / "x").mkdir(parents=True)
        (src / "x" / "AuthTrace.java").write_text(HELPER, encoding="utf-8")
        (src / "x" / "SignInFlow.java").write_text(TASK, encoding="utf-8")
        (src / "x" / "ChatLog.kt").write_text(KT_HELPER, encoding="utf-8")
        (src / "x" / "Sender.kt").write_text(KT_CALLER, encoding="utf-8")
        self.root = str(src)

    def tearDown(self):
        self.tmp.cleanup()

    def find(self, ev, **extra):
        r, err = callsites.find(dict({"root": self.root}, **extra), ev)
        self.assertIsNone(err)
        return r

    def wheres(self, r):
        return [t["where"] for t in r["targets"]]

    def test_helper_is_skipped_to_the_caller(self):
        r = self.find("LOGIN_START")
        self.assertEqual([e["method"] for e in r["emits"]], ["loginStart"])
        self.assertEqual(self.wheres(r), [os.path.join("x", "SignInFlow.java") + ":4"])
        self.assertIn("AuthTrace.loginStart()", r["targets"][0]["via"])

    def test_several_callers_are_all_candidates(self):
        self.assertEqual(self.wheres(self.find("PROFILE_FETCH")),
                         [os.path.join("x", "SignInFlow.java") + ":6",
                          os.path.join("x", "SignInFlow.java") + ":8"])

    def test_emit_inside_branch_finds_enclosing_method(self):
        # if/else 안에서 찍어도 메서드는 loginResult 다 (if 를 메서드로 착각하지 않는다)
        r = self.find("LOGIN_FAIL")
        self.assertEqual(r["emits"][0]["method"], "loginResult")
        self.assertEqual(self.wheres(r), [os.path.join("x", "SignInFlow.java") + ":10"])

    def test_comment_example_is_not_a_call(self):
        r = self.find("LOGIN_OK")
        self.assertEqual(len(r["emits"]), 1, "javadoc 속 사용 예시는 호출이 아니다")
        self.assertEqual(self.wheres(r), [os.path.join("x", "SignInFlow.java") + ":10"])

    def test_direct_emit_in_business_code_points_at_itself(self):
        r = self.find("DIRECT_EVT")
        # run() 을 부르는 곳이 없으니 찍는 줄이 곧 업무 코드
        self.assertEqual(self.wheres(r), [os.path.join("x", "SignInFlow.java") + ":11"])
        self.assertIn("업무 코드", r["targets"][0]["via"])

    def test_kotlin_helper(self):
        self.assertEqual(self.wheres(self.find("SEND_OK")), [os.path.join("x", "Sender.kt") + ":3"])

    def test_too_many_callers_falls_back_to_emit_line(self):
        many = "".join("        AuthTrace.loginStart(a, b);\n" for _ in range(callsites.MAX_CALLERS + 1))
        (pathlib.Path(self.root) / "x" / "Many.java").write_text(
            "class Many {\n    void m() {\n" + many + "    }\n}\n", encoding="utf-8")
        r = self.find("LOGIN_START")
        self.assertEqual(self.wheres(r), [os.path.join("x", "AuthTrace.java") + ":8"])
        self.assertIn("너무 많아", r["targets"][0]["via"])

    def test_unknown_event_has_no_targets(self):
        self.assertEqual(self.find("NOPE")["targets"], [])

    def test_bad_root_and_pattern_are_errors_not_crash(self):
        self.assertIn("찾지 못했다", callsites.find({"root": "/없는/경로"}, "X")[1])
        self.assertIn("정규식", callsites.find({"root": self.root, "pattern": "("}, "X")[1])

    # -- 서버: 누를 때마다 새로 읽고, 루트 밖은 거절 ---------------------------
    def hub(self, open_cmd=("ide", "--line", "{line}", "{abs}")):
        return Hub(Config.from_dict({"prefix": "APP", "eventSource": {
            "root": self.root, "open": list(open_cmd)}}))

    def test_hub_opens_chosen_candidate(self):
        calls = []
        r = self.hub().open_event("PROFILE_FETCH", 1, runner=lambda argv, **kw: calls.append(argv))
        self.assertTrue(r["ok"], r)
        self.assertEqual(calls[0][:3], ["ide", "--line", "8"])
        self.assertTrue(calls[0][3].endswith(os.path.join("x", "SignInFlow.java")))

    def test_hub_rereads_source_on_each_call(self):
        h = self.hub()
        before = h.event_where("LOGIN_START")["targets"][0]["where"]
        p = pathlib.Path(self.root) / "x" / "SignInFlow.java"
        p.write_text("// 한 줄 추가\n" + p.read_text(encoding="utf-8"), encoding="utf-8")
        after = h.event_where("LOGIN_START")["targets"][0]["where"]
        self.assertEqual((before.split(":")[1], after.split(":")[1]), ("4", "5"),
                         "소스를 고치면 재시작 없이 새 줄을 가리켜야 한다")

    def test_hub_bad_index_and_unset_config(self):
        self.assertFalse(self.hub().open_event("LOGIN_START", 5, runner=lambda *a, **k: None)["ok"])
        h = Hub(Config.from_dict({"prefix": "APP"}))
        self.assertIn("설정되지", h.event_where("X")["error"])
        self.assertFalse(Config.from_dict({"prefix": "APP"}).to_dict()["eventSource"])
        self.assertTrue(Config.from_dict({"prefix": "APP", "eventSource": {
            "root": self.root, "open": ["ide"]}}).to_dict()["eventSource"])

    def test_open_at_refuses_outside_root(self):
        calls = []
        r = open_at(self.root, "../../etc/hosts:1", ["ide", "{abs}"], lambda argv, **kw: calls.append(argv))
        self.assertFalse(r["ok"])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
