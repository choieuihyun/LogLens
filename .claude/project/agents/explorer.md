# explorer 보충 (2026-09-30, /setup)

## 더 볼 곳
- `docs/DECISIONS.md`: 실제로 밟은 버그와 그 이유(D1~D23). 비슷한 영역을 고칠 때 먼저 본다
- 같은 이름의 Kotlin 파일이 여러 곳에 보이면 `src/main/...` 쪽만 진짜다

## 피할 곳
- `lib/**/bin/`, `sample-app/**/bin/`, `tools/**/bin/`: IDE 가 `src/` 를 복사해 둔 낡은 사본. 제안 목록에 넣지 않는다
- `build/`, `**/__pycache__/`: 산출물

## 우선순위와 당부
- 이 프로젝트에서 "빌드 설정 파일" 은 `lib/**/*.gradle.kts`, `lib/gradle.properties`, `lib/local.properties`, `viewer/pyproject.toml`, `Makefile` 이다
