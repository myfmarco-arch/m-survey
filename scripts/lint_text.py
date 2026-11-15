#!/usr/bin/env python3
"""宽松检查：不依赖题目格式，审核从在线文档、表格或其他平台导出的问卷。

用法：
    python scripts/lint_text.py questionnaire.md [--format text|yaml|json]

检查内容：
- spec.text-residue            表格公式错误（#VALUE! 等）和删除线 ~~ 残留
- spec.range-overlap           同一题内数值区间选项边界重叠（例如“7-15天”和“15-30天”）
- measurement.scale-consistency 评分方向不一致（一处 1 = 负面，另一处 1 = 正面）
- spec.id-unique               题号重复
- spec.logic-reference         显示条件引用了文中不存在的题号

这些是启发式检查，结果都需要人工确认。完整检查仍需把问卷整理成 QuestionnaireSpec 后运行
validate_spec.py。存在 error 时退出码为 1。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spec_lib import RESIDUE_RE, Report, range_overlaps  # noqa: E402

SRC_SPEC = "references/services/validation/spec-integrity.md"
SRC_MEAS = "references/services/validation/measurement-integrity.md"

QID = r"[A-Z]{1,3}\d{1,3}[a-z]?"
# 题目行：Markdown 标题中的题号，或行首题号后紧跟标点（“Q5.”“S3、”）
HEADING_RE = re.compile(rf"^\s*(?:#{{1,6}}\s*(?:\*\*)?\s*({QID})(?![A-Za-z0-9])|(?:\*\*)?({QID})\s*[\.．、:：])")
# 题号出现在行首或表格单元格开头，视为“文中存在”（矩阵子题、选项表中的子题号等）
TOKEN_RE = re.compile(rf"(?:^|\|)\s*(?:#{{1,6}}\s*)?(?:\*\*)?\s*({QID})(?![A-Za-z0-9=≠＝])")
REF_RE = re.compile(rf"(?<![A-Za-z0-9])({QID})(?:_r?\d+)?\s*(?:=|≠|＝)")
ANCHOR_RE = re.compile(r"(\d+)\s*分?\s*(?:=|＝|表示|代表)\s*[“\"「]?([^，,；;。、\s“”\"」）)]{2,10})")
NEG = ("非常不满意", "非常差", "非常不喜欢", "最不喜欢", "非常困难", "非常不同意", "完全不同意",
       "完全不可能", "非常不愿意", "非常不重要", "极不满意", "很差")
POS = ("非常满意", "非常好", "非常喜欢", "最喜欢", "非常容易", "非常同意", "完全同意",
       "非常可能", "极有可能", "非常愿意", "非常重要", "极满意", "很好")


def polarity(anchor: str) -> str | None:
    for w in NEG:
        if w in anchor:
            return "neg"
    for w in POS:
        if w in anchor:
            return "pos"
    return None


def split_blocks(lines: list[str]) -> list[tuple[str, int, list[str]]]:
    """按题号行切分，返回 (题号, 行号, 该题的行)。题号行之前的内容不属于任何题。"""
    blocks: list[tuple[str, int, list[str]]] = []
    current: tuple[str, int, list[str]] | None = None
    for i, line in enumerate(lines, 1):
        m = HEADING_RE.match(line)
        if m:
            current = (m.group(1) or m.group(2), i, [line])
            blocks.append(current)
        elif current is not None:
            current[2].append(line)
    return blocks


def option_texts(block_lines: list[str]) -> list[str]:
    """取出看起来像选项的短文本：表格单元格或独立短行。"""
    out = []
    for line in block_lines[1:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith("|"):
            out += [c.strip() for c in s.strip("|").split("|") if c.strip()]
        elif len(s) <= 40:
            out.append(s.lstrip("-*• ").strip())
    return out


def lint(text: str, report: Report) -> None:
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        m = RESIDUE_RE.search(line)
        if m:
            report.add("spec.text-residue", "error", f"Text:L{i}", f"第 {i} 行有残留“{m.group(0)}”：{line.strip()[:50]}",
                       "删除表格公式错误、删除线和修订痕迹，替换为正确内容。", SRC_SPEC)

    blocks = split_blocks(lines)
    seen: dict[str, int] = {}
    for qid, ln, _ in blocks:
        if qid in seen:
            report.add("spec.id-unique", "warning", f"Text:L{ln}", f"题号 {qid} 重复（第 {seen[qid]} 行和第 {ln} 行）。",
                       "确认是否为重复题号；使用唯一题号。", SRC_SPEC)
        else:
            seen[qid] = ln
    for qid, ln, blines in blocks:
        pairs = range_overlaps(option_texts(blines))
        if pairs:
            shown = "；".join(f"“{a}”和“{b}”" for a, b in pairs[:3])
            more = f" 等 {len(pairs)} 处" if len(pairs) > 3 else ""
            report.add("spec.range-overlap", "warning", f"Text.{qid}", f"{qid}（第 {ln} 行）的区间边界重叠：{shown}{more}。",
                       "改为半开写法，例如“1 年至不到 3 年”，或写明边界值归哪一项。", SRC_SPEC)

    # 题号太少说明文档没有统一编号，引用检查只会产生噪声
    defined = set(seen)
    for line in lines:
        defined |= set(TOKEN_RE.findall(line))
    prefixes = {re.match(r"[A-Z]+", q).group(0) for q in seen}
    if len(seen) >= 5:
        for i, line in enumerate(lines, 1):
            for ref in REF_RE.findall(line):
                if ref not in defined and re.match(r"[A-Z]+", ref).group(0) in prefixes:
                    report.add("spec.logic-reference", "warning", f"Text:L{i}",
                               f"第 {i} 行引用了文中没有的题号 {ref}：{line.strip()[:50]}",
                               "核对题号；题号改过时同步修改所有显示条件。", SRC_SPEC)

    lows: dict[str, list[int]] = {"pos": [], "neg": []}
    for i, line in enumerate(lines, 1):
        anchors = [(int(n), a) for n, a in ANCHOR_RE.findall(line)]
        if not anchors:
            continue
        low_n = min(n for n, _ in anchors)
        for n, a in anchors:
            if n == low_n:
                p = polarity(a)
                if p:
                    lows[p].append(i)
                break
    if lows["pos"] and lows["neg"]:
        report.add("measurement.scale-consistency", "warning", "Text",
                   f"评分方向不一致：第 {lows['neg'][:5]} 行的低分端是负面，第 {lows['pos'][:5]} 行的低分端是正面。",
                   "全卷统一方向：小数值表示负面，大数值表示正面。", SRC_MEAS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--format", choices=["text", "yaml", "json"], default="text")
    args = ap.parse_args(argv)
    report = Report()
    lint(args.file.read_text(encoding="utf-8"), report)
    report.dump(args.format)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
