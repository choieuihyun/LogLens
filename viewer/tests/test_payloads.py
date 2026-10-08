"""원문(payload) — 조각 모으기, 빠진 조각 표시, 버퍼·통계·내보내기와의 관계."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from loglens import callsites, events, payloads  # noqa: E402
from loglens.config import Config  # noqa: E402
from loglens.parser import Parser  # noqa: E402
from loglens.payloads import PayloadStore  # noqa: E402
from loglens.server import Hub  # noqa: E402

P = Parser("APP")


def chunk(part, parts, text, nbytes=None, pl_id="k31", evt="RES_BODY", extra="flowId=a1", pid=1,
          tail=""):
    """라이브러리가 찍는 모양 그대로의 조각 한 줄. text 는 이미 이스케이프된 것."""
    if nbytes is None:
        nbytes = len(payloads.unescape(text).encode("utf-8")) if parts == 1 else 0
    head = (f"08-12 10:00:0{part % 10}.000  {pid}  1 D APP_NET: evt={evt}"
            f"{' ' + extra if extra else ''} plId={pl_id} plPart={part} plParts={parts} plBytes={nbytes}{tail}")
    return head + (f" | {text}" if text else "")


def chunks(text, n, **kw):
    """본문을 n 조각으로 나눈 줄들 (ASCII 본문 전용 — 테스트가 읽기 쉬우라고)."""
    size = -(-len(text) // n)
    parts = [text[i:i + size] for i in range(0, len(text), size)]
    return [chunk(i + 1, len(parts), p, nbytes=len(text.encode("utf-8")), **kw) for i, p in enumerate(parts)]


class TestUnescape(unittest.TestCase):
    def test_reverses_every_escape(self):
        self.assertEqual(payloads.unescape(r"a\\nb\nc\td\re\sf"), "a\\nb\nc\td\re f")
        self.assertEqual(payloads.unescape(r" ] "), " ] ")

    def test_unknown_escape_is_kept(self):
        self.assertEqual(payloads.unescape("\\q \\u12 끝\\"), "\\q \\u12 끝\\")

    def test_json_backslash_n_is_not_a_newline(self):
        # 라이브러리는 JSON 안의 \n(두 글자)을 \\n 으로, 진짜 줄바꿈을 \n 으로 보낸다
        got = payloads.unescape(r'{"memo":"첫줄\\n둘째줄"}\n끝')
        self.assertEqual(got, '{"memo":"첫줄\\n둘째줄"}\n끝')


class TestChunkOf(unittest.TestCase):
    def test_plain_record_is_not_a_payload(self):
        self.assertIsNone(payloads.chunk_of(P.parse("08-12 10:00:00.000  1  1 I APP_NET: evt=X a=1 | m")))

    def test_broken_numbers_fall_back_to_a_plain_record(self):
        for bad in ("plId=a plPart=x plParts=2 plBytes=1", "plId=a plPart=3 plParts=2 plBytes=1",
                    "plId=a plPart=0 plParts=2 plBytes=1", "plId=a plParts=2 plBytes=1",
                    "plId=a plPart=1 plParts=999999 plBytes=1"):
            rec = P.parse(f"08-12 10:00:00.000  1  1 D APP_NET: evt=X {bad} | body")
            self.assertIsNone(payloads.chunk_of(rec), bad)

    def test_reserved_name_is_pl_plus_capital(self):
        self.assertTrue(payloads.is_reserved("plId"))
        self.assertFalse(payloads.is_reserved("place"))
        self.assertFalse(payloads.is_reserved("pl"))


class TestStore(unittest.TestCase):
    def test_single_chunk(self):
        s = PayloadStore()
        r = s.add(P.parse(chunk(1, 1, '{"a":1}')))
        self.assertTrue(r["first"])
        self.assertEqual(r["info"]["format"], "json")
        d = s.detail(r["key"])
        self.assertEqual((d["text"], d["complete"], d["sizeMismatch"]), ('{"a":1}', True, False))
        self.assertEqual(d["fields"], {"flowId": "a1"}, "예약 필드는 호출부 필드가 아니다")

    def test_chunks_are_joined_in_order_even_if_they_arrive_shuffled(self):
        s = PayloadStore()
        lines = chunks("<a>" + "x" * 50 + "</a>", 4)
        firsts = [s.add(P.parse(lines[i]))["first"] for i in (2, 0, 3, 1)]
        self.assertEqual(firsts, [True, False, False, False])
        d = s.detail("1-k31")
        self.assertEqual(d["text"], "<a>" + "x" * 50 + "</a>")
        self.assertEqual((d["format"], d["complete"], d["received"]), ("xml", True, 4))

    def test_missing_chunks_are_reported_not_glued(self):
        s = PayloadStore()
        lines = chunks("AAAABBBBCCCCDDDDEEEE", 5)
        for i in (0, 3, 4):
            s.add(P.parse(lines[i]))
        d = s.detail("1-k31")
        self.assertFalse(d["complete"])
        self.assertEqual(d["missing"], [2, 3])
        self.assertEqual(d["segments"], [{"text": "AAAA"}, {"missing": [2, 3]}, {"text": "DDDDEEEE"}])
        self.assertFalse(d["sizeMismatch"], "덜 받은 것은 크기 불일치로 치지 않는다 (빠졌다고 이미 말했다)")

    def test_size_mismatch_when_all_parts_arrived_but_text_differs(self):
        s = PayloadStore()
        s.add(P.parse(chunk(1, 1, "abc", nbytes=99)))
        self.assertTrue(s.detail("1-k31")["sizeMismatch"])

    def test_same_id_from_another_process_is_another_payload(self):
        s = PayloadStore()
        s.add(P.parse(chunk(1, 1, "one", pid=10)))
        s.add(P.parse(chunk(1, 1, "two", pid=20)))
        self.assertEqual((s.detail("10-k31")["text"], s.detail("20-k31")["text"]), ("one", "two"))

    def test_reused_id_with_different_shape_starts_over(self):
        s = PayloadStore()
        s.add(P.parse(chunks("old-old-old", 2)[0]))
        r = s.add(P.parse(chunk(1, 1, "new")))
        self.assertTrue(r["first"], "조각 수가 다르면 같은 id 를 다시 쓴 다른 원문이다")
        self.assertEqual(s.detail("1-k31")["text"], "new")

    def test_duplicate_chunk_is_not_counted_twice(self):
        s = PayloadStore()
        ln = chunk(1, 1, "same")
        s.add(P.parse(ln))
        s.add(P.parse(ln))
        self.assertEqual(s.detail("1-k31")["text"], "same")
        self.assertEqual(s._bytes, len("same") + len(ln))

    def test_old_payloads_are_evicted(self):
        s = PayloadStore(max_items=3)
        for i in range(5):
            s.add(P.parse(chunk(1, 1, f"body{i}", pl_id=f"id{i}")))
        self.assertEqual(len(s), 3)
        self.assertIsNone(s.detail("1-id0"))
        self.assertEqual(s.detail("1-id4")["text"], "body4")

    def test_cut_and_err_are_carried(self):
        s = PayloadStore()
        s.add(P.parse(chunk(1, 1, "abc", nbytes=3, tail=" plCut=90000")))
        self.assertEqual(s.detail("1-k31")["cut"], 90000)
        s.add(P.parse(chunk(1, 1, "", nbytes=0, pl_id="e", tail=" plErr=mask")))
        self.assertEqual(s.detail("1-e")["err"], "mask")


CFG = {"prefix": "APP", "issueRules": [
    {"id": "anr", "label": "ANR", "severity": "fatal", "when": {"raw": r"\bANR in\b"},
     "group": {"regex": r"ANR in ([^\s(]+)", "fallback": "ANR"}}]}


class TestHub(unittest.TestCase):
    def hub(self):
        return Hub(Config.from_dict(CFG))

    def test_buffer_keeps_one_head_line_per_payload_without_the_body(self):
        h = self.hub()
        for ln in chunks('{"list":[' + "1," * 40 + "2]}", 4):
            h.ingest(ln)
        self.assertEqual(len(h.buffer), 1, "조각 수만큼 줄이 늘면 안 된다")
        head = h.buffer[0]
        self.assertIsNone(head.msg)
        self.assertNotIn("list", head.raw, "머리 줄에는 본문이 없다")
        self.assertEqual(head.fields, {"flowId": "a1"})
        self.assertEqual(head.payload["parts"], 4)
        self.assertEqual(head.payload["format"], "json")
        self.assertEqual(h.payload(head.payload["key"])["text"], '{"list":[' + "1," * 40 + "2]}")
        self.assertEqual(h.snapshot()["records"][0]["payload"]["key"], head.payload["key"])

    def test_body_text_does_not_trip_issue_rules(self):
        h = self.hub()
        h.ingest("08-12 10:00:00.000  1  1 E ActivityManager: ANR in com.app (com.app/.Main)")
        self.assertEqual(len(h.tray.snapshot()), 1, "대조: 이 규칙은 보통 줄에는 걸린다")
        h.ingest(chunk(1, 1, '{"log":"ANR in com.other"}'))
        self.assertEqual(len(h.tray.snapshot()), 1, "원문 본문에 든 글자는 이슈가 아니다")
        self.assertEqual(h.tray.snapshot()[0]["count"], 1)

    def test_event_is_seen_once_and_without_reserved_fields(self):
        h = self.hub()
        for ln in chunks("x" * 90, 3):
            h.ingest(ln)
        seen = h.seen.events["RES_BODY"]
        self.assertEqual(seen["count"], 1)
        self.assertEqual(list(seen["fields"]), ["flowId"])

    def test_payload_survives_after_its_head_left_the_buffer(self):
        h = Hub(Config.from_dict(dict(CFG, bufferSize=5)))
        h.ingest(chunk(1, 1, "keep me"))
        for i in range(10):
            h.ingest(f"08-12 10:00:01.000  1  1 I APP_NET: evt=NOISE n={i}")
        self.assertNotIn("RES_BODY", [r.event for r in h.buffer])
        self.assertEqual(h.payload("1-k31")["text"], "keep me")

    def test_clear_drops_payloads_too(self):
        h = self.hub()
        h.ingest(chunk(1, 1, "x"))
        h.clear()
        self.assertIsNone(h.payload("1-k31"))

    def test_flow_step_carries_the_payload_link(self):
        h = self.hub()
        h.ingest("08-12 10:00:00.000  1  1 I APP_NET: evt=REQ_START flowId=a1")
        for ln in chunks("y" * 60, 3):
            h.ingest(ln)
        from loglens import flows
        d = flows.flow_detail(list(h.buffer), h.cfg, "a1")
        self.assertEqual([s["event"] for s in d["steps"]], ["REQ_START", "RES_BODY"], "조각마다 단계가 되면 안 된다")
        self.assertEqual(d["steps"][1]["payload"]["key"], "1-k31")


class TestSessionExport(unittest.TestCase):
    def filled(self):
        h = Hub(Config.from_dict(CFG))
        h.ingest("08-12 10:00:00.000  1  1 I APP_NET: evt=BEFORE")
        for ln in chunks("secret-body-" * 8, 3):
            h.ingest(ln)
        h.ingest("08-12 10:00:09.000  1  1 I APP_NET: evt=AFTER")
        return h

    def test_bodies_are_left_out_by_default_and_marked(self):
        text = self.filled().export_session({})
        self.assertNotIn("secret-body", text)
        self.assertIn('"payloads": "excluded"', text)
        b = Hub(Config.from_dict(CFG))
        b.import_session("s", text)
        self.assertEqual([r.event for r in b.buffer], ["BEFORE", "RES_BODY", "AFTER"])
        d = b.payload(b.buffer[1].payload["key"])
        self.assertEqual((d["err"], d["text"], d["missing"]), ("excluded", "", []),
                         "뺀 원문이 '조각 유실' 로 보이면 안 된다")

    def test_bodies_can_be_included_on_request(self):
        text = self.filled().export_session({}, with_payloads=True)
        b = Hub(Config.from_dict(CFG))
        b.import_session("s", text)
        self.assertEqual([r.event for r in b.buffer], ["BEFORE", "RES_BODY", "AFTER"])
        d = b.payload(b.buffer[1].payload["key"])
        self.assertEqual((d["text"], d["complete"]), ("secret-body-" * 8, True))


class TestSynth(unittest.TestCase):
    """가짜 로그 생성기는 계약을 흉내내는 쪽이다. 흉내가 어긋나면 화면 데모가 거짓이 된다."""

    def src(self):
        from loglens.sources.synthetic import SyntheticSource
        return SyntheticSource(prefix="APP")

    def roundtrip(self, text, **kw):
        s = PayloadStore()
        lines = self.src()._payload("NET", "RES_BODY", text, "flowId=f1", **kw)
        key = None
        for ln in lines:
            self.assertEqual(ln, ln.rstrip(), "줄 끝 공백")
            self.assertLessEqual(len(ln.encode("utf-8")), 3800 + 128)
            self.assertEqual(len(ln.splitlines()), 1)
            key = s.add(P.parse(ln))["key"]
        return lines, s.detail(key)

    def test_text_comes_back_exactly(self):
        for text in ('{"a":"줄\\n바꿈"}\n  들여쓴\t줄', "  앞뒤 공백  ", "말줄임...[cut]", "",
                     "가 나 다 👍🏻 " * 900, "a\u2028b\u0085c"):
            lines, d = self.roundtrip(text)
            self.assertEqual(d["text"], text)
            self.assertTrue(d["complete"])
            self.assertFalse(d["sizeMismatch"], text[:20])

    def test_escape_matches_what_unescape_expects(self):
        for text in ("\\", " ", "\u00a0x\u3000", "a|b | c", "\\n", "]"):
            self.assertEqual(payloads.unescape(payloads.escape(text)), text)

    def test_lost_chunk_shows_as_missing(self):
        lines, d = self.roundtrip("x" * 12000, lose=True)
        self.assertEqual(d["missing"], [2])
        self.assertFalse(d["complete"])

    def test_generator_output_is_well_formed(self):
        src = self.src()
        h = Hub(Config.from_dict(CFG))
        n = 0
        for _ in range(4000):                 # 조각이 빠지는 경우는 드물다. 넉넉히 돌린다 (씨앗이 고정이라 결과는 늘 같다)
            for item in src._next_batch():
                if isinstance(item, float):
                    continue
                h.ingest(item() if callable(item) else item)
                n += 1
        heads = [r for r in h.buffer if r.payload]
        self.assertGreater(len(heads), 10, "원문이 충분히 섞여 나와야 화면을 볼 수 있다")
        formats = {r.payload["format"] for r in heads}
        self.assertEqual(formats, {"json", "xml"})
        details = [h.payload(r.payload["key"]) for r in heads]
        self.assertTrue(any(d["parts"] > 1 and d["complete"] for d in details), "여러 조각짜리")
        self.assertTrue(any(d["missing"] for d in details), "조각이 빠진 것")
        self.assertFalse(any(d["sizeMismatch"] for d in details))


class TestCallSites(unittest.TestCase):
    def test_payload_call_is_found_like_any_other(self):
        import re
        m = re.search(callsites.DEFAULT_PATTERN, 'LogLens.payload(AppDomain.MEMBER, "ADDR_ADD_RES_BODY", json);')
        self.assertEqual(m.group(1), "ADDR_ADD_RES_BODY")

    def test_third_argument_is_the_body_not_a_field(self):
        java = ['AppDomain.MEMBER', '"RES_BODY"', 'json', '"flowId"', 'flowId', '"type"', 't']
        self.assertEqual(events.parse_call(java, payload=True), ("MEMBER", "RES_BODY", ["flowId", "type"]))
        kotlin = ['AppDomain.MEMBER', '"RES_BODY"', 'json', '"flowId" to flowId']
        self.assertEqual(events.parse_call(kotlin, payload=True), ("MEMBER", "RES_BODY", ["flowId"]))
        self.assertEqual(events.parse_call(['AppDomain.MEMBER', '"RES_BODY"', '"{}"'], payload=True),
                         ("MEMBER", "RES_BODY", []), "문자열 리터럴 본문을 필드 키로 읽으면 안 된다")


if __name__ == "__main__":
    unittest.main()
