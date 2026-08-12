"""파서 계약 테스트. 픽스처(docs/RECORD_FORMAT.md 의 예시들)를 진실로 삼는다."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens.parser import Parser, STRUCTURED, UNSTRUCTURED, RAW  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


class TestBody(unittest.TestCase):
    def setUp(self):
        self.p = Parser("APP")

    def one(self, line):
        return self.p.parse(line)

    def test_full_record(self):
        r = self.one("08-12 11:23:45.678  4321  4390 I APP_AUTH: evt=LOGIN_OK uid=123 | 로그인 성공")
        self.assertEqual(r.kind, STRUCTURED)
        self.assertEqual(r.level, "I")
        self.assertEqual(r.domain, "AUTH")
        self.assertEqual(r.event, "LOGIN_OK")
        self.assertEqual(r.fields, {"uid": "123"})
        self.assertEqual(r.msg, "로그인 성공")
        self.assertEqual(r.pid, 4321)
        self.assertEqual(r.tid, 4390)

    def test_event_only(self):
        r = self.one("08-12 11:23:45.701  1  1 D APP_CHAT: evt=ROOM_ENTER")
        self.assertEqual(r.kind, STRUCTURED)
        self.assertEqual(r.event, "ROOM_ENTER")
        self.assertEqual(r.fields, {})
        self.assertIsNone(r.msg)

    def test_event_and_message_no_fields(self):
        r = self.one("08-12 11:23:45.712  1  1 I APP_CHAT: evt=MSG_SEND | 메시지만")
        self.assertEqual(r.fields, {})
        self.assertEqual(r.msg, "메시지만")

    def test_fields_no_message(self):
        r = self.one("08-12 11:23:45.690  1  1 E APP_NET: evt=SOCKET_FAIL host=10.0.0.1 err=X:timeout")
        self.assertEqual(r.fields, {"host": "10.0.0.1", "err": "X:timeout"})
        self.assertIsNone(r.msg)

    def test_empty_value_sentinel(self):
        r = self.one("08-12 11:23:45.733  1  1 I APP_FILE_XFER: evt=UPLOAD_DONE size=10 name=-")
        self.assertEqual(r.domain, "FILE_XFER", "도메인에 언더스코어가 허용돼야 한다")
        self.assertEqual(r.fields["name"], "-")

    def test_domain_with_digits(self):
        r = self.one("08-12 11:23:45.744  1  1 I APP_API2: evt=CALL_OK code=200")
        self.assertEqual(r.domain, "API2")

    def test_pipe_in_message_survives(self):
        r = self.one("08-12 11:23:45.744  1  1 I APP_NET: evt=X | a | b | c")
        self.assertEqual(r.msg, "a | b | c")

    def test_masked_value_is_a_token(self):
        r = self.one("08-12 11:23:45.720  1  1 W APP_AUTH: evt=TOKEN_REFRESH token=*** uid=123")
        self.assertEqual(r.fields, {"token": "***", "uid": "123"})

    def test_truncated_line_degrades_not_throws(self):
        r = self.one("08-12 11:23:45.755  1  1 V APP_NET: evt=TRACE payload=aaaa...[cut]")
        self.assertEqual(r.kind, STRUCTURED)
        self.assertTrue(r.truncated)

    def test_truncated_mid_token_degrades_to_unstructured(self):
        # `evt=` 조차 안 끝난 경우
        r = self.one("08-12 11:23:45.755  1  1 V APP_NET: ev...[cut]")
        self.assertEqual(r.kind, UNSTRUCTURED)
        self.assertTrue(r.truncated)

    def test_trailing_space_does_not_demote(self):
        # 회귀: emitter 가 필드 뒤에 공백 한 칸을 남기면 레코드 전체가 강등됐었다.
        r = self.one("08-12 11:23:45.733  1  1 I APP_FILE_XFER: evt=UPLOAD_DONE size=10 name=a.png ")
        self.assertEqual(r.kind, STRUCTURED)
        self.assertEqual(r.fields, {"size": "10", "name": "a.png"})

    def test_trailing_space_after_message(self):
        r = self.one("08-12 11:23:45.733  1  1 I APP_NET: evt=X | 메시지  ")
        self.assertEqual(r.msg, "메시지")

    def test_legacy_line_passes_through(self):
        r = self.one("08-12 11:23:45.777  1  1 D LegacyTag: @@@@@ debugging")
        self.assertEqual(r.kind, UNSTRUCTURED)
        self.assertEqual(r.tag, "LegacyTag")
        self.assertEqual(r.msg, "@@@@@ debugging")

    def test_foreign_tag_with_evt_is_not_ours(self):
        r = self.one("08-12 11:23:45.788  1  1 I SomeOther: evt=NOT_OURS x=1")
        self.assertEqual(r.kind, UNSTRUCTURED)
        self.assertIsNone(r.domain)

    def test_divider_is_raw(self):
        r = self.one("--------- beginning of main")
        self.assertEqual(r.kind, RAW)

    def test_empty_line(self):
        self.assertEqual(self.one("").kind, RAW)

    def test_never_throws(self):
        junk = ["\x00\x01", "evt=", "I/", ":", "|||", "APP_: evt=X", "a" * 5000]
        for j in junk:
            self.p.parse(j)  # 예외 없이 끝나면 통과

    def test_prefix_is_regex_escaped(self):
        p = Parser("A.P")
        self.assertEqual(p.parse("I/A.P_AUTH: evt=X").domain, "AUTH")
        self.assertIsNone(p.parse("I/AxP_AUTH: evt=X").domain)

    def test_fatal_level_maps_to_error(self):
        r = self.one("08-12 11:23:45.810  1  1 F APP_NET: evt=BOOM")
        self.assertEqual(r.level, "E")


class TestPrefixVariants(unittest.TestCase):
    def setUp(self):
        self.p = Parser("APP")

    def test_threadtime_fixture(self):
        recs = self.p.parse_lines(load("threadtime.log"))
        structured = [r for r in recs if r.kind == STRUCTURED]
        self.assertEqual(len(structured), 11)
        self.assertEqual(
            {r.domain for r in structured},
            {"AUTH", "NET", "CHAT", "FILE_XFER", "API2"},
        )

    def test_brief_fixture(self):
        recs = self.p.parse_lines(load("brief.log"))
        self.assertEqual([r.kind for r in recs],
                         [STRUCTURED, STRUCTURED, STRUCTURED, UNSTRUCTURED])
        self.assertEqual(recs[0].pid, 4321)
        self.assertEqual(recs[1].domain, "NET")

    def test_filesink_fixture(self):
        recs = self.p.parse_lines(load("filesink.log"))
        self.assertTrue(all(r.kind == STRUCTURED for r in recs))
        self.assertEqual(recs[0].ts, "2026-08-12 11:23:45.678")

    def test_same_body_parses_identically_across_prefixes(self):
        body = "evt=LOGIN_OK uid=123 | 로그인 성공"
        variants = [
            f"08-12 11:23:45.678  1  2 I APP_AUTH: {body}",
            f"I/APP_AUTH( 1): {body}",
            f"2026-08-12 11:23:45.678 I/APP_AUTH: {body}",
            f"08-12 11:23:45.678 I/APP_AUTH( 1): {body}",
        ]
        parsed = [self.p.parse(v) for v in variants]
        for r in parsed:
            self.assertEqual((r.domain, r.event, r.fields, r.msg),
                             ("AUTH", "LOGIN_OK", {"uid": "123"}, "로그인 성공"),
                             msg=r.raw)

    def test_stacktrace_lines_kept_as_unstructured(self):
        r = self.p.parse(
            "08-12 11:23:45.810  1  1 E AndroidRuntime: \tat io.loglens.MainActivity.onCreate(MainActivity.java:42)"
        )
        self.assertEqual(r.kind, UNSTRUCTURED)
        self.assertEqual(r.tag, "AndroidRuntime")
        self.assertEqual(r.level, "E")


if __name__ == "__main__":
    unittest.main(verbosity=2)
