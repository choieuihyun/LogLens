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
    p.add_argument("--init", metavar="OUT.json",
                   help="실제 로그를 표본으로 읽어 config.json 초안을 만든다 "
                        "(태그 이름·빈도만 사용, 메시지 내용은 읽지 않음)")
    p.add_argument("--init-lines", type=int, default=5000, help="--init 표본 줄 수")
    p.add_argument("--init-seconds", type=float, default=20.0, help="--init 표본 시간(초)")
    p.add_argument("--version", action="version", version=f"loglens {__version__}")
    return p.parse_args(argv)


def _make_source(a, cfg: Config, dump: bool = False, tail=None):
    if a.source == "adb":
        return build("adb", serial=a.serial, package=a.package or cfg.package,
                     adb_path=a.adb, clear_first=a.clear, dump=dump, tail=tail)
    if a.source == "file":
        if not a.file:
            sys.exit("--source file 에는 --file 이 필요합니다")
        return build("file", path=a.file, follow=a.follow, delay=a.replay_delay)
    return build("synth", prefix=cfg.prefix, rate=a.rate)


def _run_init(a, cfg: Config) -> int:
    """실제 로그에서 config.json 초안을 만든다.

    이관 전 프로젝트에 붙이는 첫 단계다. 도메인이 뭔지 모르는 상태에서
    손으로 config 를 쓰라고 하면 아무도 안 쓴다.
    """
    import json
    from .scaffold import LogLandscape, build_config, report, sample

    # -d: 지금 링버퍼에 있는 것만 읽고 끝낸다. 기다릴 필요가 없다.
    # 최근 N줄을 본다. 오래된 쪽부터 읽으면 부팅 로그만 표본이 된다.
    source = _make_source(a, cfg, dump=(a.source == "adb"),
                          tail=a.init_lines if a.source == "adb" else None)
    pkg = a.package or cfg.package

    # adb 소스면 대상 앱 pid 를 먼저 푼다 — 시스템 태그를 걸러내는 가장 강한 신호다.
    app_pid = getattr(source, "_resolve_pid", lambda: None)() if pkg else None
    if pkg and app_pid is None:
        print(f"경고: {pkg} 가 실행 중이 아닙니다. 앱을 켜면 훨씬 정확해집니다.",
              file=sys.stderr)

    land = LogLandscape(prefix=cfg.prefix, app_pid=app_pid)
    sample(source, Parser(cfg.prefix), land,
           max_lines=a.init_lines, max_seconds=a.init_seconds)

    if not land.total:
        print("표본을 하나도 못 읽었습니다. 기기 연결과 소스를 확인하세요.", file=sys.stderr)
        return 1

    print(report(land), file=sys.stderr)
    out = build_config(land, package=pkg)
    with open(a.init, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"\n→ {a.init} 에 초안을 썼습니다. 탭 이름과 도메인은 손으로 다듬으세요.",
          file=sys.stderr)
    print(f"   실행:  python3 -m loglens --source {a.source} "
          f"{'--package ' + pkg + ' ' if pkg else ''}--config {a.init}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    a = _parse_args(argv)
    cfg = Config.load(a.config)

    if a.init:
        return _run_init(a, cfg)

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
