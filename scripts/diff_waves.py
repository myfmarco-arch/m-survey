#!/usr/bin/env python3
"""比较两波问卷规格，列出可比、需加注和不可比的题目。

用法：
    python3 scripts/diff_waves.py previous.yaml current.yaml [--map Q3:Q4 ...]
        [--codes default|explicit] [--format text|yaml|json]

按题号对应两波题目；题号变了时用 --map 旧题号:新题号。逐题比较：题型和量表、题干、选项文字、
编码含义、矩阵行、显示条件（分母）和题序位置。规则定义见
references/services/validation/tracking-comparability.md。

--codes default 时，没有写明编码的选项按当前产品默认编码推算；插入选项导致的编码移位会被报告为
tracking.code-meaning-changed。已回收问卷应写明全部编码并使用 --codes explicit。

存在 error 时退出码为 1。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spec_lib import (  # noqa: E402
    Report,
    SpecIndex,
    ZH_PROFILE,
    assign_default_codes,
    load_yaml,
    norm_text,
)

SRC = "references/services/validation/tracking-comparability.md"
STATUS = {"error": "不可比", "warning": "需加注"}


def codes_of(idx: SpecIndex, qid: str, mode: str) -> dict[str, object]:
    q = idx.questions[qid]
    if mode == "explicit":
        return {o["id"]: o.get("code") for o in q.get("options", []) or []}
    codes = ZH_PROFILE.codes()
    return assign_default_codes(q, codes["other"], codes["none"])


def logic_key(q: dict) -> str:
    return json.dumps(q.get("display_logic") or {}, sort_keys=True, ensure_ascii=False)


def compare(old: dict, new: dict, mapping: dict[str, str] | None = None, codes_mode: str = "default") -> tuple[Report, list[dict]]:
    mapping = mapping or {}
    a, b = SpecIndex(old), SpecIndex(new)
    report = Report()
    rows: list[dict] = []
    pairs = []
    for old_id in a.order:
        new_id = mapping.get(old_id, old_id)
        if new_id in b.questions:
            pairs.append((old_id, new_id))
        else:
            rows.append({"old": old_id, "new": "", "status": "已删除", "reasons": []})
    matched_new = {n for _, n in pairs}
    for new_id in b.order:
        if new_id not in matched_new:
            rows.append({"old": "", "new": new_id, "status": "新增", "reasons": []})

    for old_id, new_id in pairs:
        qa, qb = a.questions[old_id], b.questions[new_id]
        target = f"QuestionnaireSpec.{new_id}"
        found: list[tuple[str, str, str]] = []

        def add(rule: str, sev: str, msg: str, fix: str) -> None:
            report.add(rule, sev, target, msg, fix, SRC)
            found.append((rule, sev, msg))

        if qa.get("response_type") != qb.get("response_type"):
            add("tracking.scale-changed", "error",
                f"{new_id} 的题型从 {qa.get('response_type')} 改为 {qb.get('response_type')}。",
                "恢复原题型，或把本题标为不可比、下一波重新建立基线。")
        sa, sb = qa.get("scale") or {}, qb.get("scale") or {}
        if (sa or sb) and any(sa.get(k) != sb.get(k) for k in ("min", "max", "low", "high")):
            add("tracking.scale-changed", "error",
                f"{new_id} 的评分从 {sa.get('min')}–{sa.get('max')}（{sa.get('low')} / {sa.get('high')}）"
                f"改为 {sb.get('min')}–{sb.get('max')}（{sb.get('low')} / {sb.get('high')}）。",
                "沿用上一波的点数、锚点和方向；必须修改时标为不可比。")
        if norm_text(qa.get("prompt", "")) != norm_text(qb.get("prompt", "")):
            add("tracking.wording-changed", "warning", f"{new_id} 的题干有改动。",
                "沿用上一波原文，只改必要的版本名；改动了对象或时间范围时标为不可比。")
        oa = {o["id"]: o for o in qa.get("options", []) or []}
        ob = {o["id"]: o for o in qb.get("options", []) or []}
        removed, added = sorted(set(oa) - set(ob)), sorted(set(ob) - set(oa))
        changed = sorted(k for k in set(oa) & set(ob) if norm_text(oa[k].get("text", "")) != norm_text(ob[k].get("text", "")))
        if removed or added or changed:
            parts = []
            if added:
                parts.append(f"新增 {added}")
            if removed:
                parts.append(f"删除 {removed}")
            if changed:
                parts.append(f"改写 {changed}")
            add("tracking.options-changed", "warning", f"{new_id} 的选项有变化：" + "；".join(parts) + "。",
                "受影响的选项不直接比较；多选题的其余选项比例需加注。")
        ra = {r["id"]: norm_text(r.get("text", "")) for r in qa.get("rows", []) or []}
        rb = {r["id"]: norm_text(r.get("text", "")) for r in qb.get("rows", []) or []}
        if ra != rb:
            add("tracking.options-changed", "warning", f"{new_id} 的矩阵行有变化。", "只比较两波都有且文字相同的行。")
        ca, cb = codes_of(a, old_id, codes_mode), codes_of(b, new_id, codes_mode)
        meaning_a = {code: norm_text(oa[k].get("text", "")) for k, code in ca.items() if code is not None}
        meaning_b = {code: norm_text(ob[k].get("text", "")) for k, code in cb.items() if code is not None}
        clashes = sorted(str(c) for c in set(meaning_a) & set(meaning_b) if meaning_a[c] != meaning_b[c])
        if clashes:
            add("tracking.code-meaning-changed", "error",
                f"{new_id} 中编码 {', '.join(clashes)} 在两波中代表不同选项。",
                "沿用上一波编码；新增选项使用新的编码，不要让旧编码换含义。")
        if logic_key(qa) != logic_key(qb):
            add("tracking.base-changed", "warning", f"{new_id} 的显示条件改变，分母不同。",
                "比较时按同一分母重算，或在报告中说明分母变化。")
        before_a = {mapping.get(x, x) for x in a.order[: a.position(old_id)]}
        before_b = set(b.order[: b.position(new_id)])
        inserted = sorted(before_b - before_a)
        if inserted:
            add("tracking.position-changed", "info", f"{new_id} 之前新增了 {inserted}。",
                "检查新增题是否会影响本题（尤其是刺激曝光和相关评价）；在报告中加注。")
        sevs = {s for _, s, _ in found}
        status = "不可比" if "error" in sevs else ("需加注" if "warning" in sevs else "可比")
        rows.append({"old": old_id, "new": new_id, "status": status, "reasons": [m for _, _, m in found]})
    return report, rows


def table(rows: list[dict]) -> str:
    lines = ["| 上一波 | 本波 | 判断 | 原因 |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['old']} | {r['new']} | {r['status']} | {'；'.join(r['reasons'])} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("previous", type=Path)
    ap.add_argument("current", type=Path)
    ap.add_argument("--map", nargs="*", default=[], help="旧题号:新题号")
    ap.add_argument("--codes", choices=["default", "explicit"], default="default")
    ap.add_argument("--format", choices=["text", "yaml", "json"], default="text")
    args = ap.parse_args(argv)
    mapping = dict(x.split(":", 1) for x in args.map)
    report, rows = compare(load_yaml(args.previous), load_yaml(args.current), mapping, args.codes)
    if args.format == "text":
        sys.stdout.write(table(rows) + "\n")
    report.dump(args.format)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
