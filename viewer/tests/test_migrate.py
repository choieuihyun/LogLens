"""예전 로그 이관 도우미 테스트. 가짜 앱 소스를 임시 디렉토리에 만든다 (중립 이름만)."""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens import migrate  # noqa: E402
from loglens.config import Config  # noqa: E402
from loglens.server import Hub  # noqa: E402

CFG = Config.from_dict({"prefix": "APP", "tabs": [
    {"id": "chat", "label": "채팅", "domains": ["CHAT"], "legacyTagPattern": "(?i)chat|room"},
    {"id": "net", "label": "네트워크", "domains": ["NET"], "legacyTagPattern": "(?i)socket|http"}]})

JAVA = """class RoomScreen {
    private static final String TAG = "RoomScreen";
    void a() {
        // Log.d(TAG, "old " + x);
        Log.d(TAG, "==========================");
        Log.e(TAG, "@@@ matcher test : " + m.group());
        Log.e(TAG, "send error", e);
        Log.d(TAG, "requestJoinRoom failed!!!!");
        Log.e(TAG, "onMessage: event.what = " + event.what);
        Log.i(TAG, "enter room " + room.getRoomKey() + " members=" + list.size());
        Log.d(TAG, "received body=" + msgBody + " json=" + record.jsonData);
        Log.d("SocketWorker", "reconnect " + session.getId());
        Log.w(TAG, "load failed: " + e.getMessage());
    }
}
"""

KOTLIN = """class ChatSync {
    companion object { private val TAG = ChatSync::class.java.simpleName }
    fun b() {
        Log.d(TAG, "sync done room=${room.chatRoomKey} count=$count")
        Log.i(TAG,
              "upload completed " + fileName)
    }
}
"""


class TestParts(unittest.TestCase):
    def test_field_names(self):
        f = migrate.field_name
        self.assertEqual(f("sendRecord.getChatRoomKey()"), "chatRoomKey")
        self.assertEqual(f("tailXml.toString()"), "tailXml")
        self.assertEqual(f("session.getId()"), "sessionId")
        self.assertEqual(f("unread.size"), "unreadSize")

    def test_event_names(self):
        n = migrate.event_name
        self.assertEqual(n("xxx -> handleEnterBackground failed!!!!", True, False), "ENTER_BACKGROUND_FAIL")
        self.assertEqual(n("upload completed", False, True), "UPLOAD_OK")
        self.assertEqual(n("=====", False, False), "TODO_EVENT")

    def test_message_parts_java_and_kotlin(self):
        self.assertEqual(migrate.parse_message('"a = " + x.y + ", b"'), ("a = , b", ["x.y"]))
        self.assertEqual(migrate.parse_message('"room=${r.key} n=$n"'), ("room= n=", ["r.key", "n"]))

    def test_word_based_sensitivity(self):
        self.assertTrue(migrate.is_sensitive("chatContent"))
        self.assertFalse(migrate.is_sensitive("bodySize"), "크기는 값 자체가 아니다")
        self.assertFalse(migrate.is_sensitive("className"), "글자 일부(ssn)로 판단하지 않는다")
        self.assertTrue(migrate.is_dump("jsonData"))
        self.assertFalse(migrate.is_dump("responseCode"))


class TestScan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        (root / "RoomScreen.java").write_text(JAVA, encoding="utf-8")
        (root / "ChatSync.kt").write_text(KOTLIN, encoding="utf-8")
        self.root = str(root)
        files, err = migrate.scan({"root": self.root}, {"calls": ["Log"]}, CFG, {"ENTER_ROOM_MEMBERS": "NET"})
        self.assertIsNone(err)
        self.java = files["RoomScreen.java"]
        self.kt = files["ChatSync.kt"]

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, text):
        return next(x for x in self.java if text in x["code"])

    def test_kinds(self):
        self.assertEqual(self.at("old ")["kind"], "commented")
        self.assertEqual(self.at("=====")["action"], "delete")
        self.assertEqual(self.at("matcher test")["kind"], "noise")
        self.assertEqual(self.at("send error")["kind"], "exception")
        self.assertEqual(self.at("requestJoinRoom")["kind"], "failure")

    def test_exception_suggestion_passes_throwable(self):
        x = self.at("send error")
        self.assertIn("LogLens.e(AppDomain.CHAT, \"SEND_FAIL\", e", x["suggestion"])
        # e.getMessage() 를 이어 붙인 것도 예외를 넘기자고 한다
        y = self.at("load failed")
        self.assertEqual(y["kind"], "exception")
        self.assertIn('"LOAD_FAIL", e', y["suggestion"])

    def test_failure_gets_reason_placeholder(self):
        self.assertIn('"JOIN_ROOM_FAIL", "reason", "TODO"', self.at("requestJoinRoom")["suggestion"])

    def test_error_level_misuse_is_lowered(self):
        x = self.at("event.what")
        self.assertEqual(x["suggestLevel"], "D")
        self.assertIn("확신 낮음", x["why"])

    def test_fields_and_name_collision(self):
        x = self.at("enter room")
        self.assertIn('"roomKey", room.getRoomKey(), "listSize", list.size()', x["suggestion"])
        self.assertIn("NET 도메인에 이미 있다", x["why"])

    def test_sensitive_and_dump_values_are_not_fields(self):
        x = self.at("received body")
        self.assertEqual(x["sensitive"], ["msgBody"])
        self.assertEqual(x["dumps"], ["jsonData"])
        self.assertNotIn("msgBody", x["suggestion"])
        self.assertNotIn("jsonData", x["suggestion"])

    def test_domain_from_tag_not_path(self):
        self.assertEqual(self.at("send error")["domain"], "CHAT")          # TAG = "RoomScreen"
        self.assertEqual(self.at("reconnect")["domain"], "NET")            # 리터럴 태그 SocketWorker

    def test_kotlin_template_multiline_and_simple_name_tag(self):
        a, b = self.kt
        self.assertEqual(a["domain"], "CHAT")                                # ChatSync::class.java.simpleName
        self.assertIn('"chatRoomKey" to room.chatRoomKey, "count" to count', a["suggestion"])
        self.assertTrue(a["suggestion"].endswith(")"), "코틀린은 세미콜론 없이")
        self.assertIn('"UPLOAD_OK", "fileName" to fileName', b["suggestion"])

    def test_summary_by_domain(self):
        s = migrate.summarize({"RoomScreen.java": self.java, "ChatSync.kt": self.kt}, {"CHAT": 3})
        chat = next(d for d in s["domains"] if d["domain"] == "CHAT")
        self.assertEqual(chat["commented"], 1)
        self.assertEqual(chat["loglens"], 3)
        self.assertEqual(chat["legacy"] + chat["commented"],
                         sum(1 for x in self.java + self.kt if x["domain"] == "CHAT"))
        self.assertIsNotNone(chat["percent"])

    def test_hub_file_view_and_root_guard(self):
        h = Hub(Config.from_dict({"prefix": "APP", "tabs": CFG.to_dict()["tabs"],
                                  "eventSource": {"root": self.root, "open": ["true"]}}))
        self.assertEqual(len(h.migration_file("RoomScreen.java")["items"]), len(self.java))
        self.assertIn("아니다", h.migration_file("../../etc/hosts")["error"])
        self.assertGreater(h.migration()["totals"]["legacy"], 0)


if __name__ == "__main__":
    unittest.main()
