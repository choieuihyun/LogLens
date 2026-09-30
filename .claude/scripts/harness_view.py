#!/usr/bin/env python3
# 하네스 세팅 화면 (결정적, LLM 미개입)
# 역할: 이 프로젝트에 하네스가 어떻게 세팅돼 있는지 HTML 한 장으로 그린다. 보기 전용이다.
#
# 무엇을 읽나 (설치된 파일만 읽고 아무것도 고치지 않는다):
#   .claude/project.json 과 어댑터       설정값
#   .claude/agents/*/AGENT.md             에이전트의 도구 (tools, /setup 이 붙인 tools_extra)
#   .claude/setup/*.md                    에이전트 소개와 질문 표. 질문 표의 "저장 위치" 를 실제 값과 맞대
#                                         무엇이 채워졌고 무엇이 비었는지, 비면 어떻게 되는지를 낸다
#   .claude/project/agents/*.md           /setup 이 채운 에이전트별 보충
#   <docs.domain_map>/*/DOMAIN.md         도메인 문서의 절별 채움 상태
#   .claude/.harness-manifest             설치된 하네스 버전
#
# 왜 LLM 이 아니라 스크립트로 그리나: 보여 주는 값이 실제 파일과 한 글자도 달라서는 안 된다.
# 설정 내용은 파일 밖으로 보내지 않는다. 글꼴만 Google Fonts 에서 받는다 (오프라인이면 시스템 글꼴).
# 결과는 .claude/state/harness-view.html 이다 (커밋 대상 아님).
#
# 사용법: harness_view.py [--open] [project_dir]

import html
import json
import os
import re
import subprocess
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_config
import harness_manifest

# 파이프라인 순서는 뼈대가 정한다 (core/commands). 여기서는 그림으로 옮길 뿐이다.
PIPELINES = [
    ("/fix", "버그 수정", ["explorer", "implementer", "builder", "@gate", "triage", "documenter"]),
    ("/feature", "신규 기능", ["discuss", "spec", "planner", "plan-checker", "@approve", "explorer",
                            "implementer", "verifier", "builder", "@gate", "triage", "documenter"]),
    ("/study", "학습", ["tutor"]),
]
# 에이전트마다 무엇을 받아 무엇을 내놓는지. 카드에 한 줄로 보여 준다 (파일 이름은 커맨드 문서의 계약이다).
IO = {
    "explorer": ("작업 설명, 에러", "explorer-proposal.json"),
    "implementer": ("allowed_to_modify", "소스 수정, implementer.json"),
    "builder": ("adapter.build", "builder.json"),
    "triage": ("runner.json", "triage.json"),
    "documenter": ("changed_files, domains", "DOMAIN.md"),
    "discuss": ("기능 요청", "discuss.json"),
    "spec": ("discuss.json", "spec.json"),
    "planner": ("spec.json", "plan.json"),
    "plan-checker": ("spec.json, plan.json", "plan-check.json"),
    "verifier": ("spec.json, plan.json, 변경 파일", "verifier.json"),
    "tutor": ("주제, learning.*", "학습 노트"),
}
STEPS = {"@gate": ("런타임 게이트", "셸이 올리기, 시나리오 재생, 내리기를 하고 JUnit 결과로 판정한다. LLM 미개입"),
         "@approve": ("사람 승인", "명세와 설계를 보고 사용자가 승인해야 구현이 시작된다")}


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    out = {}
    if m:
        for line in m.group(1).split("\n"):
            k, _, v = line.partition(":")
            if v:
                out[k.strip()] = v.strip()
    return out, text[m.end():] if m else text


def section(body, title):
    m = re.search(r"^## %s\s*\n(.*?)(?=^## |\Z)" % re.escape(title), body, re.S | re.M)
    return m.group(1).strip() if m else ""


def filled(v):
    return v is not None and v != "" and v != [] and v != {}


def lookup(cfg, ad, key):
    # 저장 위치 한 칸이 채워졌는지. 반환: (채움 여부, 보여 줄 값)
    if key == "adapter":
        name = cfg.get("adapter") or ("inline: " + (cfg.get("adapter_inline") or {}).get("name", "")
                                      if cfg.get("adapter_inline") else "")
        return filled(name), name
    if key.startswith("adapter_override") or key == "adapter_inline":
        sub = key.split(".", 1)[1] if "." in key else None
        if sub:
            v = (ad or {}).get(sub)
            return filled(v), v
        v = cfg.get(key)
        return filled(v), v
    cur = cfg
    for part in key.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return filled(cur), cur


def cell(row, i):
    c = [x.strip() for x in row.strip().strip("|").split("|")]
    return c[i] if len(c) > i else ""


def questions(body, cfg, ad, root, agent, domains_filled, tools_extra):
    out = []
    for row in body.split("\n"):
        if not re.match(r"^\| \d+ \|", row):
            continue
        where_raw = cell(row, 3)
        keys = re.findall(r"`([^`]+)`", where_raw)
        state, value = False, None
        for k in keys:
            if k.startswith(".claude/project/agents/"):
                p = os.path.join(root, k)
                ok = os.path.isfile(p)
                state, value = state or ok, ("있음" if ok else None)
            elif k == "DOMAIN.md":
                state, value = state or domains_filled, ("도메인 문서 있음" if domains_filled else None)
            elif k == "tools:":
                state, value = state or bool(tools_extra), (", ".join(tools_extra) or None)
            else:
                ok, v = lookup(cfg, ad, k)
                if ok:
                    state, value = True, v
        out.append({"q": cell(row, 1), "where": ", ".join(keys) or where_raw, "filled": state,
                    "value": value if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)[:300],
                    "ifempty": cell(row, 4)})
    return out


def domain_docs(root, cfg):
    base = ((cfg.get("docs") or {}).get("domain_map") or "").strip()
    out = []
    if not base:
        return out, base
    d = os.path.join(root, base)
    if not os.path.isdir(d):
        return out, base
    for name in sorted(os.listdir(d)):
        text = read(os.path.join(d, name, "DOMAIN.md"))
        if not text:
            continue
        secs = []
        for m in re.finditer(r"^## (.+?)\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M):
            body = re.sub(r"<!--.*?-->", "", m.group(2), flags=re.S)
            lines = [l for l in body.split("\n") if l.strip() and not re.match(r"^\s*\|?[\s|:-]*\|?\s*$", l)
                     and l.strip() not in ("-",) and not re.match(r"^\|[^|]*(용어|파일|축|날짜)[^|]*\|", l)]
            lines = [l for l in lines if not re.fullmatch(r"\s*(-\s*)?(태그|위치):\s*(`<[^>]*>`)?\s*", l)]
            secs.append({"name": m.group(1), "filled": bool(lines)})
        out.append({"name": name, "sections": secs})
    return out, base


def run(args, cwd):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def collect(root):
    dest = os.path.join(root, ".claude")
    cfg = harness_config.load(root) or {}
    ad = harness_config.adapter(cfg) or {}
    agents_cfg = cfg.get("agent_tools") or {}
    docs, domain_map = domain_docs(root, cfg)
    domains_filled = bool(docs)
    agents = {}
    for name in sorted(os.listdir(os.path.join(dest, "agents"))) if os.path.isdir(os.path.join(dest, "agents")) else []:
        fm, _ = frontmatter(read(os.path.join(dest, "agents", name, "AGENT.md")))
        gfm, gbody = frontmatter(read(os.path.join(dest, "setup", name + ".md")))
        extra = [t.strip() for t in fm.get("tools_extra", "").split(",") if t.strip()] or agents_cfg.get(name, [])
        base_tools = [t.strip() for t in fm.get("tools", "").split(",") if t.strip() and t.strip() not in extra]
        title = re.search(r"^# (.+)$", gbody, re.M)
        qs = questions(gbody, cfg, ad, root, name, domains_filled, extra)
        sup = read(os.path.join(dest, "project", "agents", name + ".md"))
        desc = fm.get("description", "")
        parts = [x.strip() for x in desc.split(". ") if x.strip()]
        agents[name] = {
            "title": title.group(1) if title else name,
            "desc": (". ".join(parts[1:]) if len(parts) > 1 else desc).rstrip("."),
            "io": IO.get(name, ("", "")),
            "what": section(gbody, "무엇을 하나"),
            "cannot": section(gbody, "못 하는 것"),
            "gives": section(gbody, "넘겨주는 것"),
            "tools": base_tools, "mcp": extra, "mcp_hint": gfm.get("mcp", ""),
            "questions": qs, "supplement": sup,
        }
    m = harness_manifest.meta(dest)
    update = run([sys.executable, os.path.join(dest, "scripts", "harness_version.py"), root], root)
    selfcheck = run([sys.executable, os.path.join(dest, "scripts", "domains_for.py"), "--self-check"], root)
    e2e_dir = (cfg.get("e2e") or {}).get("dir") or ((ad.get("e2e") or {}).get("dir_default") or "")
    coverage = run([sys.executable, os.path.join(dest, "scripts", "e2e_tags.py"), "--coverage",
                    os.path.join(root, e2e_dir)], root) if e2e_dir else ""
    known = []
    for r in ((cfg.get("domains") or {}).get("dir_rules") or []):
        known += r.get("known") or []
    return {
        "project": (cfg.get("project") or {}).get("name") or os.path.basename(os.path.abspath(root)),
        "config_found": bool(cfg),
        "has_ui": (cfg.get("project") or {}).get("has_ui"),
        "adapter": cfg.get("adapter") or ("inline: " + (cfg.get("adapter_inline") or {}).get("name", "") if cfg.get("adapter_inline") else ""),
        "runtime_gate": cfg.get("runtime_gate", True),
        "build": ad.get("build") or "", "deploy": ad.get("deploy") or "", "teardown": ad.get("teardown") or "",
        "e2e_dir": e2e_dir, "coverage": [c for c in coverage.split(",") if c], "known_domains": known,
        "selfcheck": selfcheck, "domain_map": domain_map, "domains": docs,
        "commit": m.get("harness_commit", "")[:7], "installed_at": m.get("installed_at", ""), "update": update,
        "agents": agents, "pipelines": PIPELINES, "steps": STEPS,
    }


PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>하네스 세팅: __PROJECT__</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Do+Hyeon&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#f6f5f2;--panel:#ffffff;--panel2:#fbfaf8;--line:#e8e5df;--line2:#d9d5ce;
  --ink:#1d1c1a;--text:#5c5853;--dim:#98938c;
  --red:#c2453d;--red-soft:#fbeeec;--red-line:#efc9c5;--red-ink:#a3372f;
  --ok:#2f2d2a;--part:#c2453d;--none:#b9b4ac;
  --title:"Do Hyeon","Plus Jakarta Sans","Apple SD Gothic Neo",sans-serif;
}
*{box-sizing:border-box}
html,body{background:var(--bg)}
body{margin:0;color:var(--text);font:14px/1.6 "Plus Jakarta Sans",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:1200px;margin:0 auto;padding:40px 20px 96px}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.pill{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line2);background:var(--panel);color:var(--text);border-radius:999px;padding:5px 14px;font-size:13px}
.rdot{width:7px;height:7px;border-radius:50%;background:var(--red);display:inline-block;flex:none}
.red{color:var(--red)}
h1{font-family:var(--title);color:var(--ink);font-size:clamp(38px,6vw,68px);line-height:1.05;font-weight:400;letter-spacing:-.01em;text-transform:uppercase;margin:22px 0 14px}
.lead{max-width:680px;font-size:15px}
h2{font-family:var(--title);font-size:clamp(24px,2.8vw,34px);line-height:1.2;font-weight:400;letter-spacing:-.01em;margin:72px 0 22px;color:var(--ink)}
h2 .d{color:var(--dim)}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}

/* 요약 */
.facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-top:36px}
.fact{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.fact b{display:block;font-size:11px;font-weight:500;color:var(--dim);letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px}
.fact span{color:var(--ink);word-break:break-word}
.fact code{color:var(--ink)}
.notes{margin-top:12px;display:flex;flex-direction:column;gap:8px}
.note{display:flex;gap:10px;align-items:flex-start;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 16px;color:var(--text)}
.note .rdot{margin-top:8px}

/* 에이전트 카드 */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px;perspective:1100px}
.card{position:relative;aspect-ratio:4/5;border-radius:18px;border:1px solid var(--line);background:var(--panel);padding:18px;cursor:pointer;
  display:flex;flex-direction:column;will-change:transform;transform-style:preserve-3d;outline:none;transition:border-color .2s}
.card:hover,.card:focus-visible{border-color:var(--line2);box-shadow:0 6px 20px rgba(29,28,26,.06)}
.card:focus-visible{box-shadow:0 0 0 2px var(--red)}
.card .name{font-family:var(--title);color:var(--ink);font-weight:400;font-size:21px;letter-spacing:0}
.card .grp{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);margin-top:2px}
.card .stat{position:absolute;top:20px;right:18px;font-size:11px;color:var(--dim);display:flex;align-items:center;gap:6px}
.card .icon{flex:1;display:flex;align-items:center;justify-content:center;color:var(--ink)}
.card .icon svg{width:40%;height:auto;fill:none;stroke:currentColor;stroke-width:1.2;stroke-linecap:round;stroke-linejoin:round;opacity:.92}
.card .rule{width:44px;height:1px;background:var(--line2);margin:0 0 10px}
.card .io{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--text);margin-bottom:6px;word-break:break-word}
.card .io .red{padding:0 3px}
.card .desc{font-size:12px;line-height:1.5;color:var(--dim)}
.st{display:inline-block;width:7px;height:7px;border-radius:50%}
.s-ok{background:var(--ok)}.s-part{background:var(--part)}.s-none{background:transparent;border:1px solid var(--none)}
.legend{display:flex;flex-wrap:wrap;gap:8px;margin:-8px 0 18px}
.legend .pill{font-size:12px;padding:4px 12px}

/* 파이프라인 */
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:0;margin:0 0 18px}
.flow .cmd{font-family:var(--title);color:var(--ink);font-weight:400;width:100%;margin-bottom:10px;font-size:15px}
.flow .cmd span{color:var(--dim);font-weight:400;margin-left:8px;font-size:13px}
.chip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line2);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 14px;font-size:13px;cursor:pointer;margin:4px 0}
.chip:hover{border-color:var(--dim)}
.chip.step{cursor:default;color:var(--text);background:var(--red-soft);border-color:var(--red-line);color:var(--red-ink)}
.dash{width:26px;height:0;border-top:1px dashed var(--red);opacity:.8;margin:0 4px}

/* 표 */
.tw{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
th{color:var(--dim);font-weight:500;font-size:11px;letter-spacing:.06em;text-transform:uppercase}
td b{color:var(--ink);font-weight:600}
td code{color:var(--ink)}
.ok{color:var(--ok);white-space:nowrap}.no{color:var(--part);white-space:nowrap}
.sec{display:inline-flex;align-items:center;gap:6px;margin:2px 12px 2px 0;font-size:12px}
.hint{font-size:12px;color:var(--dim);margin-top:10px}

/* 상세 */
dialog{border:1px solid var(--line2);border-radius:20px;padding:0;background:var(--panel);color:var(--text);
  width:min(820px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:hidden}
dialog[open]{display:flex;flex-direction:column}
dialog::backdrop{background:rgba(29,28,26,.28);backdrop-filter:blur(2px)}
.dhead{display:flex;align-items:center;gap:16px;padding:20px 24px;border-bottom:1px solid var(--line);flex:none}
.dhead .ic{width:64px;height:36px;border-radius:999px;background:var(--red-soft);border:1px solid var(--red-line);color:var(--red-ink);display:flex;align-items:center;justify-content:center;flex:none}
.dhead .ic svg{width:20px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.dhead h3{font-family:var(--title);margin:0;color:var(--ink);font-size:24px;font-weight:400}
.dhead .sub{font-size:13px;color:var(--dim)}
.dhead button{margin-left:auto;border:1px solid var(--line2);background:transparent;color:var(--ink);border-radius:999px;padding:6px 14px;cursor:pointer;font:inherit;font-size:13px}
.dbody{padding:6px 24px 26px;overflow:auto;overscroll-behavior:contain;flex:1}
.dbody h4{margin:22px 0 8px;font-size:11px;color:var(--dim);font-weight:500;letter-spacing:.08em;text-transform:uppercase}
.dbody p{margin:0;white-space:pre-wrap}
.tag{display:inline-block;border:1px solid var(--line2);border-radius:999px;padding:2px 10px;margin:2px 6px 2px 0;font-size:12px;color:var(--ink)}
.tag.mcp{border-color:var(--red-line);background:var(--red-soft);color:var(--red-ink)}
pre{white-space:pre-wrap;margin:0;font-size:12px;background:var(--panel2);color:var(--text);padding:12px;border-radius:12px;border:1px solid var(--line)}
@media (prefers-reduced-motion:reduce){.card{transition:none}}
</style></head><body><main>
<span class="pill"><span class="rdot"></span>Harness View</span>
<h1>__PROJECT__<br>하네스 세팅<span class="red">.</span></h1>
<div class="lead">이 프로젝트에 하네스가 어떻게 세팅돼 있는지 보여 준다. 보기 전용이다. 바꾸려면 <code>/setup</code>, 다시 그리려면 <code>/harness-view</code>.</div>
<div id="top"></div>

<div class="head"><h2><span class="d">에이전트 <span id="n"></span>개.</span> 누르면 자세히 나온다<span class="red">.</span></h2></div>
<div class="legend">
  <span class="pill"><span class="st s-ok"></span>다 채움</span><span class="pill"><span class="st s-part"></span>일부 빔</span><span class="pill"><span class="st s-none"></span>안 채움</span>
</div>
<div class="cards" id="cards"></div>

<h2><span class="d">파이프라인.</span> 이 순서로 일한다<span class="red">.</span></h2><div id="pipes"></div>
<h2><span class="d">도메인.</span> 에이전트가 읽는 지식<span class="red">.</span></h2><div id="domains"></div>
<h2><span class="d">빈칸.</span> 안 채우면 이렇게 된다<span class="red">.</span></h2><div id="empties"></div>
</main>
<dialog id="dlg"></dialog>
<script>
const D = __DATA__;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

// 역할 묶음과 아이콘. 선 아이콘은 24 격자에 직접 그렸다 (외부 파일 없이 이 페이지 하나로 끝나게).
const GROUP = {explorer:"judge",discuss:"judge",spec:"judge",planner:"judge","plan-checker":"judge",
  implementer:"act",builder:"act",verifier:"check",triage:"check",documenter:"record",tutor:"record"};
const GROUP_NAME = {judge:"판단",act:"실행",check:"검증",record:"기록"};
const ICON = {
  explorer:'<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/><circle cx="12" cy="12" r=".6"/>',
  implementer:'<path d="M14.7 6.3a4 4 0 0 0-5.3 5.1L4 16.8 7.2 20l5.4-5.4a4 4 0 0 0 5.1-5.3l-2.5 2.5-2.3-.6-.6-2.3z"/>',
  builder:'<rect x="4" y="14" width="7" height="6" rx="1"/><rect x="13" y="14" width="7" height="6" rx="1"/><rect x="8.5" y="6" width="7" height="6" rx="1"/>',
  triage:'<path d="M4 5h16l-6 7.5V18l-4 2v-7.5z"/>',
  documenter:'<path d="M6 4h9a3 3 0 0 1 3 3v13H9a3 3 0 0 1-3-3z"/><path d="M6 17a3 3 0 0 1 3-3h9"/><path d="M10 8h4"/>',
  discuss:'<path d="M4 5h10v7H9l-3 3v-3H4z"/><path d="M16 9h4v7h-2v3l-3-3h-3v-2"/>',
  spec:'<rect x="6" y="5" width="12" height="15" rx="1.5"/><path d="M9.5 3.5h5v3h-5z"/><path d="M9 13l2 2 4-4"/>',
  planner:'<path d="M4 6.5l5-2 6 2 5-2v13l-5 2-6-2-5 2z"/><path d="M9 4.5v13M15 6.5v13"/>',
  "plan-checker":'<path d="M10 7h10M10 12h10M10 17h10"/><path d="M4 7l1.2 1.2L7.5 6M4 12l1.2 1.2 2.3-2.2M4 17l1.2 1.2 2.3-2.2"/>',
  verifier:'<path d="M12 3l7 3v6c0 4.2-3 7.3-7 9-4-1.7-7-4.8-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
  tutor:'<path d="M2.5 9.5L12 5l9.5 4.5L12 14z"/><path d="M6.5 11.5V16c3 2 8 2 11 0v-4.5"/><path d="M21.5 9.5v5"/>'
};
const svg = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[n]||'<circle cx="12" cy="12" r="8"/>'}</svg>`;
function state(a){const q=a.questions; if(!q.length) return "ok"; const f=q.filter(x=>x.filled).length; return f===q.length?"ok":(f?"part":"none");}
const io = a => a.io && (a.io[0]||a.io[1]) ? `${esc(a.io[0])}<span class="red">→</span>${esc(a.io[1])}` : "";

function renderTop(){
  let h=`<div class="facts">`;
  const f=(k,v)=>h+=`<div class="fact"><b>${k}</b><span>${v}</span></div>`;
  f("화면 (has_ui)", D.has_ui===null||D.has_ui===undefined?"<span class='no'>모름 · 있는 것으로 본다</span>":(D.has_ui?"있음":"없음"));
  f("어댑터", D.adapter?esc(D.adapter):"<span class='no'>없음</span>");
  f("런타임 게이트", D.runtime_gate===false?"꺼짐":"켜짐");
  f("빌드", `<code>${esc(D.build)||"-"}</code>`);
  f("올리기 / 내리기", `<code>${esc(D.deploy)||"없음"}</code><br><code>${esc(D.teardown)||"없음"}</code>`);
  f("시나리오", `<code>${esc(D.e2e_dir)||"-"}</code><br>${D.coverage.length?esc(D.coverage.join(", ")):"<span class='no'>덮는 도메인 모름</span>"}`);
  f("도메인 규칙", esc(D.selfcheck)||"-");
  f("하네스 버전", `<code>${esc(D.commit)||"기록 없음"}</code><br><span style="color:var(--dim)">${esc(D.installed_at.replace("T"," ").slice(0,16))}</span>`);
  h+=`</div><div class="notes">`;
  if(!D.config_found) h+=`<div class="note"><span class="rdot"></span><div>.claude/project.json 을 찾지 못했다. install.sh 로 설치한 뒤 /setup 을 부른다.</div></div>`;
  if(D.update) h+=`<div class="note"><span class="rdot"></span><div>${esc(D.update)}</div></div>`;
  const unc=D.known_domains.filter(d=>!D.coverage.includes(d));
  if(D.coverage.length&&unc.length) h+=`<div class="note"><span class="rdot"></span><div>시나리오가 없는 도메인: ${esc(unc.join(", "))}. 이 도메인만 고치면 런타임 검증이 없다.</div></div>`;
  h+=`</div>`;
  document.getElementById("top").innerHTML=h;
}

function order(){ const seen=[]; for(const [,,seq] of D.pipelines) for(const n of seq) if(!n.startsWith("@")&&!seen.includes(n)) seen.push(n);
  for(const n of Object.keys(D.agents)) if(!seen.includes(n)) seen.push(n); return seen.filter(n=>D.agents[n]); }

function renderCards(){
  const names=order(); document.getElementById("n").textContent=names.length;
  const el=document.getElementById("cards");
  el.innerHTML=names.map(n=>{const a=D.agents[n]; const f=a.questions.filter(x=>x.filled).length;
    return `<div class="card" data-a="${esc(n)}" tabindex="0" role="button" aria-label="${esc(n)} 자세히">
      <div class="name">${esc(n)}</div><div class="grp">${GROUP_NAME[GROUP[n]]||""}</div>
      <div class="stat"><span class="st s-${state(a)}"></span>${f}/${a.questions.length}${a.mcp.length?" · MCP":""}${a.supplement?" · 보충":""}</div>
      <div class="icon">${svg(n)}</div>
      <div class="rule"></div><div class="io">${io(a)}</div><div class="desc">${esc(a.desc)}</div></div>`;}).join("");
  el.querySelectorAll(".card").forEach(c=>{ c.onclick=()=>show(c.dataset.a); c.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();show(c.dataset.a);}}; tilt(c); });
}

// 기울기 따라가기. 카드마다 스프링 하나: 목표 각도로 당기고(K) 속도를 줄여(DAMP) 떼면 살짝 출렁이며 멈춘다.
const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
function tilt(card){
  if(REDUCE) return;
  const s={x:0,y:0,vx:0,vy:0,tx:0,ty:0}, K=.1, DAMP=.8, MAX=8; let raf=null;
  const step=()=>{ s.vx=(s.vx+(s.tx-s.x)*K)*DAMP; s.x+=s.vx; s.vy=(s.vy+(s.ty-s.y)*K)*DAMP; s.y+=s.vy;
    card.style.transform=`rotateX(${s.y.toFixed(3)}deg) rotateY(${s.x.toFixed(3)}deg)`;
    raf=(Math.abs(s.vx)+Math.abs(s.vy)+Math.abs(s.tx-s.x)+Math.abs(s.ty-s.y)>.005)?requestAnimationFrame(step):null; };
  const kick=()=>{ if(!raf) raf=requestAnimationFrame(step); };
  card.addEventListener("pointermove",e=>{ const r=card.getBoundingClientRect();
    s.tx=((e.clientX-r.left)/r.width-.5)*MAX*2; s.ty=-((e.clientY-r.top)/r.height-.5)*MAX*2; kick(); });
  card.addEventListener("pointerleave",()=>{ s.tx=0; s.ty=0; kick(); });
}

function renderPipes(){
  let h="";
  for(const [cmd,label,seq] of D.pipelines){
    h+=`<div class="flow"><div class="cmd">${esc(cmd)}<span>${esc(label)}</span></div>`;
    seq.forEach((n,i)=>{ if(i) h+=`<span class="dash"></span>`;
      if(n.startsWith("@")){const [t,d]=D.steps[n]; h+=`<span class="chip step" title="${esc(d)}"><span class="rdot"></span>${esc(t)}</span>`;}
      else h+=`<span class="chip" data-a="${esc(n)}"><span class="st s-${D.agents[n]?state(D.agents[n]):"none"}"></span>${esc(n)}</span>`; });
    h+=`</div>`;
  }
  const el=document.getElementById("pipes"); el.innerHTML=h;
  el.querySelectorAll(".chip[data-a]").forEach(c=>c.onclick=()=>show(c.dataset.a));
}

// 모달이 열려 있는 동안 뒤 페이지가 스크롤을 가져가지 않게 막는다. 닫히면(버튼, 바깥 클릭, Esc) 되돌린다.
const dlg=document.getElementById("dlg");
dlg.addEventListener("close",()=>{ document.documentElement.style.overflow=""; document.body.style.overflow=""; });
dlg.addEventListener("click",e=>{ if(e.target===dlg) dlg.close(); });

function show(name){
  const a=D.agents[name]; if(!a) return;
  let h=`<div class="dhead"><div class="ic">${svg(name)}</div><div><h3>${esc(name)}</h3><div class="sub">${esc(a.desc)}</div></div><button type="button" id="dclose">닫기</button></div><div class="dbody">`;
  if(io(a)) h+=`<h4>입력과 출력</h4><div class="mono" style="color:var(--ink)">${io(a)}</div>`;
  if(a.what) h+=`<h4>무엇을 하나</h4><p>${esc(a.what)}</p>`;
  h+=`<h4>도구</h4>${a.tools.map(t=>`<span class="tag">${esc(t)}</span>`).join("")}${a.mcp.map(t=>`<span class="tag mcp">${esc(t)}</span>`).join("")}`;
  h+=`<div class="hint">붙인 MCP: ${a.mcp.length?"빨간 테두리":"없음"} · 권장: ${esc(a.mcp_hint)||"-"}</div>`;
  if(a.cannot) h+=`<h4>못 하는 것</h4><p>${esc(a.cannot)}</p>`;
  if(a.gives) h+=`<h4>넘겨주는 것</h4><p>${esc(a.gives)}</p>`;
  h+=`<h4>이 에이전트를 위한 설정</h4><div class="tw"><table><tr><th>상태</th><th>무엇</th><th>현재 값 / 비면</th></tr>`;
  for(const q of a.questions) h+=`<tr><td class="${q.filled?"ok":"no"}">${q.filled?"채움":"비어 있음"}</td><td>${esc(q.q)}<br><code>${esc(q.where)}</code></td><td>${q.filled?`<code>${esc(q.value)}</code>`:esc(q.ifempty)}</td></tr>`;
  h+=`</table></div><h4>보충 칸</h4><div class="mono" style="color:var(--dim);margin-bottom:8px">.claude/project/agents/${esc(name)}.md</div>`;
  h+=a.supplement?`<pre>${esc(a.supplement)}</pre>`:`<div class="hint">없음. /setup 에서 이 에이전트에게 따로 당부할 것을 적을 수 있다.</div>`;
  h+=`</div>`;
  dlg.innerHTML=h; document.getElementById("dclose").onclick=()=>dlg.close();
  if(!dlg.open){ document.documentElement.style.overflow="hidden"; document.body.style.overflow="hidden"; dlg.showModal(); }
  dlg.querySelector(".dbody").scrollTop=0;
}

function renderDomains(){
  let h="";
  if(!D.domain_map) h=`<div class="hint">docs.domain_map 이 비어 있다. 도메인 지식을 적을 곳이 없어 에이전트가 코드만 보고 판단한다.</div>`;
  else if(!D.domains.length) h=`<div class="hint"><code>${esc(D.domain_map)}</code> 아래에 DOMAIN.md 가 아직 없다.</div>`;
  else{ h=`<div class="tw"><table><tr><th>도메인</th><th>절</th><th>시나리오</th></tr>`;
    for(const d of D.domains) h+=`<tr><td><b>${esc(d.name)}</b></td><td>${d.sections.map(s=>`<span class="sec"><span class="st s-${s.filled?"ok":"none"}"></span>${esc(s.name)}</span>`).join("")}</td><td>${D.coverage.includes(d.name)?"<span class='ok'>있음</span>":"<span class='no'>없음</span>"}</td></tr>`;
    h+=`</table></div>`; }
  const miss=D.known_domains.filter(k=>!D.domains.some(d=>d.name===k));
  if(D.domain_map&&miss.length) h+=`<div class="hint">문서가 없는 도메인: ${esc(miss.join(", "))}</div>`;
  document.getElementById("domains").innerHTML=h;
}

function renderEmpties(){
  const seen=new Map();
  for(const [n,a] of Object.entries(D.agents)) for(const q of a.questions) if(!q.filled){
    if(!seen.has(q.where)) seen.set(q.where,{where:q.where,ifempty:q.ifempty,agents:[]});
    const e=seen.get(q.where); if(!e.agents.includes(n)) e.agents.push(n); }
  if(!seen.size){ document.getElementById("empties").innerHTML=`<div class="hint">비어 있는 설정이 없다.</div>`; return; }
  let h=`<div class="tw"><table><tr><th>설정</th><th>쓰는 에이전트</th><th>안 채우면</th></tr>`;
  for(const e of seen.values()) h+=`<tr><td><code>${esc(e.where)}</code></td><td>${esc(e.agents.join(", "))}</td><td>${esc(e.ifempty)}</td></tr>`;
  h+=`</table></div><div class="hint">채우려면 /setup 을 부르고 "비운 것만 채우기" 를 고른다.</div>`;
  document.getElementById("empties").innerHTML=h;
}

renderTop(); renderCards(); renderPipes(); renderDomains(); renderEmpties();
</script></body></html>
"""


def main():
    args = [a for a in sys.argv[1:] if a != "--open"]
    root = os.path.abspath(args[0] if args else os.getcwd())
    data = collect(root)
    out_dir = os.path.join(root, ".claude", "state")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "harness-view.html")
    page = PAGE.replace("__PROJECT__", html.escape(data["project"])).replace(
        "__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    empty = sum(1 for a in data["agents"].values() for q in a["questions"] if not q["filled"])
    total = sum(len(a["questions"]) for a in data["agents"].values())
    print(out)
    print("에이전트 %d개, 설정 %d칸 중 %d칸 채움, 도메인 문서 %d개%s" % (
        len(data["agents"]), total, total - empty, len(data["domains"]),
        (". " + data["update"]) if data["update"] else ""))
    if "--open" in sys.argv:
        webbrowser.open("file://" + out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
