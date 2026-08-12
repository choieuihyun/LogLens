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

MAX_BYTES = 3800  # Truncator.DEFAULT_MAX_BYTES 와 같아야 한다


def canon_of(rec) -> str:
    fields = ",".join(f"{k}={v}" for k, v in rec.fields.items())
    return f"{rec.domain}|{rec.event}|{fields}|{rec.msg or ''}"


def main() -> int:
    parser = Parser("APP")
    cases, name, mode, expected = [], None, None, None

    for raw in sys.stdin:
        raw = raw.rstrip("\n")
        if raw.startswith("CASE\t"):
            _, name, mode = raw.split("\t", 2)
        elif raw.startswith("CANON\t"):
            expected = raw.split("\t", 1)[1]
        elif raw.startswith("LINE\t"):
            cases.append((name, mode, expected, raw.split("\t", 1)[1]))

    if not cases:
        print("입력이 비었습니다. RoundTrip 을 먼저 실행하세요.", file=sys.stderr)
        return 2

    failed = 0
    for name, mode, expected, line in cases:
        rec = parser.parse(line)
        errs = []

        # 어떤 모드에서든 지켜져야 하는 것들
        if "\n" in line or "\r" in line:
            errs.append("한 줄 불변식 위반 (개행 포함)")
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
          f"TRUNC {sum(1 for c in cases if c[1] == 'TRUNC')})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
