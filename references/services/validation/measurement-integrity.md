# 测量完整性验证

本服务检查题目是否实际测量了所声称的内容。每次交付问卷或审核结果前执行。题序、选项来源、刺激物和量表的具体写法见 [题目工艺](../../modules/knowledge/question-craft.md)，本文件只列检查项。

## 受访资格

- 先问真实行为和使用资格，再问体验评价、原因和需求。
- 未使用过功能的用户不评价实际使用体验。可以测量认知、未使用原因和未来需求。
- 测试未上线概念时，使用概念评价语言，不使用实际体验语言。

## 题目和选项

- 一道题只测量一个主要概念。
- 题目明确对象、时间范围和使用场景。召回期与行为频率匹配。
- 题干和选项使用用户能观察到的描述，不使用宣传文案。
- 选项保持同一层级，并在任务允许范围内尽量互斥、穷尽。
- 封闭列表写明来源；自拟列表列入研究简报与方案的需确认项。
- 不知道、不适用、拒答、“其他”和“以上都没有”按语义需要设置，不按统一数字编码强制设置。
- 量表方向和端点含义保持一致。
- 版本、型号、使用时长等受访者容易说错的事实，提供核验方式。

## 标准题组和量表

- 代表题、结构说明、工作译文和项目模板不得包装为完整正式量表。
- 无法核验完整题项、正式语言版本、计分方式和许可时，不得声称交付正式标准量表。
- 修改标准题组后标记为适配版，不继续使用原常模或跨研究比较结论。
- 正式跨语言、跨市场或跨期追踪项目记录翻译、回译、认知访谈和预测试状态。

## 规则

| rule_id | 检查 | 默认严重程度 | 脚本可检 |
|---|---|---|---|
| `measurement.experience-required` | 使用体验评价题只向有实际使用经历的受访者显示 | `error` | 是（需在资格题中标记 `eligible`） |
| `measurement.concept-language` | 未上线概念使用概念评价语言，不使用实际体验语言 | `error` | 否 |
| `measurement.single-construct` | 一道题只测量一个主要概念；不出现双重提问；一个选项只写一件事 | `warning` | 否 |
| `measurement.explicit-frame` | 题干明确对象、时间范围和使用场景 | `warning` | 否 |
| `measurement.recall-period` | 召回期与行为频率匹配；不要求精确回忆不显眼的小事件次数 | `warning` | 否 |
| `measurement.marketing-language` | 题干和选项不使用宣传文案或评价性形容词，改为可观察的功能描述 | `warning` | 否 |
| `measurement.options-mece` | 选项同层级，并尽量互斥、穷尽 | `warning` | 部分（区间重叠见 `spec.range-overlap`） |
| `measurement.option-source` | 封闭列表写明来源；自拟列表列入研究简报与方案的需确认项 | `warning` | 是（多选和排序题，需在规格中填写 `option_source`） |
| `measurement.special-options` | 特殊选项按语义设置，不按统一数字强制设置；并非人人适用的矩阵行提供“无法评价” | `warning` | 否 |
| `measurement.scale-consistency` | 评分点数、方向和端点含义在同类题中一致 | `warning` | 是 |
| `measurement.self-report-verification` | 版本、型号、使用时长等易错事实给出查看路径、截图、图片识别或交叉核验 | `warning` | 否 |
| `measurement.order-general-first` | 总体评价在对应细项评价之前 | `warning` | 否 |
| `measurement.order-before-exposure` | 评价在功能介绍、卖点、概念或价格曝光之前；曝光后的评价在方案中说明 | `warning` | 否 |
| `measurement.order-unaided-first` | 无提示认知在提示认知之前 | `error` | 否 |
| `measurement.order-rating-before-reason` | 原因或方面选择题不在使用同一列表的评分题之前出现 | `warning` | 是（列表与后续矩阵行重复时） |
| `measurement.stimulus-presentation` | 视觉和交互类对象用图片或视频展示，写明展示条件，多方案顺序随机或平衡，说明不透露研究假设 | `warning` | 否 |
| `measurement.scale-authenticity` | 不将代表题、工作译文或项目模板声称为正式量表 | `error` | 否 |
| `measurement.adapted-scale` | 修改后的标准题组标记为适配版，不沿用原常模 | `warning` | 否 |
| `measurement.translation-record` | 正式跨语言、跨市场或追踪项目记录翻译和预测试状态 | `warning` | 否 |
| `measurement.leading-wording` | 题干不暗示期望答案，不预设受访者立场 | `warning` | 否 |

## 阻断条件

无经验者评价真实体验、交付物伪造正式量表状态，或提示认知被当作无提示认知时，返回 `error`。
