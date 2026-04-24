# 功能深潜文档（Feature Deep Dives）

这个子目录是对 `../README.md` 主索引的 **细节补充**：主索引侧重"系统能做什么、给谁用、长什么样"，本目录侧重"具体功能在代码层面是怎么实现的、数据如何流转、字段如何对应"。每篇文档都对应到 `apps/backend/app/services/` 下一个或几个 Python 模块和 `apps/web/app/` 下一组页面，方便答辩 / 验收时能"指哪打哪"地展示证据。

## 文档清单

1. [追问策略库与挑战机制（含语气变奏、评委角色卡、Critic Agent）](./01-challenge-and-probing.md)
   - 对应代码：`services/challenge_strategies.py`、`services/competition_judges.py`、`services/diagnosis_engine.py`、`services/agents.py::critic_agent_*`
   - 关键产物：`agent_trace.critic`、`agent_trace.competition.active_judge`、`agent_trace.preferred_tone`、`agent_trace.tone_origin`、`pressure_test_trace`
2. [测试用例库与回归脚本体系（test_final01_*.py 全套）](./02-test-library-and-regression.md)
   - 对应代码：`apps/backend/scripts/test_final01_*.py`
   - 关键产物：`regression_final01_*.json`
3. [聊天室与对话双轨制（room vs conversation）](./03-chat-room-and-conversations.md)
   - 对应代码：`services/chat_storage.py`、`services/storage.py::ConversationStorage`、`apps/web/app/chat/`
   - 数据落盘：`data/chat/rooms.json`、`data/chat/messages/{room_id}.json`、`data/conversations/`
4. [财务预算系统（BudgetStorage + finance_guard + finance_analyst）](./04-finance-budget-system.md)
   - 对应代码：`services/budget_storage.py`、`services/revenue_models.py`、`services/finance_pattern_formulas.py`、`services/finance_guard.py`、`services/finance_analyst.py`、`services/finance_report_service.py`
   - 数据落盘：`data/budgets/{user_id}/{plan_id}.json`、`data/finance_reports/{project_id}.json`
5. [商业计划书运行时（章节模板 → pending_revisions → coaching_mode 切换）](./05-business-plan-runtime.md)
   - 对应代码：`services/business_plan_service.py`
   - 关键产物：`data/business_plans/{plan_id}.json` 中的 `sections`、`pending_revisions`、`agenda_signals`、`coaching_mode`、`version_history`

## 怎么读这些文档

- 每篇文档第一节都是**一图流的功能定位**，二节是**代码 / 数据落点**，三节及以后才是细节。
- 想 30 秒理解一个功能：只看第 1、2 节。
- 想跑一遍验证：跳到每篇文档末尾的"自测命令 / 接口对照"。
- 写论文 / 答辩稿：直接抽里面的「设计要点」「字段定义表」段落即可。

## 与上层文档的关系

- 顶层主索引：`../README.md`
- 全局 Prompt 编排：`../all-prompts-and-orchestration.md`
- 项目类型识别：`../project-type-orchestration-and-prompts.md`
- 知识图谱与超图：`../knowledge-graph-and-evaluation.md` / `../hypergraph-and-evaluation.md` / `../kg-hypergraph-reference-and-retrieval.md`
- 商业计划书外部行为：`../business-plan-generation-and-word-export.md`（本目录第 5 篇是它的实现层补充）
- 商业模式与财务概览：`../business-model-finance-intervention-and-market-sizing.md`（本目录第 4 篇是它的实现层补充）
- 5 会话回归测试结论：`../test-cases-and-results.md`（本目录第 2 篇说明这些回归是**怎么写出来的**）

## 一句话总览

本目录把"追问 / 测试 / 聊天 / 预算 / 计划书"五大模块的 Python 文件、JSON 落盘格式、HTTP 路由、前端组件**逐字段拉通**，让任何看完文档的人都能直接打开对应代码继续读、或直接根据接口表写自动化用例。
