#!/usr/bin/env python3
"""估算问卷时长：典型路径和最长路径。

用法：
    python3 scripts/estimate_duration.py spec.yaml [--params timing.yaml] [--target 10] [--format text|json]

每道题的时间 = 阅读时间（题干、选项、矩阵行的字数 ÷ 阅读速度）+ 作答时间（按题型）。
典型路径按每题预计看到的比例（expected_share）和预计循环次数（expected_loops）加权；
最长路径假设全部题目都显示、循环取最大次数。

参数默认读取 references/modules/knowledge/timing-parameters.yaml。那是起始假设，
未经校准时，结果只能说明量级，不能直接写成对受访者的承诺。校准方法见
references/services/validation/respondent-burden.md。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spec_lib import estimate_duration, load_timing, load_yaml  # noqa: E402


def render_text(result: dict, target: float | None) -> str:
    lines = [
        f"典型路径：约 {result['typical_minutes']} 分钟",
        f"最长路径：约 {result['max_minutes']} 分钟",
        f"参数状态：{result['parameter_status']}；校准系数 {result['calibration'].get('factor', 1.0)}"
        f"（{result['calibration'].get('basis', '未校准')}）",
    ]
    if target:
        diff = round(result["typical_minutes"] - target, 1)
        lines.append(f"目标时长：{target} 分钟；典型路径{'超出' if diff > 0 else '低于'}目标 {abs(diff)} 分钟")
    top = sorted(result["questions"], key=lambda r: r["typical"], reverse=True)[:5]
    lines += ["", "最耗时的 5 道题（典型路径秒数）："]
    lines += [f"- {r['id']}【{r['label']}】{r['typical']:g} 秒（单次 {r['seconds']:g} 秒，看到比例 {r['share']:g}，"
              f"循环 {r['loops']:g} 次）" for r in top]
    if result["defaults_used"]:
        lines += ["", "以下题目使用了参数文件的默认假设，建议在规格中填写 expected_share / expected_loops："]
        lines += [f"- {x}" for x in result["defaults_used"]]
    lines += ["", "| 题号 | 标签 | 单次秒数 | 典型路径秒数 | 最长路径秒数 |", "|---|---|---:|---:|---:|"]
    lines += [f"| {r['id']} | {r['label']} | {r['seconds']:g} | {r['typical']:g} | {r['max']:g} |"
              for r in result["questions"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path)
    ap.add_argument("--params", type=Path, help="时长参数文件")
    ap.add_argument("--target", type=float, help="目标时长（分钟）；默认读取 meta.target_minutes")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args(argv)
    spec = load_yaml(args.spec)
    result = estimate_duration(spec, load_timing(args.params) if args.params else None)
    target = args.target or (spec.get("meta") or {}).get("target_minutes")
    if args.format == "json":
        json.dump({**result, "target_minutes": target}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_text(result, target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
