# documenter 보충 (2026-09-30, /setup)

## 우선순위와 당부
- 형식 계약 파일(`parser.py`, `Formatter.kt`, `LineFormat.kt`, `Sanitizer.kt`, `Truncator.kt`, `Masker.kt`, `tools/roundtrip/`)이 바뀌면 규모와 상관없이 `docs/domains/format/DOMAIN.md` 를 갱신한다
- 바뀐 동작이 `docs/RECORD_FORMAT.md` 의 내용과 어긋나면 보고에 적는다. RECORD_FORMAT 은 사람이 고친다
- 기획서나 앞선 결정과 달라진 설계 결정이 보이면 `docs/DECISIONS.md` 에 새 항목(D 번호)을 추가하자고 **제안만** 한다. 직접 쓰지 않는다
- `기획서.md` 는 고치지 않는다. 초안이 무엇을 예측했는지가 그 문서의 값어치다 (DECISIONS D20)
