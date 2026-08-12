# 문서

| 파일 | 무엇 | 언제 읽나 |
|---|---|---|
| [**../기획서.md**](../기획서.md) | 원래 설계 초안 — 문제 정의, 설계 결정과 근거, 실전 교훈 | 이 프로젝트가 **왜** 존재하는지 |
| [**ARCHITECTURE.md**](ARCHITECTURE.md) | 동작 원리 — 데이터 흐름, emitter 파이프라인, 뷰어가 기기에 붙는 방식, 기술 스택, 0→1 절차 | **어떻게** 도는지 (여기부터 읽으면 된다) |
| [**RECORD_FORMAT.md**](RECORD_FORMAT.md) | 계약 전문 — 문법, 불변식, 정규식, 정규화된 레코드 모양 | 파서나 emitter를 손댈 때 |
| [**DECISIONS.md**](DECISIONS.md) | 구현 결정 기록 — 초안과 달라진 것과 그 이유, 밟은 버그들 | 왜 이렇게 짰는지 궁금할 때 |

## architecture.html

[`ARCHITECTURE.md`](ARCHITECTURE.md) 를 다이어그램까지 렌더한 단일 HTML 페이지.
의존성 없이 그대로 열린다.

```bash
open docs/architecture.html
```

ASCII 다이어그램 대신 SVG로 그린 그림 넷이 들어 있다 —
로그 한 줄 해부도 / 전체 흐름과 세 경계 / 브라우저 샌드박스 vs 로컬 브리지 / 파서 강등 사다리.

> 이 파일은 Claude Artifact 로 발행된 페이지의 원본이기도 하다.
> 내용을 고치면 **이 경로에서** 다시 발행해야 같은 URL 이 유지된다.
> `<!doctype>` / `<html>` / `<body>` 태그가 없는 건 그래서다 — 발행 시 감싸진다.
