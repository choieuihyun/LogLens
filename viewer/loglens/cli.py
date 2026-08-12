"""loglens CLI.

    loglens --source synth                    # 기기 없이 데모
    loglens --source adb --package com.x.y    # 실제 기기
    loglens --source file --file dump.log     # 저장된 로그 재생
    loglens --config app.json                 # 프로젝트별 탭/이슈 규칙
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from . import __version__
from .config import Config
from .parser import Parser
from .server import serve
from .sources import build


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="loglens",
        description="구조화 로그 실시간 뷰어 / 분석기",
    )
    p.add_argument("--config", help="프로젝트 config.json (탭/이슈규칙/프리픽스)")
    p.add_argument("--source", default="synth", choices=["adb", "file", "synth"],
                   help="로그 소스 (기본: synth — 기기 없이 데모)")
    p.add_argument("--file", help="--source file 일 때 읽을 로그 파일")
    p.add_argument("--follow", action="store_true", help="파일 소스를 tail -f 로")
    p.add_argument("--replay-delay", type=float, default=0.0,
                   help="파일 재생 시 줄당 지연(초)")
    p.add_argument("--serial", help="adb 기기 시리얼 (-s)")
    p.add_argument("--package", help="대상 앱 패키지 (pid 자동추적)")
    p.add_argument("--adb", default="adb", help="adb 실행 경로")
    p.add_argument("--clear", action="store_true", help="시작 시 logcat 버퍼 비우기")
    p.add_argument("--rate", type=float, default=12.0, help="synth 초당 줄 수")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8420)
    p.add_argument("--no-browser", action="store_true", help="브라우저 자동 실행 안 함")
    p.add_argument("--stdout", action="store_true",
                   help="서버 없이 파싱 결과를 JSONL 로 표준출력 (파이프용)")
    p.add_argument("--version", action="version", version=f"loglens {__version__}")
    return p.parse_args(argv)


def _make_source(a, cfg: Config):
    if a.source == "adb":
        return build("adb", serial=a.serial, package=a.package or cfg.package,
                     adb_path=a.adb, clear_first=a.clear)
    if a.source == "file":
        if not a.file:
            sys.exit("--source file 에는 --file 이 필요합니다")
        return build("file", path=a.file, follow=a.follow, delay=a.replay_delay)
    return build("synth", prefix=cfg.prefix, rate=a.rate)


def main(argv=None) -> int:
    a = _parse_args(argv)
    cfg = Config.load(a.config)
    source = _make_source(a, cfg)

    if a.stdout:
        import json
        parser = Parser(cfg.prefix)
        try:
            for line in source.lines():
                print(json.dumps(parser.parse(line).to_dict(), ensure_ascii=False),
                      flush=True)
        except KeyboardInterrupt:
            pass
        return 0

    httpd, hub, _reader = serve(source, cfg, a.host, a.port)
    url = f"http://{a.host}:{a.port}/"
    print(f"LogLens {__version__}  →  {url}")
    print(f"  소스   : {source.describe()}")
    print(f"  프리픽스: {cfg.prefix}_*   탭: {len(cfg.tabs)}개   "
          f"이슈규칙: {len(cfg.issue_rules)}개")
    print("  Ctrl-C 로 종료")

    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료 중…")
    finally:
        source.stop()
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
