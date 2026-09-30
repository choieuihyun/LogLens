#!/usr/bin/env python3
# 프로젝트 설정 로더 (결정적, LLM 미개입)
# 역할: project.json 과 어댑터 json 을 찾아 읽고 하나로 합쳐 돌려준다.
# 성격: 읽기만 한다. 값의 의미는 해석하지 않는다. 해석은 부르는 쪽 몫이다.
#
# 왜 로더를 따로 두나:
#   도메인 표와 빌드 명령이 코드 안에 박혀 있으면 다른 프로젝트에 복사할 때 코드를 고쳐야 한다.
#   설정을 밖으로 빼면 복사한 뒤 json 만 채우면 된다. 그 빈칸의 위치를 아는 곳이 여기 하나여야
#   스크립트마다 찾는 규칙이 갈리지 않는다.
#
# 찾는 순서 (먼저 걸리는 것을 쓴다):
#   1. 환경변수 HARNESS_PROJECT_JSON
#   2. 이 스크립트 위치의 상위 (.claude/scripts -> .claude/project.json)
#   3. 인자로 받은 project_dir 의 .claude/project.json
#
# 중요: 설정이 없을 때 어떻게 할지는 여기서 정하지 않는다.
#   load() 는 없으면 None 을 준다. 부르는 쪽이 안전한 쪽으로 판단해야 한다.
#   도메인 매핑은 설정이 없으면 ALL(전체 회귀)로 넓히는 것이 안전하고,
#   런타임 게이트는 설정이 없으면 통과가 아니라 오류(exit 3)로 끝나는 것이 안전하다.
#   이 둘을 한 곳에서 통일하면 게이트가 조용히 SKIP 이 된다.

import os
import json


def config_path(project_dir=None):
    # project.json 의 실제 경로를 돌려준다. 없으면 None.
    env = os.environ.get("HARNESS_PROJECT_JSON")
    if env and os.path.isfile(env):
        return env

    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(os.path.dirname(here), "project.json")
    if os.path.isfile(cand):
        return cand

    if project_dir:
        cand = os.path.join(project_dir, ".claude", "project.json")
        if os.path.isfile(cand):
            return cand

    return None


def load(project_dir=None):
    # project.json 을 읽어 dict 로 준다. 없거나 깨졌으면 None.
    # 깨진 json 을 빈 dict 로 바꿔 주지 않는다. 빈 설정과 잘못된 설정은 다른 상황이고
    # 부르는 쪽이 구분해서 처리해야 한다.
    path = config_path(project_dir)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (ValueError, OSError):
        return None
    if not isinstance(cfg, dict):
        return None
    cfg["_path"] = path
    return cfg


def _merge(base, over):
    # adapter_override 를 어댑터 파일 위에 덮는다. 객체는 키 단위로 내려가 합치고, 나머지는 통째로 바꾼다.
    # adapter_inline 은 어댑터를 통째로 대신하므로, 로그 명령 하나만 바꾸려고 쓰면 빌드와 재생 명령이 사라진다.
    # 일부만 바꾸는 길이 따로 있어야 한다.
    if not isinstance(over, dict):
        return base
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def adapter(cfg):
    # project.json 이 가리키는 어댑터 json 을 읽는다. 없으면 None.
    # adapter 는 "구조가 다른 것"을 담는다. gradle 이냐 npm 이냐, maestro 냐 playwright 냐.
    # project.json 은 "값만 다른 것"을 담는다. 둘을 섞지 않는다.
    if not cfg:
        return None
    inline = cfg.get("adapter_inline")
    if isinstance(inline, dict):
        return inline

    name = cfg.get("adapter")
    if not name:
        return None
    base = os.path.dirname(cfg.get("_path", ""))
    for cand in (os.path.join(base, "adapters", name + ".json"),
                 os.path.join(base, "adapters", name)):
        if os.path.isfile(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    return _merge(json.load(f), cfg.get("adapter_override"))
            except (ValueError, OSError):
                return None
    return None


def expand(template, cfg):
    # 어댑터 명령의 빈칸을 project.json 의 vars 로 채운다.
    # 예: "<빌드도구> {INSTALL_TASK}" + {"INSTALL_TASK": "installDebug"} -> "<빌드도구> installDebug"
    #     실제 명령 문자열은 어댑터에만 있다. 이 파일에는 예시로도 두지 않는다.
    # 못 채운 빈칸은 그대로 남긴다. 조용히 빈 문자열로 만들면 명령이 반쪽이 된 채 실행된다.
    if not template:
        return ""
    vars_map = (cfg or {}).get("vars") or {}
    out = template
    for k, v in vars_map.items():
        out = out.replace("{%s}" % k, str(v))
    return out


def missing_vars(template, cfg):
    # expand 후에도 남은 빈칸 목록. 부르는 쪽이 실행 전에 막을 수 있게 한다.
    import re
    return sorted(set(re.findall(r"\{([A-Z_][A-Z0-9_]*)\}", expand(template, cfg))))


def _sh(value):
    # 셸이 eval 할 수 있게 안전하게 따옴표를 씌운다
    import shlex
    return shlex.quote(str(value))


def export_main(argv):
    # 셸에서 eval 로 읽을 수 있는 형태로 설정을 뿜는다.
    # 사용법: harness_config.py --export [project_dir]
    #
    # 셸에서 json 을 파싱하지 않기 위해서다. 파싱을 셸에 두면 따옴표와 공백에서 조용히 깨진다.
    # 실패해도 종료코드는 0 이다. HC_OK 로 성패를 알리고, 어떻게 끝낼지는 부르는 쪽이 정한다.
    # (런타임 게이트는 설정이 없으면 통과가 아니라 오류로 끝나야 한다.)
    project_dir = argv[1] if len(argv) > 1 else None
    out = []

    cfg = load(project_dir)
    if cfg is None:
        print("HC_OK=0")
        print("HC_ERROR=%s" % _sh("project.json 을 찾지 못했거나 읽을 수 없다"))
        return 0

    # 런타임 게이트를 쓰지 않기로 한 프로젝트 (E2E 개념이 없는 라이브러리 등).
    # "설정을 안 했다" 와 "안 쓰기로 했다" 는 다른 사건이다. 전자는 오류(exit 3), 후자는 정상 SKIP 이다.
    # 이 구분이 없으면 게이트가 매번 실패해 파이프라인이 사람 손을 부른다.
    #
    # 게이트를 꺼도 빌드는 한다. builder 는 이 로더에서 빌드 명령을 받으므로 여기서 끊으면 빌드까지 멈춘다.
    # 그래서 어댑터를 읽을 수 있으면 빌드 명령과 환경변수는 내보낸다.
    # 단 HC_OK 는 어댑터 성패와 무관하게 2 로 둔다. 어댑터가 깨졌다고 0 으로 바꾸면
    # 끄기로 한 게이트가 exit 3 으로 멈춘다. 빌드 명령이 비는 것은 builder 가 따로 막는다.
    ad = adapter(cfg)
    if cfg.get("runtime_gate") is False:
        print("HC_OK=2")
        print("HC_CONFIG=%s" % _sh(cfg.get("_path", "")))
        print("HC_ERROR=%s" % _sh("project.json 에서 runtime_gate 를 끔"))
        if ad is not None:
            print("HC_ADAPTER=%s" % _sh(ad.get("name", "")))
            print("HC_BUILD_CMD=%s" % _sh(expand(ad.get("build") or "", cfg)))
            print("HC_MISSING_BUILD=%s" % _sh(" ".join(missing_vars(ad.get("build") or "", cfg))))
            print("HC_PROJECT_NAME=%s" % _sh((cfg.get("project") or {}).get("name") or ""))
            _print_env(cfg, ad)
        return 0

    if ad is None:
        print("HC_OK=0")
        print("HC_CONFIG=%s" % _sh(cfg.get("_path", "")))
        name = cfg.get("adapter")
        if not name:
            msg = "project.json 의 adapter 가 비어 있다. adapters/ 의 파일명을 적는다"
        else:
            msg = "어댑터 파일을 찾지 못했다: adapters/%s.json" % name
        print("HC_ERROR=%s" % _sh(msg))
        return 0

    e2e_cfg = cfg.get("e2e") or {}
    e2e_ad = ad.get("e2e") or {}
    dev = ad.get("device") or {}

    # 표식이 없으면 하네스 설정 파일 자체를 표식으로 쓴다. 이 워크트리에 설치됐다는 가장 직접적인 증거다.
    # 비워 두면 게이트가 "유효한 워크트리 아님" 으로 매번 멈춘다. 처음 보는 스택이라 /setup 이
    # adapter_inline 을 새로 쓰면서 detect 를 빠뜨리는 경우가 여기 걸린다.
    markers = cfg.get("worktree_markers") or ad.get("detect") or [".claude/project.json"]
    build = expand(ad.get("build") or "", cfg)
    deploy = expand(ad.get("deploy") or "", cfg)
    teardown = expand(ad.get("teardown") or "", cfg)
    e2e_cmd = expand(e2e_ad.get("command") or "", cfg)

    # 남은 빈칸은 실행 전에 알린다. 빈칸을 빈 문자열로 눌러 담으면 반쪽 명령이 돈다.
    # 단 누가 막힐지는 나눠서 알린다. 런타임 게이트는 빌드를 하지 않으므로(빌드는 builder 몫)
    # 빌드 빈칸 때문에 게이트가 멈추면 자기 일과 무관한 이유로 죽는 것이다.
    missing = sorted(set(missing_vars(ad.get("deploy") or "", cfg)
                         + missing_vars(ad.get("teardown") or "", cfg)
                         + missing_vars(e2e_ad.get("command") or "", cfg)))
    missing_build = sorted(set(missing_vars(ad.get("build") or "", cfg)))
    # 세션마다 셸이 채우는 자리는 빈칸으로 세지 않는다
    runtime_slots = {"E2E_PATH", "TAG_OPT", "REPORT_XML", "DEBUG_DIR", "TAGS"}
    missing = [m for m in missing if m not in runtime_slots]
    missing_build = [m for m in missing_build if m not in runtime_slots]

    out.append(("HC_OK", "1"))
    out.append(("HC_CONFIG", cfg.get("_path", "")))
    out.append(("HC_ADAPTER", ad.get("name", "")))
    out.append(("HC_MARKERS", " ".join(markers)))
    out.append(("HC_E2E_DIR", e2e_cfg.get("dir") or e2e_ad.get("dir_default") or ""))
    out.append(("HC_E2E_GLOBS", " ".join(e2e_ad.get("file_globs") or [])))
    out.append(("HC_E2E_CMD", e2e_cmd))
    out.append(("HC_TAG_OPT", expand(e2e_ad.get("tag_option") or "", cfg)))
    # 태그 여러 개를 러너에 넘길 때의 구분자. 러너마다 문법이 다르다 (콤마, 정규식 |, pytest 의 or)
    out.append(("HC_TAG_JOIN", e2e_ad.get("tag_join") or ","))
    out.append(("HC_BUILD_CMD", build))
    out.append(("HC_DEPLOY_CMD", deploy))
    out.append(("HC_TEARDOWN_CMD", teardown))
    out.append(("HC_LOGS_CMD", ((ad.get("logs") or {}).get("command") or "")))
    out.append(("HC_DEVICE_CHECK", dev.get("check") or ""))
    out.append(("HC_DEVICE_FILTER", dev.get("count_filter") or ""))
    out.append(("HC_SKIP_REASON", dev.get("skip_reason") or "no_device"))
    out.append(("HC_MISSING", " ".join(missing)))
    out.append(("HC_MISSING_BUILD", " ".join(missing_build)))
    out.append(("HC_PROJECT_NAME", (cfg.get("project") or {}).get("name") or ""))

    for k, v in out:
        print("%s=%s" % (k, _sh(v)))

    _print_env(cfg, ad)
    return 0


def _print_env(cfg, ad):
    # 환경변수. 있는 것만 export 한다
    for k, v in (cfg.get("env") or {}).items():
        print("export %s=%s" % (k, _sh(os.path.expandvars(str(v)))))
    for k, cands in (cfg.get("env_candidates") or {}).items():
        # 기기마다 경로가 다른 값이다. 존재하는 첫 후보를 쓴다.
        # 없는 경로를 기본값으로 박아두면 실행 단계에 가서야 깨진다.
        cur = os.environ.get(k)
        if cur and os.path.isdir(cur):
            continue
        for c in cands or []:
            c = os.path.expandvars(os.path.expanduser(str(c)))
            if os.path.isdir(c):
                print("export %s=%s" % (k, _sh(c)))
                break
    prepend = ad.get("env_path_prepend") or []
    if prepend:
        parts = []
        for p in prepend:
            p = os.path.expandvars(os.path.expanduser(str(p).replace("{HOME}", "$HOME")))
            parts.append(p)
        print('export PATH=%s:"$PATH"' % _sh(":".join(parts)).replace("'", '"'))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--export":
        sys.exit(export_main(sys.argv[1:]))
    cfg = load()
    print(cfg.get("_path") if cfg else "설정 없음")
