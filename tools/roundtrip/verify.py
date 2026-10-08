#!/usr/bin/env python3
"""왕복 검증 — Java emitter 가 만든 줄을 Python parser 로 되읽어 대조한다.

    java -cp build/classes io.loglens.tools.RoundTrip | python3 tools/roundtrip/verify.py

이게 이 프로젝트에서 유일하게 "양쪽이 정말 같은 계약을 쓰는가"를 증명하는 검사다.
픽스처는 내가 양쪽에 같은 오해를 심을 수 있지만, 왕복은 그럴 수 없다.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "viewer"))

from loglens.parser import Parser, STRUCTURED, TRUNCATION_MARK  # noqa: E402
from loglens.payloads import PayloadStore, is_reserved  # noqa: E402

MAX_BYTES = 3800  # Truncator.DEFAULT_MAX_BYTES 와 같아야 한다


def canon_of(rec) -> str:
    fields = ",".join(f"{k}={v}" for k, v in rec.fields.items())
    return f"{rec.domain}|{rec.event}|{fields}|{rec.msg or ''}"


def line_errors(line: str) -> list:
    """어떤 모드에서든 한 줄마다 지켜져야 하는 것들."""
    errs = []
    if "\n" in line or "\r" in line:
        errs.append("한 줄 불변식 위반 (개행 포함)")
    if len(line.splitlines()) != 1:
        errs.append("줄을 가르는 글자가 그대로 들어 있다 (세션 파일을 다시 열면 줄이 쪼개진다)")
    nbytes = len(line.encode("utf-8"))
    # 접두사(타임스탬프+태그)는 예산 밖이므로 여유를 둔 상한으로 본다
    if nbytes > MAX_BYTES + 128:
        errs.append(f"바이트 한도 초과: {nbytes}")
    try:
        line.encode("utf-8").decode("utf-8")
    except UnicodeError:
        errs.append("UTF-8 왕복 실패 (코드포인트가 쪼개짐)")
    if "�" in line:
        errs.append("치환문자(U+FFFD) 발견 — 바이트 경계에서 잘렸다")
    return errs


def check_payload(parser: Parser, expected: str, lines: list) -> list:
    """조각 줄들을 뷰어가 실제로 쓰는 경로(PayloadStore)로 모아 입력과 대조한다."""
    dom, event, want_fields, hexed, want_cut = expected.split("|")
    want_text = bytes.fromhex(hexed).decode("utf-8")
    errs, store, keys = [], PayloadStore(), set()
    for line in lines:
        errs += line_errors(line)
        rec = parser.parse(line)
        if rec.kind != STRUCTURED:
            errs.append(f"조각이 구조화로 파싱되지 않음 (kind={rec.kind})")
            continue
        if rec.truncated or line.endswith(TRUNCATION_MARK):
            errs.append("원문 줄에 잘림 표식이 붙었다")
        if line != line.rstrip():
            errs.append("줄 끝에 공백이 남았다 — 파서가 떼어 내서 본문이 달라진다")
        fields = ",".join(f"{k}={v}" for k, v in rec.fields.items() if not is_reserved(k))
        if (rec.domain, rec.event, fields) != (dom, event, want_fields):
            errs.append(f"머리 불일치: {rec.domain}|{rec.event}|{fields}  (기대 {dom}|{event}|{want_fields})")
        added = store.add(rec)
        if added is None:
            errs.append("뷰어가 원문 조각으로 알아보지 못했다")
        else:
            keys.add(added["key"])
    if len(keys) != 1:
        return errs + [f"묶음이 {len(keys)}개로 갈렸다"]
    d = store.detail(keys.pop())
    if d["missing"]:
        errs.append(f"빠진 조각: {d['missing']}")
    if d["parts"] != len(lines):
        errs.append(f"조각 수 불일치: plParts={d['parts']}, 실제 줄 {len(lines)}")
    if d["sizeMismatch"]:
        errs.append(f"크기 불일치: plBytes={d['bytes']}, 되살린 본문 {d['gotBytes']}")
    if d["text"] != want_text:
        at = next((i for i, (a, b) in enumerate(zip(d["text"], want_text)) if a != b),
                  min(len(d["text"]), len(want_text)))
        errs.append(f"본문이 다르다 ({at}번째 글자부터)\n"
                    f"      기대: {want_text[max(0, at - 20):at + 20]!r}\n"
                    f"      실제: {d['text'][max(0, at - 20):at + 20]!r}")
    if str(d["cut"] or "") != want_cut:
        errs.append(f"plCut 불일치: {d['cut']} (기대 {want_cut or '없음'})")
    return errs


def main() -> int:
    parser = Parser("APP")
    cases = []

    for raw in sys.stdin:
        raw = raw.rstrip("\n")
        if raw.startswith("CASE\t"):
            _, name, mode = raw.split("\t", 2)
            cases.append([name, mode, None, []])
        elif raw.startswith("CANON\t") and cases:
            cases[-1][2] = raw.split("\t", 1)[1]
        elif raw.startswith("LINE\t") and cases:
            cases[-1][3].append(raw.split("\t", 1)[1])

    if not cases:
        print("입력이 비었습니다. RoundTrip 을 먼저 실행하세요.", file=sys.stderr)
        return 2

    failed = 0
    for name, mode, expected, lines in cases:
        if not lines or expected is None:
            failed += 1
            print(f"  FAIL  {name}\n      줄이 없다")
            continue
        if mode == "PAYLOAD":
            errs = check_payload(parser, expected, lines)
            if errs:
                failed += 1
                print(f"  FAIL  {name}")
                for e in errs[:6]:
                    print(f"      {e}")
            continue

        line = lines[0]
        rec = parser.parse(line)
        errs = line_errors(line)

        if mode == "EXACT":
            if rec.kind != STRUCTURED:
                errs.append(f"구조화로 파싱되지 않음 (kind={rec.kind})")
            else:
                actual = canon_of(rec)
                if actual != expected:
                    errs.append("필드 불일치\n      기대: " + expected + "\n      실제: " + actual)
        else:  # TRUNC
            if not line.endswith(TRUNCATION_MARK):
                errs.append("잘림 표식이 없다")
            if rec.kind == "raw":
                errs.append("잘린 줄이 RAW 로 떨어졌다 — 접두사는 살아 있어야 한다")
            if rec.domain is None:
                errs.append("잘려도 도메인은 읽혀야 한다")

        if errs:
            failed += 1
            print(f"  FAIL  {name}")
            for e in errs:
                print(f"      {e}")

    total = len(cases)
    print(f"\nroundtrip: {total - failed} passed, {failed} failed  "
          f"(EXACT {sum(1 for c in cases if c[1] == 'EXACT')}, "
          f"TRUNC {sum(1 for c in cases if c[1] == 'TRUNC')}, "
          f"PAYLOAD {sum(1 for c in cases if c[1] == 'PAYLOAD')})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
