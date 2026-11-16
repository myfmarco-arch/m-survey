"""M-survey 脚本共用函数。

只依赖 Python 3.9+、PyYAML 和 jsonschema。
"""
from __future__ import annotations

import json
import re
import sys

sys.dont_write_bytecode = True  # 不在 Skill 目录中留下 __pycache__

from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 PyYAML。请运行：python3 -m pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "questionnaire-spec.schema.json"

SPECIAL_SEMANTICS = {"other", "none", "dont_know", "not_applicable", "refused"}
EXCLUSIVE_SEMANTICS = {"none", "dont_know", "not_applicable", "refused"}
CHOICE_TYPES = {"single", "multi", "ranking"}

# 未解释占位符。管道标记 {{Q5}} / {{item}} 另行检查。
# PLACEHOLDER_RE：中括号占位和英文占位词，任何位置都视为 error。
# DRAFT_WORD_RE：“待定”类词语。题干中视为 error；选项文字中可能是正式选项（例如“还没想好/待定”），视为 warning。
# 中括号占位同时覆盖全角 ⟨…⟩、〈…〉、〔…〕——它们常被用来标记“待替换的内容”。
# 【】是官方问卷格式的标记，不在此列。
PLACEHOLDER_RE = re.compile(r"\b(?:TBD|TODO|XXX)\b|\[[^\]\n]{1,40}\]|[⟨〈〔][^⟩〉〕\n]{1,60}[⟩〉〕]", re.IGNORECASE)
DRAFT_WORD_RE = re.compile(r"待定|待确认|待补")
PIPE_TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_-]*)\s*\}\}")


@dataclass
class Result:
    rule_id: str
    severity: str
    target: str
    message: str
    resolution: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "target": self.target,
            "message": self.message,
            "resolution": self.resolution,
            "source": self.source,
        }


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, *args: str) -> None:
        self.results.append(Result(*args))

    @property
    def errors(self) -> list[Result]:
        return [r for r in self.results if r.severity == "error"]

    def counts(self) -> dict[str, int]:
        out = {"error": 0, "warning": 0, "info": 0}
        for r in self.results:
            out[r.severity] = out.get(r.severity, 0) + 1
        return out

    def dump(self, fmt: str, stream=sys.stdout) -> None:
        if fmt == "yaml":
            yaml.safe_dump(
                [r.as_dict() for r in self.results] or [],
                stream,
                allow_unicode=True,
                sort_keys=False,
                width=1000,
            )
        elif fmt == "json":
            json.dump([r.as_dict() for r in self.results], stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        else:
            order = {"error": 0, "warning": 1, "info": 2}
            for r in sorted(self.results, key=lambda x: order.get(x.severity, 9)):
                stream.write(f"[{r.severity}] {r.rule_id} @ {r.target}\n  {r.message}\n  修复：{r.resolution}\n")
            c = self.counts()
            stream.write(f"\n合计：error {c['error']}，warning {c['warning']}，info {c['info']}\n")


def load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def iter_questions(spec: dict) -> Iterable[tuple[dict, dict]]:
    for section in spec.get("sections", []) or []:
        for q in section.get("questions", []) or []:
            yield section, q


def option_semantic(opt: dict) -> str:
    return opt.get("semantic", "regular")


class SpecIndex:
    """按问卷顺序索引题目，供逻辑检查和渲染使用。"""

    def __init__(self, spec: dict):
        self.spec = spec
        self.order: list[str] = []
        self.questions: dict[str, dict] = {}
        self.section_of: dict[str, dict] = {}
        for section, q in iter_questions(spec):
            qid = q.get("id")
            if qid is None:
                continue
            if qid not in self.questions:
                self.order.append(qid)
                self.questions[qid] = q
                self.section_of[qid] = section

    def position(self, qid: str) -> int:
        try:
            return self.order.index(qid)
        except ValueError:
            return -1

    def option_ids(self, qid: str, include_piped: bool = True) -> set[str]:
        q = self.questions.get(qid, {})
        ids = {o.get("id") for o in q.get("options", []) or []}
        if include_piped and q.get("options_from"):
            src = q["options_from"].get("question")
            if src in self.questions and src != qid:
                ids |= self.option_ids(src, include_piped=True)
        return ids

    def resolved_options(self, qid: str) -> list[dict]:
        """返回题目可见选项：引用来源的普通选项在前，本题选项在后。"""
        q = self.questions.get(qid, {})
        own = list(q.get("options", []) or [])
        if not q.get("options_from"):
            return own
        src = q["options_from"].get("question")
        piped = [o for o in self.resolved_options(src) if option_semantic(o) == "regular"] if src in self.questions else []
        return piped + own


def assign_default_codes(q: dict, other_code: Any = 98, none_code: Any = 99, reserved: Iterable[Any] = ()) -> dict[str, Any]:
    """按官方产品默认编码为选项分配编码。

    已有显式编码优先；普通选项按顺序使用未被占用的 1、2、3……；
    other 默认 98，none 默认 99；不知道、不适用、拒答没有默认值，返回 None。
    reserved 是已被占用的编码，例如引用前题时来源题的编码。
    """
    codes: dict[str, Any] = {}
    used = {o["code"] for o in q.get("options", []) or [] if "code" in o} | set(reserved)
    nxt = 1
    for o in q.get("options", []) or []:
        oid = o.get("id")
        if "code" in o:
            codes[oid] = o["code"]
            continue
        sem = option_semantic(o)
        if sem == "regular":
            while nxt in used:
                nxt += 1
            codes[oid] = nxt
            used.add(nxt)
            nxt += 1
        elif sem == "other":
            codes[oid] = other_code
        elif sem == "none":
            codes[oid] = none_code
        else:
            codes[oid] = None
    return codes


# ------------------------------------------------------------------ 产品配置
class Profile:
    """产品配置：面向受访者的文字、表头、标签和默认编码。

    合同、脚本和 SKILL.md 不写死这些内容，产品目录下的 profile.yaml 决定它们。
    缺少字段时回退到 survey-zh-default，保证旧产品或第三方产品不会因为少写字段而崩。
    """

    FALLBACK_DIR = "references/products/survey-zh-default"

    def __init__(self, data: dict, path: Path | None = None):
        self.data = data or {}
        self.path = path
        self.id = self.data.get("id") or "unknown"
        self.language = self.data.get("language") or "zh-CN"

    # --- 取字段
    class Missing(Exception):
        """产品配置缺必需字段。宁可报错，也不要静默退回另一种语言。"""

    def _require(self, section: str, key: str):
        node = self.data.get(section) or {}
        if key not in node:
            raise Profile.Missing(f"产品 {self.id} 的 profile.yaml 缺少 {section}.{key}")
        return node[key]

    def codes(self) -> dict[str, int | str]:
        return {k: self._require("codes", k) for k in ("other", "none")}

    def table(self, kind: str) -> list[str]:
        return list(self._require("tables", kind))

    def type_label(self, rtype: str, has_scale: bool = False) -> str:
        key = ("matrix_scale" if has_scale else "matrix_choice") if rtype == "matrix" else rtype
        return self._require("type_labels", key)

    def token(self, key: str, default: str | None = None, **kwargs) -> str:
        """取产品文字模板。

        产品自己声明了 tokens 时，缺 key 直接报错（避免静默显示成空或另一种语言）；
        只有在检查工具按“未知 key”探测时才用 default。
        """
        tokens = self.data.get("tokens") or {}
        if key in tokens:
            raw = tokens[key]
        elif default is not None:
            raw = default
        else:
            raise Profile.Missing(f"产品 {self.id} 的 profile.yaml 缺少 tokens.{key}")
        if not kwargs:
            return raw
        try:
            return raw.format(**kwargs)
        except (KeyError, IndexError):
            return raw

    def token_prefix(self, key: str, default: str | None = None) -> str:
        """模板第一个占位符之前的固定文字，用于识别“引用…”“loop over…”这类前缀。"""
        raw = self.token(key) if default is None else self.token(key, default)
        return raw.split("{")[0]

    def heading(self, key: str, default: str | None = None, **kwargs) -> str:
        raw = self._require("headings", key) if default is None else \
            (self.data.get("headings") or {}).get(key, default)
        try:
            return raw.format(**kwargs)
        except (KeyError, IndexError):
            return raw

    def separator(self, key: str, default: str | None = None) -> str:
        return self._require("separators", key) if default is None else \
            (self.data.get("separators") or {}).get(key, default)

    def appendices(self) -> list[str]:
        return list(self.data.get("appendices") or [])


def _load_fallback_profile() -> Profile:
    """默认产品配置优先读磁盘上的 profile.yaml；文件不存在时用最小内置值。"""
    path = ROOT / "references" / "products" / "survey-zh-default" / "profile.yaml"
    if path.exists():
        return Profile(load_yaml(path), path)
    return Profile({"id": "survey-zh-default", "language": "zh-CN",
                    "codes": {"other": 98, "none": 99}})


ZH_PROFILE = _load_fallback_profile()


def load_profile(path: Path) -> Profile:
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是有效的产品配置")
    return Profile(data, path)


# ------------------------------------------------------------------ 产品注册表
def product_registry() -> tuple[str, dict]:
    """读取产品注册表，返回 (默认产品 id, 产品表)。

    product.yaml 是上游文件；local.yaml 中的 products 在其之上合并，同名以 local.yaml 为准。
    """
    data = load_yaml(ROOT / "product.yaml")
    products = {str(k): (v or {}) for k, v in (data.get("products") or {}).items()}
    default_id = str(data.get("default_product") or data.get("product") or "survey-zh-default")
    local = ROOT / "local.yaml"
    if local.exists():
        local_data = load_yaml(local) or {}
        for key, value in (local_data.get("products") or {}).items():
            products[str(key)] = {**products.get(str(key), {}), **(value or {})}
    return default_id, products


def current_product() -> str:
    """生效的产品 id：local.yaml 的 product 优先，其次 product.yaml 的 product / default_product。"""
    local = ROOT / "local.yaml"
    if local.exists():
        data = load_yaml(local) or {}
        if isinstance(data, dict) and data.get("product"):
            return str(data["product"])
    default_id, _ = product_registry()
    return default_id


def product_files(product_id: str) -> dict[str, str]:
    """产品提供的文件。

    来源按优先级：产品自己的 profile.yaml 中 files 块 → product.yaml 中该产品的登记 → 默认产品。
    只保留实际存在的文件，缺失的键继续向下回退。
    """
    default_id, products = product_registry()
    resolved: dict[str, str] = {}
    for source in (products.get(default_id) or {}, products.get(product_id) or {}):
        resolved.update({k: str(v) for k, v in source.items()})
    # profile 必须优先解析，才能读到它自己声明的 files
    _, registry_products = product_registry()
    profile_rel = (registry_products.get(product_id) or {}).get("profile") or \
        (registry_products.get(default_id) or {}).get("profile")
    if profile_rel and (ROOT / profile_rel).exists():
        local = (load_yaml(ROOT / profile_rel) or {}).get("files") or {}
        base_dir = (ROOT / profile_rel).parent
        for key, rel_file in local.items():
            resolved[key] = str((base_dir / rel_file).relative_to(ROOT))
    return {k: v for k, v in resolved.items() if (ROOT / v).exists()}


def product_profile(product_id: str | None = None) -> Profile:
    """按 id 取产品配置。显式传入未注册的 id 时报错，而不是静默退回中文产品。"""
    pid = product_id or current_product()
    _, products = product_registry()
    if product_id is not None and pid not in products:
        raise Profile.Missing(f"未注册的产品 {pid}。在 product.yaml 的 products 或 local.yaml 的 products 中登记。")
    files = product_files(pid)
    rel = files.get("profile")
    if not rel or not (ROOT / rel).exists():
        raise Profile.Missing(f"产品 {pid} 没有可用的 profile.yaml")
    return load_profile(ROOT / rel)


# ------------------------------------------------------------------ 文本残留与数值区间
# 表格公式错误和删除线是从在线文档、表格导出问卷时最常见的残留。
RESIDUE_RE = re.compile(r"#(?:VALUE|REF|N/A|DIV/0|NAME\?|NUM|NULL)!?|~~")

_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(岁|天|日|周|个月|月|年|次|笔|分钟|小时|元|块|个|张|部|台|款|分|days?|weeks?|months?|years?|times?|hours?|minutes?)"
# 顺序重要：先匹配半开区间（“A 至不到 B”），再匹配闭区间（“A–B”）
_HALF_OPEN_RE = re.compile(_NUM + r"\s*" + _UNIT + r"?\s*(?:至|到)\s*不到\s*" + _NUM + r"\s*" + _UNIT)
_CLOSED_RE = re.compile(_NUM + r"\s*" + _UNIT + r"?\s*(?:-|–|—|~|～|至|到)\s*" + _NUM + r"\s*" + _UNIT)


def parse_range(text: str):
    """从选项文字中取出数值区间，返回 (下限, 上限, 单位, 含下限, 含上限)；取不到时返回 None。

    只识别带单位的区间，例如“7–15 天”“1 年至不到 3 年”“1 个月到 3 个月（含 3 个月）”。
    “及以上”“以下”这类单边区间不参与比较。
    """
    t = (text or "").replace("，", ",")
    m = _HALF_OPEN_RE.search(t)
    if m:
        lo, u1, hi, u2 = m.groups()
        if u1 and u1 != u2:
            return None
        return float(lo), float(hi), u2, True, False
    m = _CLOSED_RE.search(t)
    if not m:
        return None
    lo, u1, hi, u2 = m.groups()
    if u1 and u1 != u2:
        return None
    lo_inc, hi_inc = True, True
    rest = t[m.end():]
    if re.search(r"不含\s*" + re.escape(hi), rest):
        hi_inc = False
    elif re.search(r"(?<!不)含\s*" + re.escape(hi), rest):
        lo_inc = False  # 写明“含上限”，通常表示不含下限，例如“1 个月到 3 个月（含 3 个月）”
    return float(lo), float(hi), u2, lo_inc, hi_inc


def range_overlaps(texts: list[str]) -> list[tuple[str, str]]:
    """同一单位的区间两两比较，返回边界重叠的选项文字对。相同文字只算一次。"""
    seen: set[str] = set()
    parsed = []
    for t in texts:
        key = norm_text(t)
        if key in seen:
            continue
        seen.add(key)
        r = parse_range(t)
        if r:
            parsed.append((t, r))
    out = []
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            (ta, a), (tb, b) = parsed[i], parsed[j]
            if a[2] != b[2]:
                continue
            first, second = (a, b) if (a[0], not a[3]) <= (b[0], not b[3]) else (b, a)
            # first 在左；second 的下限落在 first 内部，或两者在同一端点都包含
            if second[0] < first[1] or (second[0] == first[1] and first[4] and second[3]):
                out.append((ta, tb))
    return out


def norm_text(text: str) -> str:
    """比较列表用：去掉空白和标点。"""
    return re.sub(r"[\s，,。．.、；;：:！!？?“”\"'‘’（）()【】\[\]/／]+", "", text or "")


def core_text(text: str) -> str:
    """去掉括号内的补充说明后再规范化，例如“系统稳定性（闪退、死机）”→“系统稳定性”。"""
    return norm_text(re.sub(r"[（(][^）)]*[）)]", "", text or ""))


# ------------------------------------------------------------------ 时长估算
TIMING_PATH = ROOT / "references" / "modules" / "knowledge" / "timing-parameters.yaml"


def load_timing(path: Path | None = None) -> dict:
    data = load_yaml(path or TIMING_PATH)
    if not isinstance(data, dict) or "answer_seconds" not in data or "reading" not in data:
        raise ValueError(f"{path or TIMING_PATH} 不是有效的时长参数文件")
    return data


def text_units(text: str, language: str) -> float:
    """中文按字计，其他语言按词计。"""
    text = PIPE_TOKEN_RE.sub("", text or "")
    if language.lower().startswith(("zh", "ja", "ko")):
        return float(len(re.sub(r"\s", "", text)))
    return float(len(re.findall(r"[A-Za-z0-9']+", text)))


def question_text(idx: "SpecIndex", qid: str) -> str:
    q = idx.questions[qid]
    parts = [q.get("prompt", "")]
    parts += [o.get("text", "") for o in idx.resolved_options(qid)]
    parts += [r.get("text", "") for r in q.get("rows", []) or []]
    sc = q.get("scale") or {}
    parts += [sc.get("low", ""), sc.get("high", ""), sc.get("mid", "")]
    return " ".join(p for p in parts if p)


def estimate_duration(spec: dict, params: dict | None = None) -> dict:
    """按题估算阅读加作答时间，返回典型路径、最长路径和每题明细（秒）。

    典型路径 = Σ 每题秒数 × 预计看到的比例 × 预计循环次数；最长路径假设全部显示、循环取最大次数。
    没有填写 expected_share / expected_loops 的题目使用参数文件中的默认值，并记录在 defaults_used 中。
    """
    params = params or load_timing()
    language = (spec.get("meta") or {}).get("language", "zh-CN")
    reading = params["reading"]
    rate = reading["chars_per_minute"] if language.lower().startswith(("zh", "ja", "ko")) else reading["words_per_minute"]
    ans = params["answer_seconds"]
    defaults = params.get("defaults") or {}
    factor = float((params.get("calibration") or {}).get("factor", 1.0))
    idx = SpecIndex(spec)
    rows, defaults_used = [], []
    for qid in idx.order:
        q = idx.questions[qid]
        rules = q.get("response_rules") or {}
        if rules.get("hidden"):
            continue
        rtype = q.get("response_type")
        read_s = text_units(question_text(idx, qid), language) / rate * 60
        if rtype == "matrix":
            act = ans["matrix_row"] * len(q.get("rows", []) or [])
        elif rtype == "open_text":
            act = ans["open_text_required"] if rules.get("required", True) else ans["open_text_optional"]
        elif rtype == "ranking":
            n = rules.get("rank_count") or len([o for o in idx.resolved_options(qid) if option_semantic(o) == "regular"])
            act = ans["ranking_per_item"] * n
        else:
            act = ans.get(rtype, 0)
        secs = read_s + act
        section = idx.section_of[qid]
        if "expected_share" in q:
            share = float(q["expected_share"])
        elif q.get("display_logic") and section.get("role") != "screening":
            share = float(defaults.get("conditional_share", 0.5))
            defaults_used.append(f"{qid}：预计看到比例取默认值 {share:g}")
        else:
            share = 1.0
        loops_typ = loops_max = 1.0
        if q.get("loop_over"):
            src = q["loop_over"]["question"]
            loops_max = float(len([o for o in idx.resolved_options(src) if option_semantic(o) == "regular"]) or 1)
            if "expected_loops" in q:
                loops_typ = float(q["expected_loops"])
            else:
                loops_typ = min(float(defaults.get("loop_count", 2)), loops_max)
                defaults_used.append(f"{qid}：预计循环次数取默认值 {loops_typ:g}")
        rows.append({"id": qid, "label": q.get("label", ""), "seconds": round(secs * factor, 1),
                     "typical": round(secs * share * loops_typ * factor, 1),
                     "max": round(secs * loops_max * factor, 1), "share": share, "loops": loops_typ})
    typical = sum(r["typical"] for r in rows)
    longest = sum(r["max"] for r in rows)
    return {
        "typical_minutes": round(typical / 60, 1),
        "max_minutes": round(longest / 60, 1),
        "questions": rows,
        "defaults_used": defaults_used,
        "parameter_status": params.get("status", "unknown"),
        "calibration": params.get("calibration") or {},
    }
