#!/usr/bin/env python3
"""M-survey 行为评测执行器。

流程分四步，每一步都可以由人工替代：

  prepare   生成每个用例、每次运行的目录，写入 prompt.md（发给 Skill 的消息）、
            setup.md（评测准备）和 judgement.template.json（人工评审模板）。
  generate  （可选）在隔离工作区安装 Skill，用 --cmd 指定的命令生成回答，保存为 response.md。
            命令从标准输入读取提示，向标准输出写回答，例如 "claude -p"。
            也可以手动把回答粘贴到 response.md。
  judge     （可选）用 --cmd 指定的模型命令按 evals/judge-prompt.md 评审，保存 judgement.json。
            也可以人工复制 judgement.template.json 为 judgement.json 后填写。
  report    按 evals/scoring.md 计算单次、用例和评测组结果，写出 report.md 和 results.json。

示例：
  python scripts/run_evals.py list
  python scripts/run_evals.py prepare --suite conformance --runs 3 --out evals/runs/demo
  python scripts/run_evals.py generate --out evals/runs/demo --cmd "claude -p"
  python scripts/run_evals.py judge --out evals/runs/demo --cmd "claude -p"
  python scripts/run_evals.py report --out evals/runs/demo

质量评测（quality 组）使用单独的子命令：同一需求分别在“安装 Skill”和“不安装 Skill”的工作区中生成，
可另加人工撰写的参考交付物，打乱标识后由评审按 evals/quality/rubric.md 逐维打分，最后比较各条件的得分。

  python scripts/run_evals.py quality prepare --runs 3 --out evals/runs/q1 [--reference-dir 参考目录]
  python scripts/run_evals.py quality generate --out evals/runs/q1 --cmd "claude -p"
  python scripts/run_evals.py quality judge --out evals/runs/q1 --cmd "claude -p"
  python scripts/run_evals.py quality report --out evals/runs/q1

被测命令和评审命令需要你自己确认可用；脚本只负责传入提示、保存输出和计算结果。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys as _sys

_sys.dont_write_bytecode = True
import json
import math
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spec_lib import ROOT, load_yaml  # noqa: E402

import yaml  # noqa: E402

SUITES = {
    "conformance": "evals/conformance/cases.yaml",
    "modules": "evals/modules/cases.yaml",
    "product": "evals/products/survey-zh-default.yaml",
}
CJK = r"　-〿㐀-鿿＀-￯“”‘’"
CJK_GAP_RE = re.compile(rf"(?<=[{CJK}])\s+(?=[{CJK}])")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
WORKSPACE_IGNORE = shutil.ignore_patterns(".git", "runs", "__pycache__", ".github", "*.pyc", ".DS_Store")


# ---------------------------------------------------------------- 读取用例
def clean(text: str) -> str:
    return CJK_GAP_RE.sub("", (text or "").strip())


def load_suite(name: str) -> tuple[str, list[dict], list[str]]:
    """返回 (组名, 用例列表, 自动启用的 overlay 列表)。"""
    if name in SUITES:
        data = load_yaml(ROOT / SUITES[name])
        return name, data.get("cases", []), []
    if name.startswith("overlay:"):
        overlay_path = name.split(":", 1)[1]
        ov = load_yaml(ROOT / overlay_path)
        cases = []
        for rel in ov.get("evals", []) or []:
            data = load_yaml((ROOT / overlay_path).parent / rel)
            cases.extend(data.get("cases", []))
        return f"overlay-{ov['id']}", cases, [overlay_path]
    raise SystemExit(f"未知评测组：{name}。可用：{', '.join(SUITES)} 或 overlay:<overlay.yaml 路径>")


def expand_suites(names: list[str]) -> list[str]:
    out = []
    for n in names:
        out.extend(SUITES.keys() if n == "all" else [n])
    return out


def fixture_block(case: dict, strip_notes: bool) -> str:
    parts = []
    for rel in case.get("fixtures", []) or []:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if strip_notes:
            text = COMMENT_RE.sub("", text).strip()
        name = Path(rel).name
        parts.append(f"附件 {name}：\n\n```\n{text.strip()}\n```")
    return "\n\n".join(parts)


def skill_prompt(case: dict) -> str:
    block = fixture_block(case, strip_notes=True)
    return clean(case["request"]) + ("\n\n" + block if block else "") + "\n"


# ---------------------------------------------------------------- prepare
def cmd_prepare(args) -> int:
    out = Path(args.out)
    manifest = {"created": dt.datetime.now().isoformat(timespec="seconds"), "runs": args.runs, "suites": {}}
    skill_version = load_yaml(ROOT / "product.yaml").get("version")
    manifest["skill_version"] = skill_version
    for suite_name in expand_suites(args.suite):
        label, cases, auto_overlays = load_suite(suite_name)
        manifest["suites"][label] = {"source": suite_name, "cases": []}
        for case in cases:
            if args.case and case["id"] not in args.case:
                continue
            overlays = list(dict.fromkeys(auto_overlays + ((case.get("setup") or {}).get("overlays") or [])))
            case_dir = out / label / case["id"]
            for i in range(1, args.runs + 1):
                run_dir = case_dir / f"run-{i}"
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "prompt.md").write_text(skill_prompt(case), encoding="utf-8")
                setup_lines = ["# 评测准备", "", "使用一个全新的会话，不保留上一用例的上下文。", ""]
                if overlays:
                    setup_lines += ["在被测 Skill 的 product.yaml 中设置：", "", "```yaml", "overlays:"]
                    setup_lines += [f"  - {o}" for o in overlays] + ["```", ""]
                else:
                    setup_lines += ["使用默认 product.yaml（overlays 为空）。", ""]
                setup_lines += ["把 prompt.md 的全部内容作为一条消息发送，把完整回答保存为同目录下的 response.md。", ""]
                (run_dir / "setup.md").write_text("\n".join(setup_lines), encoding="utf-8")
                template = {
                    "expected": [{"index": n, "met": None, "evidence": ""} for n in range(1, len(case["expected"]) + 1)],
                    "forbidden": [{"index": n, "occurred": None, "evidence": ""}
                                  for n in range(1, len(case.get("forbidden", []) or []) + 1)],
                    "notes": "",
                    "judge": "human",
                }
                (run_dir / "judgement.template.json").write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
            (case_dir / "case.json").write_text(json.dumps({**case, "overlays": overlays}, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest["suites"][label]["cases"].append(case["id"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    n_cases = sum(len(s["cases"]) for s in manifest["suites"].values())
    print(f"已准备 {n_cases} 个用例 × {args.runs} 次运行：{out}")
    return 0


def iter_runs(out: Path):
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for label, suite in manifest["suites"].items():
        for cid in suite["cases"]:
            case_dir = out / label / cid
            case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
            for run_dir in sorted(case_dir.glob("run-*")):
                yield label, case, run_dir


# ---------------------------------------------------------------- generate
def make_workspace(run_dir: Path, case: dict, install_path: str, out: Path) -> Path:
    ws = run_dir / "workspace"
    if ws.exists():
        shutil.rmtree(ws)
    skill_dir = ws / install_path
    out_resolved = out.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = set(WORKSPACE_IGNORE(directory, names))
        at_root = Path(directory).resolve() == ROOT
        for n in names:
            if (Path(directory) / n).resolve() == out_resolved:
                skipped.add(n)  # 运行目录位于仓库内时，避免把自己复制进工作区
            if at_root and n in {"evals", "tests"}:
                skipped.add(n)  # 评测用例和参考答案不进入被测环境
        return skipped

    shutil.copytree(ROOT, skill_dir, ignore=ignore)
    if case.get("overlays"):
        product_path = skill_dir / "product.yaml"
        product = load_yaml(product_path)
        product["overlays"] = case["overlays"]
        product_path.write_text(yaml.safe_dump(product, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ws


def run_cmd(cmd: str, prompt: str, cwd: Path, timeout: int) -> tuple[int, str, str]:
    proc = subprocess.run(shlex.split(cmd), input=prompt, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def cmd_generate(args) -> int:
    out = Path(args.out)
    failures = 0
    for label, case, run_dir in iter_runs(out):
        target = run_dir / "response.md"
        if target.exists() and not args.overwrite:
            continue
        ws = make_workspace(run_dir, case, args.install_path, out)
        prompt = (run_dir / "prompt.md").read_text(encoding="utf-8")
        try:
            code, stdout, stderr = run_cmd(args.cmd, prompt, ws, args.timeout)
        except subprocess.TimeoutExpired:
            code, stdout, stderr = -1, "", "timeout"
        if code != 0 or not stdout.strip():
            failures += 1
            (run_dir / "generate.error.txt").write_text(f"exit={code}\n{stderr}", encoding="utf-8")
            print(f"[失败] {label}/{case['id']}/{run_dir.name}：exit={code}")
            continue
        target.write_text(stdout, encoding="utf-8")
        if not args.keep_workspace:
            shutil.rmtree(ws)
        print(f"[完成] {label}/{case['id']}/{run_dir.name}")
    return 1 if failures else 0


# ---------------------------------------------------------------- judge
def numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {clean(t)}" for i, t in enumerate(items, 1)) or "（无）"


def judge_prompt(case: dict, response: str) -> str:
    template = (ROOT / "evals" / "judge-prompt.md").read_text(encoding="utf-8")
    fixtures = fixture_block(case, strip_notes=False)
    return template.format(
        case_id=case["id"],
        request=clean(case["request"]),
        fixtures=("用户提供的附件（HTML 注释中的参考答案只供评审参考，被测 Skill 看不到）：\n\n" + fixtures) if fixtures else "",
        expected=numbered(case["expected"]),
        forbidden=numbered(case.get("forbidden", []) or []),
        response=response.strip(),
    )


def extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def cmd_judge(args) -> int:
    out = Path(args.out)
    failures = 0
    for label, case, run_dir in iter_runs(out):
        resp = run_dir / "response.md"
        target = run_dir / "judgement.json"
        if not resp.exists() or (target.exists() and not args.overwrite):
            continue
        prompt = judge_prompt(case, resp.read_text(encoding="utf-8"))
        (run_dir / "judge-prompt.txt").write_text(prompt, encoding="utf-8")
        try:
            code, stdout, stderr = run_cmd(args.cmd, prompt, run_dir, args.timeout)
            data = extract_json(stdout)
            data["judge"] = args.cmd
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[完成] {label}/{case['id']}/{run_dir.name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            (run_dir / "judge.error.txt").write_text(str(exc), encoding="utf-8")
            print(f"[失败] {label}/{case['id']}/{run_dir.name}：{exc}")
    return 1 if failures else 0


# ---------------------------------------------------------------- report
def run_verdict(case: dict, j: dict) -> tuple[str, str]:
    n_exp = len(case["expected"])
    n_forb = len(case.get("forbidden", []) or [])
    exp = {e["index"]: e for e in j.get("expected", [])}
    forb = {f["index"]: f for f in j.get("forbidden", [])}
    if set(exp) != set(range(1, n_exp + 1)) or set(forb) != set(range(1, n_forb + 1)):
        return "invalid", "评审结果条目数与用例不一致"
    if any(not isinstance(v.get("met"), bool) for v in exp.values()) or \
            any(not isinstance(v.get("occurred"), bool) for v in forb.values()):
        return "invalid", "评审结果存在未填写项或非布尔值（必须是 true / false）"
    occurred = [i for i, f in forb.items() if f["occurred"]]
    unmet = [i for i, e in exp.items() if not e["met"]]
    if occurred:
        return "fail", f"出现禁止行为 {occurred}"
    if not unmet:
        return "pass", ""
    if len(unmet) == 1:
        return "partial", f"未满足预期 {unmet}"
    return "fail", f"未满足预期 {unmet}"


def cmd_report(args) -> int:
    out = Path(args.out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    results = {"created": dt.datetime.now().isoformat(timespec="seconds"), "skill_version": manifest.get("skill_version"),
               "model": args.model, "judge": args.judge_label, "suites": {}}
    overall_ok = True
    lines = ["# 评测报告", "", f"- Skill 版本：{manifest.get('skill_version')}", f"- 被测模型：{args.model or '未填写'}",
             f"- 评审方式：{args.judge_label or '未填写'}", f"- 每个用例运行次数：{manifest['runs']}", ""]
    for label, suite in manifest["suites"].items():
        case_rows = []
        blocking_ok = True
        nb_total = nb_pass = 0
        incomplete = 0
        for cid in suite["cases"]:
            case_dir = out / label / cid
            case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
            runs = []
            for run_dir in sorted(case_dir.glob("run-*")):
                jp = run_dir / "judgement.json"
                if not jp.exists():
                    runs.append(("missing", "缺少 judgement.json"))
                    continue
                runs.append(run_verdict(case, json.loads(jp.read_text(encoding="utf-8"))))
            n = len(runs)
            need = math.ceil(2 * n / 3)
            n_pass = sum(1 for v, _ in runs if v == "pass")
            if any(v in {"missing", "invalid"} for v, _ in runs):
                status = "incomplete"
                incomplete += 1
            elif any(v == "fail" and r.startswith("出现禁止行为") for v, r in runs):
                status = "fail"
            else:
                status = "pass" if n_pass >= need else "fail"
            blocking = case.get("blocking", True) or label == "conformance"
            if blocking and status != "pass":
                blocking_ok = False
            if not blocking:
                nb_total += 1
                nb_pass += status == "pass"
            case_rows.append({"id": cid, "blocking": blocking, "status": status, "pass_runs": n_pass, "runs": n,
                              "details": [{"verdict": v, "reason": r} for v, r in runs]})
        nb_rate = (nb_pass / nb_total) if nb_total else 1.0
        nb_allowed_fail = max(1, nb_total // 5) if nb_total else 0
        if label == "conformance":
            suite_ok = all(c["status"] == "pass" for c in case_rows)
        else:
            suite_ok = blocking_ok and (nb_total - nb_pass) <= nb_allowed_fail
        if incomplete:
            suite_ok = False
        overall_ok &= suite_ok
        results["suites"][label] = {"passed": suite_ok, "incomplete_cases": incomplete,
                                    "non_blocking_pass_rate": round(nb_rate, 3), "cases": case_rows}
        lines += [f"## {label}：{'通过' if suite_ok else '未通过'}", "",
                  "| 用例 | 阻断 | 结果 | 通过次数 | 说明 |", "|---|---|---|---|---|"]
        for c in case_rows:
            reasons = "；".join(d["reason"] for d in c["details"] if d["reason"])
            lines.append(f"| {c['id']} | {'是' if c['blocking'] else '否'} | {c['status']} | {c['pass_runs']}/{c['runs']} | {reasons} |")
        lines.append("")
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if overall_ok else 1


# ---------------------------------------------------------------- list
def cmd_list(args) -> int:
    for suite_name in expand_suites(args.suite):
        label, cases, overlays = load_suite(suite_name)
        print(f"## {label}（{len(cases)} 个用例）" + (f"，自动启用 {overlays}" if overlays else ""))
        for c in cases:
            mod = f" [{c['module']}]" if c.get("module") else ""
            print(f"- {c['id']}{mod} kind={c.get('kind')} blocking={c.get('blocking', True)}")
    return 0


# ================================================================ quality 组
QUALITY_CASES = "evals/quality/cases.yaml"
RUBRIC = "evals/quality/rubric.md"
QUALITY_JUDGE = "evals/quality/judge-prompt.md"
LABELS = "ABCDEFGH"


def rubric_dimensions() -> list[str]:
    """量表中的维度键，按表格顺序。"""
    text = (ROOT / RUBRIC).read_text(encoding="utf-8")
    return re.findall(r"^\| `([a-z_]+)` \|", text, re.M)


def load_quality() -> dict:
    return load_yaml(ROOT / QUALITY_CASES)


def blind_order(conditions: list[str], case_id: str, run: str, seed: str) -> dict[str, str]:
    """确定性打乱：同一用例、同一运行、同一种子，标识分配固定。返回 {字母: 条件}。"""
    import hashlib
    keyed = sorted(conditions, key=lambda c: hashlib.sha256(f"{seed}:{case_id}:{run}:{c}".encode()).hexdigest())
    return {LABELS[i]: c for i, c in enumerate(keyed)}


def quality_judge_prompt(case: dict, responses: dict[str, str]) -> str:
    template = (ROOT / QUALITY_JUDGE).read_text(encoding="utf-8")
    rubric = (ROOT / RUBRIC).read_text(encoding="utf-8")
    rubric = "## 评分方式" + rubric.split("## 评分方式", 1)[-1] if "## 评分方式" in rubric else rubric
    rubric = re.sub(r"^## ", "### ", rubric, flags=re.M)  # 嵌入评审提示时降一级标题
    fixtures = fixture_block(case, strip_notes=True)
    blocks = "\n\n".join(f"### 交付物 {label}\n\n{text.strip()}" for label, text in sorted(responses.items()))
    return template.format(
        rubric=rubric.strip(),
        request=clean(case["request"]),
        fixtures=("用户提供的附件：\n\n" + fixtures) if fixtures else "",
        responses=blocks,
        dimensions="、".join(rubric_dimensions()),
    )


def validate_quality_judgement(data: dict, labels: list[str], dims: list[str]) -> str:
    """返回空字符串表示有效；否则返回原因。"""
    scores = data.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(labels):
        return f"scores 的字母应为 {sorted(labels)}"
    for label in labels:
        for d in dims:
            item = (scores[label] or {}).get(d)
            score = item.get("score") if isinstance(item, dict) else None
            if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
                return f"{label}.{d} 的分数不是 1–5 的整数"
    ranking = data.get("ranking")
    if not isinstance(ranking, list) or sorted(ranking) != sorted(labels):
        return "ranking 必须包含全部字母各一次"
    return ""


def q_prepare(args) -> int:
    data = load_quality()
    out = Path(args.out)
    conditions = list(args.conditions or data.get("conditions") or ["skill", "baseline"])
    ref_dir = Path(args.reference_dir) if args.reference_dir else None
    manifest = {"created": dt.datetime.now().isoformat(timespec="seconds"), "runs": args.runs,
                "skill_version": load_yaml(ROOT / "product.yaml").get("version"), "seed": args.seed, "cases": []}
    for case in data.get("cases", []):
        if args.case and case["id"] not in args.case:
            continue
        case_conditions = list(conditions)
        ref = ref_dir / f"{case['id']}.md" if ref_dir else None
        if ref and ref.exists():
            case_conditions.append("reference")
        case_dir = out / "quality" / case["id"]
        for i in range(1, args.runs + 1):
            for cond in case_conditions:
                run_dir = case_dir / f"run-{i}" / cond
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "prompt.md").write_text(skill_prompt(case), encoding="utf-8")
                if cond == "reference":
                    shutil.copyfile(ref, run_dir / "response.md")
        (case_dir / "case.json").write_text(json.dumps({**case, "conditions": case_conditions}, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        manifest["cases"].append(case["id"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "quality-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已准备 {len(manifest['cases'])} 个质量用例 × {args.runs} 次运行：{out}")
    return 0


def q_iter(out: Path):
    manifest = json.loads((out / "quality-manifest.json").read_text(encoding="utf-8"))
    for cid in manifest["cases"]:
        case_dir = out / "quality" / cid
        case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        for run_dir in sorted(case_dir.glob("run-*")):
            yield case, run_dir


def q_generate(args) -> int:
    out = Path(args.out)
    failures = 0
    for case, run_dir in q_iter(out):
        for cond in case["conditions"]:
            if cond == "reference":
                continue
            cdir = run_dir / cond
            target = cdir / "response.md"
            if target.exists() and not args.overwrite:
                continue
            if cond == "skill":
                ws = make_workspace(cdir, {"overlays": []}, args.install_path, out)
            else:
                ws = cdir / "workspace"
                if ws.exists():
                    shutil.rmtree(ws)
                ws.mkdir(parents=True)
            prompt = (cdir / "prompt.md").read_text(encoding="utf-8")
            try:
                code, stdout, stderr = run_cmd(args.cmd, prompt, ws, args.timeout)
            except subprocess.TimeoutExpired:
                code, stdout, stderr = -1, "", "timeout"
            if code != 0 or not stdout.strip():
                failures += 1
                (cdir / "generate.error.txt").write_text(f"exit={code}\n{stderr}", encoding="utf-8")
                print(f"[失败] {case['id']}/{run_dir.name}/{cond}：exit={code}")
                continue
            target.write_text(stdout, encoding="utf-8")
            if not args.keep_workspace:
                shutil.rmtree(ws)
            print(f"[完成] {case['id']}/{run_dir.name}/{cond}")
    return 1 if failures else 0


def q_judge(args) -> int:
    out = Path(args.out)
    manifest = json.loads((out / "quality-manifest.json").read_text(encoding="utf-8"))
    seed = str(manifest.get("seed", "m-survey"))
    dims = rubric_dimensions()
    failures = 0
    for case, run_dir in q_iter(out):
        target = run_dir / "judgement.json"
        if target.exists() and not args.overwrite:
            continue
        present = [c for c in case["conditions"] if (run_dir / c / "response.md").exists()]
        if len(present) < 2:
            print(f"[跳过] {case['id']}/{run_dir.name}：可比较的回答少于 2 份")
            continue
        mapping = blind_order(present, case["id"], run_dir.name, seed)
        (run_dir / "blind.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        responses = {label: (run_dir / cond / "response.md").read_text(encoding="utf-8") for label, cond in mapping.items()}
        prompt = quality_judge_prompt(case, responses)
        (run_dir / "judge-prompt.txt").write_text(prompt, encoding="utf-8")
        try:
            code, stdout, stderr = run_cmd(args.cmd, prompt, run_dir, args.timeout)
            data = extract_json(stdout)
            problem = validate_quality_judgement(data, list(mapping), dims)
            if problem:
                raise ValueError(problem)
            data["judge"] = args.cmd
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[完成] {case['id']}/{run_dir.name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            (run_dir / "judge.error.txt").write_text(str(exc), encoding="utf-8")
            print(f"[失败] {case['id']}/{run_dir.name}：{exc}")
    return 1 if failures else 0


def q_aggregate(records: list[dict], dims: list[str]) -> dict:
    """records：[{case, run, scores: {条件: {维度: 分}}, rank: [条件…]}]。返回各条件均分、差值和胜率。"""
    by_cond: dict[str, dict[str, list[int]]] = {}
    for r in records:
        for cond, sc in r["scores"].items():
            for d in dims:
                by_cond.setdefault(cond, {k: [] for k in dims})[d].append(sc[d])
    means = {c: {d: round(sum(v) / len(v), 2) for d, v in ds.items() if v} for c, ds in by_cond.items()}
    for c in means:
        means[c]["overall"] = round(sum(means[c][d] for d in dims) / len(dims), 2)
    delta = {}
    if "skill" in means and "baseline" in means:
        delta = {d: round(means["skill"][d] - means["baseline"][d], 2) for d in dims + ["overall"]}
    wins = ties = losses = 0
    for r in records:
        if "skill" in r["scores"] and "baseline" in r["scores"]:
            s = sum(r["scores"]["skill"].values())
            b = sum(r["scores"]["baseline"].values())
            wins += s > b
            ties += s == b
            losses += s < b
    first = {}
    for r in records:
        if r["rank"]:
            first[r["rank"][0]] = first.get(r["rank"][0], 0) + 1
    return {"means": means, "delta_skill_minus_baseline": delta,
            "skill_vs_baseline": {"wins": wins, "ties": ties, "losses": losses}, "ranked_first": first,
            "n_comparisons": len(records)}


def q_report(args) -> int:
    out = Path(args.out)
    manifest = json.loads((out / "quality-manifest.json").read_text(encoding="utf-8"))
    dims = rubric_dimensions()
    records, missing = [], []
    for case, run_dir in q_iter(out):
        jp, bp = run_dir / "judgement.json", run_dir / "blind.json"
        if not jp.exists() or not bp.exists():
            missing.append(f"{case['id']}/{run_dir.name}")
            continue
        mapping = json.loads(bp.read_text(encoding="utf-8"))
        data = json.loads(jp.read_text(encoding="utf-8"))
        problem = validate_quality_judgement(data, list(mapping), dims)
        if problem:
            missing.append(f"{case['id']}/{run_dir.name}（{problem}）")
            continue
        scores = {mapping[l]: {d: data["scores"][l][d]["score"] for d in dims} for l in mapping}
        records.append({"case": case["id"], "run": run_dir.name, "scores": scores,
                        "rank": [mapping[l] for l in data["ranking"]]})
    agg = q_aggregate(records, dims)
    lines = ["# 质量评测报告", "", f"- Skill 版本：{manifest.get('skill_version')}", f"- 被测模型：{args.model or '未填写'}",
             f"- 评审方式：{args.judge_label or '未填写'}", f"- 有效比较次数：{agg['n_comparisons']}", ""]
    conds = sorted(agg["means"])
    lines += ["## 各条件均分（1–5）", "", "| 维度 | " + " | ".join(conds) + (" | skill − baseline |" if agg["delta_skill_minus_baseline"] else " |"),
              "|---|" + "---:|" * (len(conds) + (1 if agg["delta_skill_minus_baseline"] else 0))]
    for d in dims + ["overall"]:
        row = [f"{agg['means'][c].get(d, '')}" for c in conds]
        if agg["delta_skill_minus_baseline"]:
            row.append(f"{agg['delta_skill_minus_baseline'][d]:+}")
        lines.append(f"| {d} | " + " | ".join(row) + " |")
    s = agg["skill_vs_baseline"]
    lines += ["", f"skill 对 baseline：胜 {s['wins']}，平 {s['ties']}，负 {s['losses']}。",
              f"排名第一的次数：{agg['ranked_first']}。", "",
              "比较次数少时，差值只说明方向。结论需要在更多用例、更多次运行和独立评审下确认。"]
    if missing:
        lines += ["", "未计入：" + "；".join(missing)]
    (out / "quality-results.json").write_text(json.dumps({"manifest": manifest, "model": args.model,
                                                           "judge": args.judge_label, **agg, "records": records},
                                                          ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "quality-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if not missing else 1


def add_quality_parser(sub) -> None:
    q = sub.add_parser("quality", help="质量评测：skill 与 baseline 盲评比较")
    qs = q.add_subparsers(dest="qcommand", required=True)
    p = qs.add_parser("prepare")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--case", nargs="*")
    p.add_argument("--conditions", nargs="*", help="默认读取 cases.yaml 的 conditions")
    p.add_argument("--reference-dir", help="人工撰写参考交付物所在目录，文件名为 <用例 id>.md")
    p.add_argument("--seed", default="m-survey", help="盲评标识的打乱种子")
    p.add_argument("--out", default=f"evals/runs/quality-{dt.date.today().isoformat()}")
    p.set_defaults(func=q_prepare)
    p = qs.add_parser("generate")
    p.add_argument("--out", required=True)
    p.add_argument("--cmd", required=True)
    p.add_argument("--install-path", default=".claude/skills/m-survey")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--keep-workspace", action="store_true")
    p.set_defaults(func=q_generate)
    p = qs.add_parser("judge")
    p.add_argument("--out", required=True)
    p.add_argument("--cmd", required=True)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=q_judge)
    p = qs.add_parser("report")
    p.add_argument("--out", required=True)
    p.add_argument("--model")
    p.add_argument("--judge-label")
    p.set_defaults(func=q_report)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="列出用例")
    p.add_argument("--suite", nargs="+", default=["all"])
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("prepare", help="生成运行目录和提示")
    p.add_argument("--suite", nargs="+", default=["conformance"],
                   help="conformance、modules、product、all 或 overlay:<overlay.yaml 路径>")
    p.add_argument("--case", nargs="*", help="只准备指定用例 ID")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--out", default=f"evals/runs/{dt.date.today().isoformat()}")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("generate", help="调用被测命令生成回答")
    p.add_argument("--out", required=True)
    p.add_argument("--cmd", required=True, help='从 stdin 读提示、向 stdout 写回答的命令，例如 "claude -p"')
    p.add_argument("--install-path", default=".claude/skills/m-survey", help="Skill 在工作区中的安装路径")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--keep-workspace", action="store_true")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("judge", help="调用评审命令生成 judgement.json")
    p.add_argument("--out", required=True)
    p.add_argument("--cmd", required=True)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_judge)

    p = sub.add_parser("report", help="计算结果")
    p.add_argument("--out", required=True)
    p.add_argument("--model", help="被测模型名称，写入报告")
    p.add_argument("--judge-label", help="评审方式，例如 human 或模型名称")
    p.set_defaults(func=cmd_report)

    add_quality_parser(sub)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
