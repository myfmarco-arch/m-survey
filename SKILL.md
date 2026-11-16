---
name: m-survey
description: 设计、修改和审核中文定量用户研究问卷，并提供定量方法咨询。从业务决策出发选择方法、规划样本，写出题序不污染、选项有来源、带质量控制和时长估算、可直接投放和分析的问卷；也能审核从其他工具导出的问卷，检查跨波次可比性。适用于满意度与体验诊断、版本上线和卖点复盘、购买与价格研究、需求优先级（KANO、MaxDiff、联合分析）、品牌健康追踪、概念和视觉测试、命名研究和用户招募甄别；不用于普通报名表、纯定性访谈大纲、已回收数据的清洗与统计分析或问卷平台编程。
license: MIT
metadata:
  version: 0.6.0
  contract: m-survey-contract-v1
---

# M-survey

从业务决策出发，写出资深研究负责人认可的问卷：每道题有用途，题序不污染，选项有来源，数据可信，时长属实，编程可以直接实现。

## 运行起点

只做两步就可以开口：

1. 读取 [产品清单](product.yaml)。根目录存在 `local.yaml` 时一并读取，它覆盖产品选择并追加 overlay 和验证。确定当前产品、启用的 overlay 和验证清单。启用了 overlay 时，在第一次回复中用一句话说明生效的 overlay `id` 和当前产品。
2. 按 [任务路由](references/services/task-routing.md) 判断工作模式：`create` 从零设计、`revise` 修改、`audit` 审核、`consult` 方法咨询。

之后按“按需读取”表读取文件。每项只在实际需要时读取，不要一次读完。

## 写好问卷的底线

不读任何文件也要做到。细节见 [题目工艺](references/modules/knowledge/question-craft.md)。

1. **每道题有用途。** 说得出它回答哪个研究问题、看什么指标、和什么分组交叉。说不出就删。
2. **题序不污染。** 总体先于细项；评价先于功能介绍、卖点、概念和价格曝光；无提示先于提示；评分先于原因，原因列表不提前出现。
3. **选项有来源。** 封闭列表优先来自上一波问卷、问题清单、舆情、客服分类、埋点或定性研究。自拟的列表写进需确认项，请需求方校准。
4. **用受访者的话。** 不用宣传文案和内部术语；一题只问一件事；版本、型号、使用时长等易错事实给出核验方式。
5. **数据可信。** 按投放渠道设置甄别排除、问卷内检测和回收前固定的清洗规则。
6. **时长属实。** 估算典型路径和最长路径；卷首语承诺的时长与估算一致；超时时给出删减清单。
7. **证据不越界。** 只让经历过的人评价体验；不把态度当行为、相关当因果、便利样本当总体；不把工作译文包装成正式量表。
8. **追踪可比。** 与上一波比较前先拿到原问卷，列出可比、需加注和不可比的题目。
9. **交付分两份，都短。** 研究简报与方案给需求方，问卷给编程和平台，各自内容见下文“交付”。两份都不写验证记录、规则标识、假设清单和方法教程。

## 工作模式

- **从零设计**：研究简报 → 方法方案 → 问卷规格 → 最终问卷。用户要求样本量、配额或样本框架时，另外形成样本方案。
- **修改问卷**：优先保留现有题号、语义、逻辑和编码，只修改与目标有关的内容，并说明跨波可比性影响。
- **审核问卷**：先输出问题、严重程度和修改建议；用户未要求时不重写全文。除逐题检查外，还要看整卷的题序、选项来源、质量控制、时长和可比性。
- **方法咨询**：说明首选方法、成立前提、替代方案和结论边界，不强制生成问卷。

## 按需读取

| 需要做什么 | 读取 |
|---|---|
| 写题、排题序、写选项、设计刺激物 | [题目工艺](references/modules/knowledge/question-craft.md) |
| 写完整问卷：措辞、格式、模板、编码 | 当前产品的撰写规范、问卷格式、模板和默认编码（官方产品见 [撰写规范](references/products/survey-zh-default/writing.md)、[问卷格式](references/products/survey-zh-default/questionnaire-format.md)、[模板](references/products/survey-zh-default/templates.md)、[默认编码](references/products/survey-zh-default/coding.md)） |
| 参考同类问卷的结构和常见错误 | [案例索引](references/products/survey-zh-default/cases/index.md)，默认只读一份 |
| 澄清需求、判断信息是否足够 | [澄清问题](references/modules/knowledge/clarification-questions.md)、当前产品的 [工作流](references/products/survey-zh-default/workflow.md)（首轮提问上限） |
| 追问条件主题或执行约束 | [条件追问与执行约束](references/modules/knowledge/clarification-probes.md) |
| 选择方法 | [方法选择服务](references/services/method-selection.md)、[方法目录](references/modules/methods/catalog.md) |
| 使用标准量表或标准问法 | [标准问法](references/modules/methods/standard-items.md)、[题库](references/modules/knowledge/question-bank.csv)、[来源](references/modules/methods/sources.md) |
| 特殊方法（KANO、MaxDiff、联合分析、价格研究、品牌追踪） | [方法索引](references/modules/methods/index.md) 指向的单个方法文件 |
| 样本量或配额 | [样本规划](references/services/sample-planning.md)、[样本完整性](references/services/validation/sampling-integrity.md) |
| 甄别排除、注意力检测、清洗规则 | [数据质量控制](references/services/validation/data-quality.md) |
| 时长估算和手机端负担 | [受访负担](references/services/validation/respondent-burden.md) |
| 与上一波或历史结果比较 | [跨波次可比性](references/services/validation/tracking-comparability.md) |
| 隐私、敏感信息、未成年人或跨境 | [隐私基线](references/services/validation/privacy-baseline.md) |
| 写问卷规格或审核报告 | [研究产物合同](references/contracts/artifacts.md)、[验证合同](references/contracts/validation-contract.md)、[规格结构完整性](references/services/validation/spec-integrity.md) |
| Codebook 或 SPSS 配置 | [Codebook 适配器](references/adapters/codebook.md)、[SPSS 适配器](references/adapters/spss.md) |

表中的产品文件可能已被 overlay 替换或扩展，以第 1 步的解析结果为准。

## 交付

- 交付分两份文件：**研究简报与方案**（给需求方和研究负责人：一屏简报、研究目标、方法方案、样本方案、题目设计表、需确认项、后续建议）和**问卷**（给编程同学和平台：只有卷首语和正文）。只做方案时不写第二份。格式见当前产品的模板。
- 简报要简练：表格最多 6 行，每格一句话，只写结论。各节只写必须有的内容。
- 不为求全而罗列不采用的方法。用户或需求方点名了某个方法，或需求措辞容易被误读成另一种方法时，才用一两句说明为什么不采用。
- 优先使用用户已经提供的信息。只询问会改变方法、样本、核心结构或选项来源的未知信息；非关键缺口用显式假设。
- 需确认项只列问卷本身还没定的事项，每项一句并写明谁来确认。
- 验证规则标识只出现在审核报告中，交付物里用中文说明问题。
- 最终正文不保留未解释占位符。不将案例和示例中的品牌、产品、样本数、阈值或项目事实复制到新项目。

## 验证严重程度

| 内部值 | 用户可见 | 交付行为 |
|---|---|---|
| `error` | 严重 | 停止交付可投放版本 |
| `warning` | 重要 | 可继续，在交付物外说明限制 |
| `info` | 建议 | 按任务需要报告 |

以下情形直接返回 `error`：关键输入缺失且会改变方法、样本或核心结构；方法前提不成立；问卷逻辑使题目无法作答或分析；声称使用无法核验的正式量表、译本、常模或许可；已知隐私、伦理或安全条件未满足却要求交付可投放版本。

交付前按 `product.yaml` 的 `validation` 清单执行：`always` 每次执行，`when` 的触发条件成立时执行。`error` 未消除时，不交付可投放版本。

## 可选的脚本检查

有代码执行环境时使用。脚本位于本 Skill 目录（`SKILL.md` 所在目录，下文记为 `<skill>`）的 `scripts/` 中，用绝对路径调用。没有代码执行环境时，由模型按对应规则逐项检查。

1. 照 [完整示例](examples/expense-app-autocat/spec.yaml) 把问卷写成 QuestionnaireSpec YAML，写明 `meta.channel`、`purpose.analysis`、`option_source` 和 `quality.cleaning_rules`。`validate_spec.py` 报 `spec.schema` 错误时，再查 [schema](schemas/questionnaire-spec.schema.json)。
2. `python <skill>/scripts/validate_spec.py spec.yaml`：修复全部 `error`，逐条处理 `warning`。
3. `python <skill>/scripts/estimate_duration.py spec.yaml`：得到典型路径和最长路径，写进简报和卷首语。
4. `python <skill>/scripts/render_markdown.py spec.yaml --codes <参数> -o questionnaire.md`；题目设计表和清洗规则用 `--design-table design.md --cleaning-rules cleaning.md` 单独写出，贴进研究简报与方案。编码参数：官方默认编码且没有已回收数据用 `default`；已回收问卷或 spec 写明全部编码用 `explicit`；平台生成编码用 `ids`。手写问卷时改用 `check_render.py questionnaire.md --spec spec.yaml --codes <参数>`。
5. 与上一波比较时：`python <skill>/scripts/diff_waves.py previous.yaml spec.yaml`。
6. 审核从其他工具导出的问卷时：`python <skill>/scripts/lint_text.py questionnaire.md`。

问卷格式被 overlay 替换时，跳过第 4 步，按 overlay 的格式手写问卷。脚本只检查结构、逻辑和可计算的规则，不判断方法前提、证据边界、题序之外的污染和隐私风险。中间 YAML 和脚本输出不放入最终问卷正文。

## 规则合并

```text
研究事实和已有数据合同
> 用户对当前任务的明确要求
> 启用的 overlay（按列表顺序，后者优先）
> 官方产品配置
> 方法和适配器默认值
> 案例与示例
```

上层选择不得伪造证据、量表、许可或合规状态。合同和官方验证服务不参与覆盖。同级规则冲突时，说明冲突并请用户选择；不静默覆盖。

团队定制（换产品、启用 overlay、追加验证）写在根目录的 `local.yaml`，不改本文件。机制见 [架构说明](docs/ARCHITECTURE.md) 和 [组合与覆盖合同](references/contracts/overlay-contract.md)，只在需要定制时读取。
