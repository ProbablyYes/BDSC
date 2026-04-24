# 智能体讲解文档

这个目录用于集中存放项目最终文档中可直接复用的“讲解型”内容，便于后续继续补充、交叉引用和跳转阅读。

如果要从项目总首页进入，请返回根目录文档：[`../README.md`](../README.md)。

## 目录导航

1. [商业项目与公益项目的编排区分及 Prompt 设计](./project-type-orchestration-and-prompts.md)
2. [全量 Prompt 体系与智能体编排说明](./all-prompts-and-orchestration.md)
3. [知识图谱及评估说明](./knowledge-graph-and-evaluation.md)
4. [超图及评估说明](./hypergraph-and-evaluation.md)
5. [知识图谱与超图的引用正确性、检索通道与下游输入说明](./kg-hypergraph-reference-and-retrieval.md)
6. [完整商业策划书生成与 Word 下载说明](./business-plan-generation-and-word-export.md)
7. [商业模式生成、差异化盈利方案与财务智能体会话干预说明](./business-model-finance-intervention-and-market-sizing.md)
8. [测试用例与结果分析（5 会话 × 20 轮真实对话证据）](./test-cases-and-results.md)
9. [用户管理、角色身份与权限管理说明](./usermanage.md)
10. [学生端与教师端画像功能说明](./画像.md)
11. [管理员端功能总览](./admin.md)
12. [界面美观与易用性说明](./ui.md)

## 文档分组

### 1. 智能体主链路

- [商业项目与公益项目的编排区分及 Prompt 设计](./project-type-orchestration-and-prompts.md)
- [全量 Prompt 体系与智能体编排说明](./all-prompts-and-orchestration.md)

### 2. 图谱与结构化知识

- [知识图谱及评估说明](./knowledge-graph-and-evaluation.md)
- [超图及评估说明](./hypergraph-and-evaluation.md)
- [知识图谱与超图的引用正确性、检索通道与下游输入说明](./kg-hypergraph-reference-and-retrieval.md)

### 3. 文档生成与商业分析

- [完整商业策划书生成与 Word 下载说明](./business-plan-generation-and-word-export.md)
- [商业模式生成、差异化盈利方案与财务智能体会话干预说明](./business-model-finance-intervention-and-market-sizing.md)

### 4. 系统验证与测试证据

- [测试用例与结果分析](./test-cases-and-results.md)：5 个会话 × 20 轮真实对话的端到端行为记录，含诊断/财务/KG/超图逐轮证据。

### 5. 账户体系与端到端画像

- [用户管理、角色身份与权限管理说明](./usermanage.md)：学生 / 教师 / 管理员三类角色的注册、登录、权限矩阵、批量导入与团队管理全流程。
- [学生端与教师端画像功能说明](./画像.md)：学生九维能力画像 + 教师端团队 / 学生 / 项目三层画像 + 教师对 AI 结论的订正机制。
- [管理员端功能总览](./admin.md)：全校大盘、教师表现、教学干预监控、漏洞看板、访问与安全日志、系统健康度。

### 6. 界面与交互体验

- [界面美观与易用性说明](./ui.md)：深色主题 + 玻璃态 + 渐变光效的视觉语言、三端入口、学生端双面板、聊天室、教师端可视化、响应式与可访问性。

### 7. 功能深潜（实现层补充，新）

下面这组文档是对前 12 篇主索引的**实现层补充**：把"追问 / 测试 / 聊天 / 预算 / 计划书"五大模块的 Python 文件、JSON 落盘格式、HTTP 路由、前端组件**逐字段拉通**，便于答辩、迭代与扩展。完整索引见 [`./feature-deep-dives/README.md`](./feature-deep-dives/README.md)。

- [追问策略库与挑战机制（语气变奏 + 评委角色卡 + Critic）](./feature-deep-dives/01-challenge-and-probing.md)
- [测试用例库与回归脚本体系（test_final01_*.py 全套）](./feature-deep-dives/02-test-library-and-regression.md)
- [聊天室与对话双轨制（room vs conversation）](./feature-deep-dives/03-chat-room-and-conversations.md)
- [财务预算系统（BudgetStorage + finance_guard + finance_analyst）](./feature-deep-dives/04-finance-budget-system.md)
- [商业计划书运行时（章节模板 → pending_revisions → coaching_mode）](./feature-deep-dives/05-business-plan-runtime.md)

## 使用建议

- 如果是写最终说明书，可以直接从这篇主文档中抽取段落。
- 如果是做答辩或 PPT，可以优先查看其中的"编排重点""Prompt 设计差异"和"总结表述"部分。
- 后续新增主题时，建议继续按"一篇主题一个文件"的方式扩展，并在本页补上链接。

## 推荐阅读顺序

1. 先看[商业项目与公益项目的编排区分及 Prompt 设计](./project-type-orchestration-and-prompts.md)，建立整体应用场景。
2. 再看[全量 Prompt 体系与智能体编排说明](./all-prompts-and-orchestration.md)，理解系统如何调度各类 Agent。
3. 接着阅读图谱三篇文档，理解知识图谱、超图及其在运行时的检索与引用方式。
4. 接着阅读计划书与商业模式两篇文档，理解系统怎样把前述分析成果沉淀成商业策划书与财务判断。
5. 然后阅读[测试用例与结果分析](./test-cases-and-results.md)，结合 654321 账号下的 5 个真实会话，验证前 7 篇描述的能力在实际对话中的触发轨迹。
6. 最后阅读账户与画像三篇（`usermanage / 画像 / admin`）以及[界面美观与易用性说明](./ui.md)，把"系统能做什么"补上"系统给谁用、长什么样、怎么管"这几层。

## 最终交付清单

- `01` [商业项目与公益项目的编排区分及 Prompt 设计](./project-type-orchestration-and-prompts.md)：说明系统如何区分不同项目类型并调整提示词。
- `02` [全量 Prompt 体系与智能体编排说明](./all-prompts-and-orchestration.md)：完整解释学生端、教师端与多智能体链路中的 Prompt。
- `03` [知识图谱及评估说明](./knowledge-graph-and-evaluation.md)：说明知识图谱的结构、评估维度与当前结果。
- `04` [超图及评估说明](./hypergraph-and-evaluation.md)：说明超图的结构设计、评估逻辑与当前结果。
- `05` [知识图谱与超图的引用正确性、检索通道与下游输入说明](./kg-hypergraph-reference-and-retrieval.md)：说明图谱和超图如何在运行时被检索、格式化并输入各 Agent。
- `06` [完整商业策划书生成与 Word 下载说明](./business-plan-generation-and-word-export.md)：说明商业计划书如何从对话与分析结果生成、迭代、升级并导出。
- `07` [商业模式生成、差异化盈利方案与财务智能体会话干预说明](./business-model-finance-intervention-and-market-sizing.md)：说明商业模式、TAM/SAM/SOM 与财务智能体的会话干预机制。
- `08` [测试用例与结果分析](./test-cases-and-results.md)：在 `654321` 账号下跑完 5 个会话 × 20 轮真实对话，系统化验证前 7 篇描述的能力是否真实被触发。
- `09` [用户管理、角色身份与权限管理说明](./usermanage.md)：三角色 RBAC 模型、注册登录、权限矩阵、批量创建与团队邀请码机制。
- `10` [学生端与教师端画像功能说明](./画像.md)：九维能力画像、团队诊断、项目画像与教师 AI 订正链路。
- `11` [管理员端功能总览](./admin.md)：全校大盘、教师表现、教学干预、漏洞看板、安全日志与系统健康度。
- `12` [界面美观与易用性说明](./ui.md)：平台视觉语言、交互细节与响应式 / 可访问性设计。

## 快速跳转

- [跳到项目类型识别部分](./project-type-orchestration-and-prompts.md#项目类型识别机制)
- [跳到商业项目提示词部分](./project-type-orchestration-and-prompts.md#商业项目的-prompt-设计)
- [跳到公益项目提示词部分](./project-type-orchestration-and-prompts.md#公益项目的-prompt-设计)
- [跳到第二篇文档的学生端 Prompt 体系](./all-prompts-and-orchestration.md#三学生端-prompt-体系)
- [跳到第二篇文档的教师端 Prompt 体系](./all-prompts-and-orchestration.md#五教师端-prompt-体系)
- [跳到知识图谱文档的评估方法部分](./knowledge-graph-and-evaluation.md#四知识图谱评估方法)
- [跳到超图文档的评估方法部分](./hypergraph-and-evaluation.md#四超图评估方法)
- [跳到图谱/超图文档的引用正确性部分](./kg-hypergraph-reference-and-retrieval.md#九系统怎样保证引用正确)
- [跳到商业策划书文档的生成主链路部分](./business-plan-generation-and-word-export.md#五草稿生成先产出骨架版而不是一上来写超长正式稿)
- [跳到商业模式文档的会话干预部分](./business-model-finance-intervention-and-market-sizing.md#四系统如何在会话中即时干预财务问题)
- [跳到测试文档的 5 会话总览与 Mermaid 图](./test-cases-and-results.md#2-测试用例总览)
- [跳到测试文档的结果汇总与改进建议](./test-cases-and-results.md#6-结果汇总与改进建议)
- [跳到用户管理文档的权限矩阵](./usermanage.md#22-权限矩阵)
- [跳到用户管理文档的批量导入](./usermanage.md#五管理员用户管理功能)
- [跳到画像文档的九维评审维度](./画像.md#13-九维评审维度)
- [跳到画像文档的教师订正功能](./画像.md#237-教师订正功能)
- [跳到管理员端的教学干预监控](./admin.md#4-教学干预监控)
- [跳到界面文档的学生端双面板](./ui.md#41-对话与分析面板并排显示)

## 一句话总览

这 12 篇文档共同覆盖了本项目从底层到用户层的完整说明范围：智能体编排与 Prompt 设计 → 知识图谱 / 超图及其运行时引用 → 商业计划书、商业模式与财务分析的生成与优化 → 5 会话 × 20 轮真实对话的端到端验证证据，再到账号与角色体系、学生 / 教师 / 项目三层画像、管理员后台监控，以及支撑这一切的前端视觉与交互设计——完整描述了 BDSC 双创智能体平台「能做什么、给谁用、长什么样、怎么管」四个层次。
