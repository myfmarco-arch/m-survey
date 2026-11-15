"""0.6.0 新增能力的回归测试：题序、选项来源、数据质量、受访负担、跨波对比、宽松检查和质量评测。"""
from __future__ import annotations

import copy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_render  # noqa: E402
import diff_waves  # noqa: E402
import lint_text  # noqa: E402
import render_markdown  # noqa: E402
import run_evals  # noqa: E402
import validate_spec  # noqa: E402
from spec_lib import Report, estimate_duration, load_yaml, parse_range, range_overlaps  # noqa: E402

EXAMPLE = ROOT / "examples" / "expense-app-autocat" / "spec.yaml"


def find_q(spec: dict, qid: str) -> dict:
    for s in spec["sections"]:
        for q in s["questions"]:
            if q["id"] == qid:
                return q
    raise KeyError(qid)


def results(spec: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in validate_spec.validate(spec).results:
        out.setdefault(r.rule_id, []).append(r)
    return out


class RangeTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_range("7-15天")[:3], (7.0, 15.0, "天"))
        self.assertEqual(parse_range("1 年至不到 3 年")[3:], (True, False))
        self.assertEqual(parse_range("1个月到3个月（含3个月）")[3:], (False, True))
        self.assertIsNone(parse_range("30天以上"))
        self.assertIsNone(parse_range("3 个月至不到 1 年"))  # 单位不同，不比较

    def test_overlaps(self):
        self.assertEqual(range_overlaps(["7-15天", "15-30天"]), [("7-15天", "15-30天")])
        self.assertEqual(range_overlaps(["18–24 岁", "25–34 岁"]), [])
        self.assertEqual(range_overlaps(["1 年至不到 3 年", "3 年至不到 5 年"]), [])
        self.assertEqual(range_overlaps(["1个月到3个月（含3个月）", "3个月到6个月（含6个月）"]), [])
        self.assertEqual(range_overlaps(["1-2次", "1-2次"]), [])  # 相同文字只算一次


class ValidateNewRulesTest(unittest.TestCase):
    def setUp(self):
        self.base = load_yaml(EXAMPLE)

    def spec(self):
        return copy.deepcopy(self.base)

    def test_example_still_clean(self):
        self.assertEqual(results(self.base), {})

    def test_option_source_required_for_multi(self):
        s = self.spec()
        del find_q(s, "Q5")["option_source"]
        self.assertIn("measurement.option-source", results(s))

    def test_drafted_source_is_info(self):
        s = self.spec()
        find_q(s, "Q5")["option_source"] = {"type": "drafted"}
        r = results(s)["measurement.option-source"]
        self.assertEqual(r[0].severity, "info")

    def test_range_overlap(self):
        s = self.spec()
        find_q(s, "S3")["options"][2]["text"] = "10–30 笔"
        self.assertIn("spec.range-overlap", results(s))

    def test_text_residue(self):
        s = self.spec()
        find_q(s, "Q5")["options"][0]["text"] = "#VALUE!"
        self.assertIn("spec.text-residue", results(s))

    def test_reason_list_before_matching_matrix(self):
        s = self.spec()
        q4 = find_q(s, "Q4")
        reason = {
            "id": "Q3b", "label": "低分方面", "purpose": {"type": "research_question", "refs": ["RQ2"]},
            "construct": "reason", "prompt": "哪些方面让您不满意？", "response_type": "multi",
            "option_source": {"type": "prior_wave"},
            "options": [{"id": f"o{i}", "text": r["text"]} for i, r in enumerate(q4["rows"], 1)],
        }
        section = s["sections"][1]["questions"]
        section.insert(section.index(q4), reason)
        self.assertIn("measurement.order-rating-before-reason", results(s))

    def test_panel_needs_attention_check(self):
        s = self.spec()
        s["meta"]["channel"] = "panel"
        self.assertIn("quality.attention-check", results(s))
        # 加一道指令题后通过
        s["sections"][1]["questions"].append({
            "id": "QC1", "label": "注意力检测", "purpose": {"type": "quality_control"}, "construct": "other",
            "prompt": "为确认您在认真阅读，本题请选择“比较同意”。", "response_type": "single",
            "options": [{"id": "o1", "text": "非常不同意"}, {"id": "o2", "text": "比较同意"}],
            "quality": {"role": "instructed_response", "pass": ["o2"], "action": "terminate"},
        })
        self.assertNotIn("quality.attention-check", results(s))

    def test_quality_pass_must_exist(self):
        s = self.spec()
        find_q(s, "Q1")["quality"] = {"role": "instructed_response", "pass": ["o9"], "action": "flag"}
        self.assertIn("spec.logic-option-reference", results(s))

    def test_cleaning_rules_required(self):
        s = self.spec()
        del s["quality"]
        self.assertIn("quality.cleaning-rules", results(s))

    def test_matrix_size(self):
        s = self.spec()
        find_q(s, "Q4")["rows"] = [{"id": f"r{i}", "text": f"方面 {i}"} for i in range(1, 13)]
        self.assertIn("burden.matrix-size", results(s))

    def test_over_target_and_unsupported_duration(self):
        s = self.spec()
        s["meta"]["target_minutes"] = 1
        s["meta"]["estimated_minutes"] = 0.5
        r = results(s)
        self.assertIn("burden.over-target", r)
        self.assertIn("burden.unsupported-duration", r)


class EstimateTest(unittest.TestCase):
    def test_example_estimate(self):
        est = estimate_duration(load_yaml(EXAMPLE))
        self.assertGreater(est["typical_minutes"], 0)
        self.assertGreaterEqual(est["max_minutes"], est["typical_minutes"])
        self.assertEqual(est["defaults_used"], [])  # 示例为每道条件题写了 expected_share

    def test_defaults_reported(self):
        spec = load_yaml(EXAMPLE)
        del find_q(spec, "Q3")["expected_share"]
        est = estimate_duration(spec)
        self.assertTrue(any(x.startswith("Q3") for x in est["defaults_used"]))

    def test_hidden_question_costs_nothing(self):
        spec = load_yaml(EXAMPLE)
        find_q(spec, "D1").setdefault("response_rules", {})["hidden"] = True
        ids = [q["id"] for q in estimate_duration(spec)["questions"]]
        self.assertNotIn("D1", ids)

    def test_cli(self):
        out = subprocess.run([sys.executable, "scripts/estimate_duration.py", str(EXAMPLE)], cwd=ROOT,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("典型路径", out.stdout)


class RenderNewFeaturesTest(unittest.TestCase):
    def test_tags_quality_and_appendices(self):
        spec = load_yaml(EXAMPLE)
        find_q(spec, "Q1")["quality"] = {"role": "instructed_response", "pass": ["o1"], "action": "flag"}
        r = render_markdown.Renderer(spec, "default")
        md = r.render()
        self.assertIn("维度：准确性", md)
        self.assertIn("质量控制：正确答案为 1；答错者标记复核", md)
        self.assertNotIn("## 清洗规则", md)  # 清洗规则属于研究简报与方案
        self.assertIn("| C1 |", r.cleaning_table_text())
        # 题目设计表属于研究简报与方案，不进问卷文件
        self.assertNotIn("题目设计表", md)
        table = r.design_table_text()
        self.assertIn("| 题号 | 标签 | 研究问题 |", table)
        self.assertIn("客服与反馈", table)
        report = Report()
        qs = check_render.check(md, report, render_markdown.ZH_PROFILE)
        check_render.compare(qs, spec, "default", report)
        self.assertEqual([r.as_dict() for r in report.results], [])

    def test_english_product_renders_new_features(self):
        from spec_lib import product_profile
        spec = load_yaml(EXAMPLE)
        profile = product_profile("survey-en-minimal")
        r = render_markdown.Renderer(spec, "default", profile=profile)
        md = r.render()
        self.assertIn("dimension: ", md)
        self.assertIn("| Question | Label |", r.design_table_text())
        self.assertIn("| ID | Condition | Action | Basis |", r.cleaning_table_text())
        self.assertNotIn("清洗规则", md)


class DiffWavesTest(unittest.TestCase):
    def setUp(self):
        self.old = load_yaml(EXAMPLE)

    def status(self, new, qid):
        _, rows = diff_waves.compare(self.old, new)
        return next(r["status"] for r in rows if r["new"] == qid)

    def test_identical_is_comparable(self):
        report, rows = diff_waves.compare(self.old, copy.deepcopy(self.old))
        self.assertEqual(report.results, [])
        self.assertTrue(all(r["status"] == "可比" for r in rows))

    def test_scale_change_not_comparable(self):
        new = copy.deepcopy(self.old)
        find_q(new, "Q3")["scale"] = {"min": 1, "max": 5, "low": "非常不满意", "high": "非常满意"}
        self.assertEqual(self.status(new, "Q3"), "不可比")

    def test_inserted_option_shifts_default_codes(self):
        new = copy.deepcopy(self.old)
        find_q(new, "Q5")["options"].insert(0, {"id": "o0", "text": "识别速度慢"})
        report, _ = diff_waves.compare(self.old, new)
        self.assertIn("tracking.code-meaning-changed", {r.rule_id for r in report.results})

    def test_wording_change_needs_note(self):
        new = copy.deepcopy(self.old)
        find_q(new, "Q1")["prompt"] += "请根据实际情况回答。"
        self.assertEqual(self.status(new, "Q1"), "需加注")

    def test_mapping(self):
        new = copy.deepcopy(self.old)
        find_q(new, "Q9")["id"] = "Q10"
        _, rows = diff_waves.compare(self.old, new, {"Q9": "Q10"})
        self.assertEqual(next(r["status"] for r in rows if r["old"] == "Q9"), "可比")


class LintTextTest(unittest.TestCase):
    TEXT = """### Q1. 您的年龄是？
- 18-24岁
- 25-34岁
### Q2. 您更新多长时间了？
- 7-15天
- 15-30天
### Q3. 请为界面 A 打分
1分=非常不喜欢，10分=非常喜欢
### Q4. 请为以下维度打分【Q9=1】
1分=非常好；10分=非常差
### Q5. 图片
#VALUE!
### Q2. 重复题号
- 是
- 否
### Q6. 其他
- 是
"""

    def test_lint_finds_known_problems(self):
        report = Report()
        lint_text.lint(self.TEXT, report)
        ids = {r.rule_id for r in report.results}
        self.assertEqual(ids, {"spec.text-residue", "spec.range-overlap", "measurement.scale-consistency",
                               "spec.id-unique", "spec.logic-reference"})


class QualityEvalTest(unittest.TestCase):
    def test_dimensions(self):
        self.assertEqual(len(run_evals.rubric_dimensions()), 8)

    def test_blind_order_is_deterministic_and_complete(self):
        a = run_evals.blind_order(["skill", "baseline", "reference"], "c", "run-1", "s")
        b = run_evals.blind_order(["skill", "baseline", "reference"], "c", "run-1", "s")
        self.assertEqual(a, b)
        self.assertEqual(sorted(a.values()), ["baseline", "reference", "skill"])
        self.assertEqual(sorted(a), ["A", "B", "C"])

    def test_judge_prompt_hides_conditions(self):
        case = {"id": "x", "request": "设计问卷", "fixtures": []}
        p = run_evals.quality_judge_prompt(case, {"A": "甲问卷", "B": "乙问卷"})
        self.assertIn("交付物 A", p)
        self.assertNotIn("baseline", p)
        self.assertNotIn("skill", p.lower())

    def test_validate_judgement(self):
        dims = run_evals.rubric_dimensions()
        good = {"scores": {l: {d: {"score": 3, "evidence": "e"} for d in dims} for l in "AB"}, "ranking": ["B", "A"]}
        self.assertEqual(run_evals.validate_quality_judgement(good, ["A", "B"], dims), "")
        bad = copy.deepcopy(good)
        bad["scores"]["A"][dims[0]]["score"] = 6
        self.assertNotEqual(run_evals.validate_quality_judgement(bad, ["A", "B"], dims), "")
        bad = copy.deepcopy(good)
        bad["ranking"] = ["A"]
        self.assertNotEqual(run_evals.validate_quality_judgement(bad, ["A", "B"], dims), "")

    def test_aggregate(self):
        dims = ["d1", "d2"]
        recs = [{"case": "c", "run": "run-1", "scores": {"skill": {"d1": 4, "d2": 5}, "baseline": {"d1": 3, "d2": 3}},
                 "rank": ["skill", "baseline"]},
                {"case": "c", "run": "run-2", "scores": {"skill": {"d1": 3, "d2": 3}, "baseline": {"d1": 3, "d2": 3}},
                 "rank": ["baseline", "skill"]}]
        agg = run_evals.q_aggregate(recs, dims)
        self.assertEqual(agg["delta_skill_minus_baseline"]["d2"], 1.0)
        self.assertEqual(agg["skill_vs_baseline"], {"wins": 1, "ties": 1, "losses": 0})
        self.assertEqual(agg["ranked_first"], {"skill": 1, "baseline": 1})

    def test_prepare_with_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "ref"
            ref.mkdir()
            (ref / "os-beta-first-month.md").write_text("人工版本", encoding="utf-8")
            out = Path(tmp) / "out"
            args = type("A", (), {"out": str(out), "runs": 1, "case": ["os-beta-first-month"], "conditions": None,
                                  "reference_dir": str(ref), "seed": "s"})()
            run_evals.q_prepare(args)
            run_dir = out / "quality" / "os-beta-first-month" / "run-1"
            self.assertTrue((run_dir / "reference" / "response.md").exists())
            self.assertTrue((run_dir / "skill" / "prompt.md").exists())
            self.assertTrue((run_dir / "baseline" / "prompt.md").exists())


class CheckRepoQualityTest(unittest.TestCase):
    def test_unknown_focus_dimension(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "repo"
            shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "runs", "__pycache__"))
            p = dst / "evals" / "quality" / "cases.yaml"
            p.write_text(p.read_text(encoding="utf-8").replace("focus: [decision,", "focus: [nonsense,"), encoding="utf-8")
            out = subprocess.run([sys.executable, "scripts/check_repo.py"], cwd=dst, capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("nonsense", out.stdout)


if __name__ == "__main__":
    unittest.main()


class TwoDocumentsTest(unittest.TestCase):
    def test_design_table_cli_writes_separate_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            q, d = Path(tmp) / "问卷.md", Path(tmp) / "design.md"
            c = Path(tmp) / "cleaning.md"
            out = subprocess.run([sys.executable, "scripts/render_markdown.py", str(EXAMPLE), "-o", str(q),
                                  "--codes", "default",
                                  "--design-table", str(d), "--cleaning-rules", str(c)],
                                 cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            qtext = q.read_text(encoding="utf-8")
            self.assertNotIn("题目设计表", qtext)
            self.assertNotIn("清洗规则", qtext)
            self.assertIn("| 题号 |", d.read_text(encoding="utf-8"))
            self.assertIn("| C1 |", c.read_text(encoding="utf-8"))

    def test_templates_define_two_files(self):
        text = (ROOT / "references/products/survey-zh-default/templates.md").read_text(encoding="utf-8")
        for section in ("## 研究简报与方案", "## 问卷", "一、研究目标", "六、后续建议"):
            self.assertIn(section, text)
        self.assertIn("format.two-documents", text)
        self.assertIn("format.brief-concise", text)
        # 问卷模板里只有卷首语和正文
        q = text.split("## 问卷", 1)[1]
        self.assertNotIn("## 清洗规则", q)

    def test_example_ships_two_files(self):
        folder = ROOT / "examples" / "expense-app-autocat"
        self.assertTrue((folder / "02-research-plan.md").exists())
        self.assertTrue((folder / "03-questionnaire.md").exists())
        self.assertNotIn("## 研究简报", (folder / "03-questionnaire.md").read_text(encoding="utf-8"))

