# LogLens — 두 컴포넌트, 하나의 계약.
#
#   make test        전부 검증 (뷰어 + 라이브러리 + 왕복)
#   make viewer      뷰어를 데모 모드로 (기기 불필요)
#   make demo        진짜 emitter → 파일 → 뷰어  (end-to-end)
#
# 안드로이드 빌드(.aar)는 gradle + Android SDK 가 필요하다. 이 Makefile 범위 밖.

JAVAC   ?= javac
JAVA    ?= java
PYTHON  ?= python3
CLASSES := build/classes
# FileSink 가 날짜를 스스로 붙인다: --out 에는 접두사만 주고,
# 뷰어에는 날짜가 붙은 실제 파일명을 준다. (이 둘을 같게 뒀다가 app-날짜-날짜.log 가 생겼다)
DEMOSEED := build/demo/app.log
DEMOLOG  := build/demo/app-$(shell date +%Y-%m-%d).log

CORE_SRC := $(shell find lib/core/src -name '*.java' 2>/dev/null)
DEMO_SRC := $(shell find lib/sample-domains/src sample-app/jvm/src tools/roundtrip/src -name '*.java' 2>/dev/null)

.PHONY: all test test-viewer test-lib roundtrip viewer demo build clean help

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

all: test

build: ## 자바 소스 컴파일 (core + 샘플 + 왕복도구)
	@mkdir -p $(CLASSES)
	@$(JAVAC) -encoding UTF-8 -d $(CLASSES) $(CORE_SRC) $(DEMO_SRC)

test: test-viewer test-lib roundtrip ## 전부 검증
	@echo ""
	@echo "모두 통과."

test-viewer: ## 뷰어 파서/집계 테스트 (Python, 의존성 없음)
	@echo "── 뷰어 ──"
	@cd viewer && $(PYTHON) -m unittest discover -s tests -q

test-lib: build ## 라이브러리 core 테스트 (JUnit 없이 순수 자바)
	@echo "── 라이브러리 ──"
	@$(JAVA) -cp $(CLASSES) io.loglens.core.CoreTests

roundtrip: build ## 계약 왕복 검증: Java emitter → Python parser
	@echo "── 왕복 ──"
	@$(JAVA) -cp $(CLASSES) io.loglens.tools.RoundTrip | $(PYTHON) tools/roundtrip/verify.py

viewer: ## 뷰어를 합성 로그로 띄운다 (기기·adb 불필요)
	@cd viewer && $(PYTHON) -m loglens --source synth --config examples/sample-app.json

adb: ## 뷰어를 실제 기기에 붙인다  (make adb PKG=com.your.app)
	@cd viewer && $(PYTHON) -m loglens --source adb --config examples/sample-app.json \
		$(if $(PKG),--package $(PKG),)

demo: build ## end-to-end: 진짜 emitter 가 파일에 쓰고 뷰어가 그걸 tail 한다
	@mkdir -p build/demo
	@echo "emitter → $(DEMOLOG)"
	@$(JAVA) -cp $(CLASSES) io.loglens.demo.Demo --out $(DEMOSEED) --loops 200 --pause-ms 120 > /dev/null &
	@sleep 1
	@test -f $(DEMOLOG) || { echo "emitter 가 $(DEMOLOG) 를 만들지 않았습니다"; exit 1; }
	@cd viewer && $(PYTHON) -m loglens --source file --file ../$(DEMOLOG) --follow \
		--config examples/sample-app.json

emit: build ## emitter 출력만 stdout 으로 (계약이 어떻게 생겼는지 눈으로 보기)
	@$(JAVA) -cp $(CLASSES) io.loglens.demo.Demo --loops 12 --pause-ms 0

clean:
	@rm -rf build
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
