# LogLens — 두 컴포넌트, 하나의 로그 형식.
#
#   make test        전체 검증 (뷰어 + 라이브러리 + 양쪽 대조)
#   make viewer      뷰어를 가짜 로그로 실행 (기기 불필요)
#   make demo        진짜 라이브러리 → 파일 → 뷰어  (전 구간)
#   make aar         배포용 .aar 생성
#
# 라이브러리는 Kotlin + gradle, 뷰어는 Python 표준 라이브러리만 씁니다.
# gradle 은 lib/ 을 루트로 합니다.

PYTHON  ?= python3
GRADLE  := ./lib/gradlew -p lib
DEMOSEED := build/demo/app.log
DEMOLOG  := build/demo/app-$(shell date +%Y-%m-%d).log
AAR      := lib/android/build/outputs/aar/loglens-release.aar

.PHONY: all help test test-viewer test-lib roundtrip aar viewer adb demo emit clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

all: test

test: test-viewer test-lib roundtrip ## 전체 검증
	@echo ""
	@echo "모두 통과."

test-viewer: ## 뷰어 테스트 (Python, 외부 라이브러리 없음)
	@echo "── 뷰어 ──"
	@cd viewer && $(PYTHON) -m unittest discover -s tests -q

test-lib: ## 라이브러리 테스트 (Kotlin, kotlin.test)
	@echo "── 라이브러리 ──"
	@$(GRADLE) :core:test --console=plain -q
	@echo "  통과 (자세한 결과: lib/core/build/reports/tests/test/index.html)"

roundtrip: ## 형식 대조: Kotlin 라이브러리가 만든 줄 → Python 파서
	@echo "── 양쪽 대조 ──"
	@$(GRADLE) :roundtrip:run -q --console=plain 2>/dev/null | $(PYTHON) tools/roundtrip/verify.py

aar: ## 배포용 .aar 생성
	@$(GRADLE) :android:assembleRelease -q --console=plain
	@echo "→ $(AAR)"
	@ls -la $(AAR) | awk '{print "  "$$5" bytes"}'

viewer: ## 뷰어를 가짜 로그로 실행 (기기·adb 불필요)
	@cd viewer && $(PYTHON) -m loglens --source synth --config examples/sample-app.json

adb: ## 뷰어를 실제 기기에 연결  (make adb PKG=com.your.app)
	@cd viewer && $(PYTHON) -m loglens --source adb --config examples/sample-app.json \
		$(if $(PKG),--package $(PKG),)

demo: ## 전 구간: 진짜 라이브러리가 파일에 쓰고 뷰어가 그걸 따라 읽습니다
	@mkdir -p build/demo
	@echo "라이브러리 → $(DEMOLOG)"
	@$(GRADLE) :demo:run -q --console=plain \
		--args="--out ../../$(DEMOSEED) --loops 200 --pause-ms 120" > /dev/null 2>&1 &
	@sleep 6
	@test -f $(DEMOLOG) || { echo "라이브러리가 $(DEMOLOG) 를 만들지 않았습니다"; exit 1; }
	@cd viewer && $(PYTHON) -m loglens --source file --file ../$(DEMOLOG) --follow \
		--config examples/sample-app.json

emit: ## 로그가 어떤 모양으로 찍히는지 터미널에서 확인
	@$(GRADLE) :demo:run -q --console=plain --args="--loops 12 --pause-ms 0" 2>/dev/null

clean:
	@$(GRADLE) clean -q --console=plain 2>/dev/null || true
	@rm -rf build
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
