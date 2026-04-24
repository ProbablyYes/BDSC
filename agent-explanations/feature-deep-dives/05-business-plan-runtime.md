# 商业计划书运行时（章节模板 → pending_revisions → coaching_mode 切换）

> 对应主索引：`../README.md`
> 外部行为篇：`../business-plan-generation-and-word-export.md`（讲"系统给学生交付了什么"）
> 本篇：`business_plan_service.py` 的**实现层**——讲数据怎么落、状态怎么转、议题怎么沉淀。
> 对应代码：`apps/backend/app/services/business_plan_service.py`（≈ 6000 行）
> 对应路由：`/api/business-plan/*`（见末尾 API 表）
> 对应前端：`apps/web/app/business-plan/[planId]/`、`apps/web/app/business-plan/[planId]/annotate/`、`/print/`

## 1. 一图流：从对话到答辩稿的 4 个状态

```
                                    ┌──── 学生在 /business-plan/ 编辑 ────┐
                                    │   (PUT sections/{id} → user_edit)    │
                                    │                                       │
对话 (conversation)  ─readiness─▶ generate_plan ─▶ DRAFT ─edit / accept─▶ SYNCED
                                                                          │
                                          set_coaching_mode("competition") │
                                          (要求 maturity tier ≥ basic_ready) │
                                                                           ▼
                                                              COMPETITION COACHING
                                                              ─ 议题板 (agenda)
                                                              ─ 全书巡检 (jury review)
                                                              ─ 段落 patch → pending_revisions
                                                                           │
                                                                  finalize_plan / fork_for_competition
                                                                           ▼
                                                              FINAL  /  competition_fork
                                                                           │
                                                                Word / PDF 导出
                                                                / 打印 / 注释
```

## 2. 章节模板（SECTION_TEMPLATES，13 章固定骨架）

代码：`business_plan_service.py` 第 26 行起

| section_id | 标题 | 核心 slot | 对应 framework |
| --- | --- | --- | --- |
| `overview` | 项目概述 | `solution`, `stage_plan` | 一句话价值主张 / 使命愿景 |
| `users` | 用户痛点与目标人群 | `target_user`, `pain_point` | JTBD / 5W1H / 痛点分层 |
| `solution` | 产品/服务方案 | `solution`, `core_advantage` | 价值主张画布 / 体验地图 |
| `business_model` | 商业模式与价值主张 | `business_model` | BMC 九宫格 / 收入模型 |
| `market` | 市场与行业分析 | `market_competition` | TAM/SAM/SOM / PEST |
| `competition` | 竞争与差异化 | `core_advantage`, `market_competition` | 竞品矩阵 / 护城河五维 |
| `team` | 团队与执行 | `team_capability` | RACI / 能力矩阵 |
| `roadmap` | 阶段规划与里程碑 | `stage_plan` | OKR / 关键路径 |
| `finance` | 财务测算与盈利 | `finance_logic` | LTV/CAC / 现金流 / 三档情景 |
| `funding` | 融资与资金使用 | `finance_logic` | Use of Funds / 估值锚 |
| `risk` | 风险与合规 | — | 风险矩阵 / 合规清单 |
| `social_value` | 社会价值与可持续 | — | SDG 对齐 / 影响力测度 |
| `ask` | 项目诉求 | — | Ask 三件套 |

每章模板字段结构：

```python
{
  "section_id": "...",
  "title": "...",
  "core_slots": [...],                # 与 conversation.exploration_state.filled_slots 对齐
  "writing_points": [...],            # 这章要回答的具体小问题
  "subheadings": [...],               # 默认子标题
  "frameworks": [...],                # 引用的方法论框架
}
```

> 这 13 章是固定骨架，不会按学生改动而增减；学生可以编辑 `display_title` 和 `content`，但 section_id 顺序 / 数量始终一致，方便 Word 导出和评委打分。

## 3. 计划书 JSON 数据模型

落盘：`data/business_plans/{project_id}/{conversation_id}/{plan_id}.json`

```json
{
  "plan_id": "8 字符 hex",
  "project_id": "...",
  "conversation_id": "...",
  "student_id": "...",
  "title": "AI 法务 · 数据合规 · 商业计划书",
  "status": "draft | synced | user_edited | finalized",
  "version_tier": "draft | basic | full",
  "plan_type": "main | competition_fork",
  "fork_of": null,
  "mode": "learning | competition | coursework",
  "coaching_mode": "project | competition",
  "competition_unlocked": true,
  "submission_status": "draft | submitted | reviewed",

  "created_at": "...",
  "updated_at": "...",

  "sections": [
    {
      "section_id": "overview",
      "title": "项目概述",
      "display_title": "项目概述（v3）",
      "content": "...",
      "ai_draft": "...",
      "user_edit": "",
      "field_map": { "solution": "...", "stage_plan": "..." },
      "missing_points": ["缺少阶段时间线"],
      "missing_level": "minor | partial | major",
      "status": "ok | needs_review | needs_rewrite",
      "is_ai_stub": false,
      "revision_status": "clean | dirty",
      "updated_at": "..."
    }
  ],

  "knowledge_base": {
    "rag_cases": [...],
    "graph_risk_rules": [...],
    "competition_domain": {...}
  },

  "maturity": {
    "tier": "not_ready | partial_ready | basic_ready | full_ready",
    "score": 78,
    "breakdown": { "skeleton": 50, "agent_density": 22, "coherence": 6,
                   "skeleton_max": 60, "agent_density_max": 30, "coherence_max": 10 },
    "field_levels": { "target_user": "concrete", ... },
    "next_gap": [ {"section_id":"finance","suggestion":"补 LTV/CAC 估算"} ]
  },

  "pending_revisions": [
    {
      "revision_id": "uuid",
      "section_id": "competition",
      "anchor_text": "我们的核心优势是 AI 模型更准确",
      "new_content": "...（评委视角的整段重写）",
      "candidate_field_map": {...},
      "candidate_missing_level": "minor",
      "expected_diff_summary": "把"更准确"改成具体准确率 + 测试集出处",
      "jury_tag": "证据 | 量化 | 防守点 | 差异化 | 赛道匹配",
      "priority": "high | med | low",
      "title": "把准确率改成可证伪数字",
      "source_kind": "chat | jury_review",
      "source_message_ids": [...]
    }
  ],
  "revision_badge_count": 3,

  "competition_agenda": [
    {
      "agenda_id": "uuid",
      "section_id": "...",
      "anchor_text": "...",
      "title": "...",
      "weakness": "...",
      "suggestion": "...",
      "expected_diff_summary": "...",
      "jury_tag": "...",
      "priority": "high",
      "source_kind": "chat | jury_review",
      "source_message_ids": [...],
      "created_at": "...",
      "status": "open | applied | dismissed"
    }
  ],

  "cover_info": { "project_name", "student_or_team", "course_or_class",
                  "teacher_name", "date" },
  "source_summary": { "latest_user_message": "...", "message_count": 27 },

  "version_history": [
    { "version": 1, "timestamp": "...", "diff_summary": "首次草稿" },
    { "version": 2, "timestamp": "...", "diff_summary": "competition / users 段落 LLM 重写" }
  ]
}
```

## 4. 三个核心方法的语义

### 4.1 `get_readiness(project_id, conversation_id)`

`generate_plan` 之前的"准入门禁"。计算：

1. **slot_map**：13 章核心 slot 是否在对话历史里出现过关键词，或被 `exploration_state.filled_slots` 标过。
2. **maturity**：3 个分项加权
   - `skeleton`（骨架完整度，最高 60）
   - `agent_density`（多智能体补出来的字段密度，最高 30）
   - `coherence`（章节间逻辑自洽度，最高 10）
3. **tier**：`not_ready / partial_ready / basic_ready / full_ready`
4. **suggested_questions**：缺什么 slot 就把这个 slot 翻成"请补充一下项目的 XX"。

只有 `tier ∈ {basic_ready, full_ready}` 才能切换到 **竞赛教练模式**；只有 `tier != not_ready` 才能正常生成计划书；`not_ready` 必须显式 `allow_low_confidence=True` 才生草稿。

### 4.2 `generate_plan(...)` / `refresh_plan(plan_id)`

1. 拿到 `current = _load_latest_main(...)`（只取主干，不包含 fork）。
2. `_build_draft(conv, current=current, mode=mode)` 用对话历史 + 知识库 + 财务摘要为每章生成新内容。
3. 如果有 current → `_build_revisions(current.sections, draft.sections, conv)` 比对差异，把差异点收成 `pending_revisions`（不会直接覆盖，等待学生 / 评委 accept）。
4. `_save_plan(...)`：保留旧版本，写一条 `version_history`，落新 JSON。

> 设计目标：**永远只生成"待接受的修改"，不破坏学生已有手改**。学生 user_edit 字段 > AI ai_draft，content 显示的永远是 user_edit 优先；接受修订时 user_edit 才被清空。

### 4.3 `accept_revision / reject_revision / accept_all / reject_all`

接受时把 `revision.new_content → section.ai_draft → section.content`，user_edit 清空，pending list 移除该条。
拒绝时直接 pending list 移除该条，sections 不变。
两者都会：`status = "synced"` + 推一条 `version_history`。

## 5. 教练模式（coaching_mode）：项目 vs 竞赛

`set_coaching_mode(plan_id, "competition")`：

- 校验 `competition_unlocked`（实时跑一遍 readiness）。
- 不复制计划书、不改章节 → 只是把 `coaching_mode` 翻成 `competition`，并初始化 `competition_agenda`。
- 一旦切到 competition，**议题板 + 全书巡检 + 段落 patch** 这三个能力才会启用。

## 6. 议题板（competition_agenda）：聊天沉淀 + 全书巡检

### 6.1 聊天沉淀：`note_agenda_signal(plan_id, assistant_text, source_message_id)`

- 每轮 assistant 回复都调一次。
- **缓冲池**：`_agenda_chat_buffer[plan_id]` 累积；满 `_AGENDA_CHAT_BATCH = 4` 条 或距上次抽取 > `_AGENDA_CHAT_MAX_GAP_SEC = 600s`，才真正 flush 一次。
- flush 时调 `_llm_extract_agenda_from_chunk` 把多轮回复一次性送 LLM，按结构化 schema 输出议题；LLM 失败时关键词兜底 `_keyword_extract_agenda_from_text`。
- 命中的议题 normalize 后追加到 `competition_agenda`，重复 (`section_id`, `anchor_text`) 的会去重。

### 6.2 全书巡检：`run_jury_review(plan_id, force=False)`

- 把每一章送 LLM，让"评委 agent"以 5 个维度（证据 / 量化 / 防守点 / 差异化 / 赛道匹配）逐章给 0–2 条议题。
- 节流：1 分钟内不重复跑（除非 `force=True`）。
- 过程持久化在 `_review_status[plan_id]`：`{state, current_index, total, current_section_title, ts, error}`；前端可以轮询展示进度条。

### 6.3 议题 → 段落 patch

议题进入 `competition_agenda` 后是只读的"待办"，前端可以勾选若干条点"应用为段落修改"，调用：

```
POST /api/business-plan/{plan_id}/agenda/apply-as-revision
body: { agenda_ids: ["..."] }
```

后端会针对每条议题，按 `anchor_text` 用 LLM 做**段落级 patch**，结果以 `pending_revisions[]` 形式落到对应章节，等待 `accept_revision`。

> 这一套是**两段式**：议题与正文修改解耦。先把"评委想让你改什么"沉淀下来，再让学生决定要不要把建议变成实际改动。这样既保留 LLM 的批判力度，又给学生终审权。

## 7. 主干 / Fork：`fork_for_competition(plan_id, ...)`

- 只有 `plan_type == "main"` 才能被 fork。
- 复制 plan，改 `plan_id` / `plan_type=competition_fork` / `fork_of=plan_id` / `mode=competition` / `version_tier=full`。
- fork 时会**重新拉一遍 KB**：`rag_engine` 语义检索 + `case_knowledge` 案例 + `graph_service` 风险规则 + competition_domain 信息，写入 fork 的 `knowledge_base` 字段。
- fork 后两份计划书并存，learning 主干和 competition_fork 各自独立迭代，互不污染。

## 8. 章节状态机（每章 4 个字段联动）

| 字段 | 取值 | 来源 |
| --- | --- | --- |
| `missing_level` | `complete / minor / partial / major` | `_missing_level(row)` 按 field_map 完整度 + 章节中文长度判 |
| `status` | `ok / needs_review / needs_rewrite` | `_status_from_missing(missing_level)` |
| `revision_status` | `clean / dirty` | accept 后 clean，user_edit 后 dirty |
| `is_ai_stub` | bool | `_section_has_material()` 没素材时打 stub 标 |

前端按 status 上色：ok = 绿、needs_review = 黄、needs_rewrite = 红，dirty = 紫色徽标。

## 9. API 全景（`/api/business-plan/*`）

| 路径 | 用途 |
| --- | --- |
| `GET /api/business-plan/latest?project_id=&conversation_id=` | 最新计划书 |
| `GET /api/business-plan/{plan_id}` | 拉指定计划书 |
| `POST /api/business-plan/generate` | 生成 / 刷新草稿（按 readiness 判断是否允许） |
| `POST /api/business-plan/{plan_id}/refresh` | 用现有 plan 的 conv_id 重新生成 |
| `PUT /api/business-plan/{plan_id}/sections/{section_id}` | 学生编辑某章 |
| `POST /api/business-plan/{plan_id}/revisions/{revision_id}/accept` | 接受单条修订 |
| `POST /api/business-plan/{plan_id}/revisions/{revision_id}/reject` | 拒绝单条修订 |
| `POST /api/business-plan/{plan_id}/revisions/accept-all` | 全部接受 |
| `POST /api/business-plan/{plan_id}/revisions/reject-all` | 全部拒绝 |
| `POST /api/business-plan/{plan_id}/coaching-mode` | 切换 project / competition |
| `POST /api/business-plan/{plan_id}/agenda/note` | 聊天沉淀（一般由后端自动调，不需前端调） |
| `POST /api/business-plan/{plan_id}/agenda/jury-review` | 触发全书巡检 |
| `POST /api/business-plan/{plan_id}/agenda/apply-as-revision` | 把议题转成 pending_revisions |
| `GET /api/business-plan/{plan_id}/comments` | 列评注 |
| `POST /api/business-plan/{plan_id}/comments` | 加评注 |
| `PATCH /api/business-plan/{plan_id}/comments/{cid}` | 改评注 |
| `DELETE /api/business-plan/{plan_id}/comments/{cid}` | 删评注 |
| `POST /api/business-plan/{plan_id}/finalize` | 定稿 |
| `POST /api/business-plan/{plan_id}/fork-competition` | Fork 出竞赛分支 |
| `GET /api/business-plan/{plan_id}/export.docx` | 导出 Word |

## 10. 自测路径

```powershell
# 1. 跑一遍多项目对话脚本，让 final-01 的项目积累 maturity
.venv\Scripts\python.exe apps\backend\scripts\test_final01_dialogue.py

# 2. 在前端 /business-plan/ 点 "生成草稿" → 应该看到 sections 13 章 + status 着色

# 3. 调 readiness 看 maturity 数值
curl "http://127.0.0.1:8037/api/business-plan/latest?project_id=project-99fed9ab-486c-4b22-8329-b3c6466e17d2&conversation_id=<conv>"

# 4. 切到 competition 教练
curl -X POST http://127.0.0.1:8037/api/business-plan/<plan_id>/coaching-mode `
  -H "Content-Type: application/json" `
  -d '{"mode":"competition"}'

# 5. 跑全书巡检
curl -X POST http://127.0.0.1:8037/api/business-plan/<plan_id>/agenda/jury-review

# 6. 看议题板里新增的 N 条议题
curl http://127.0.0.1:8037/api/business-plan/<plan_id>
```

## 11. 设计要点摘录（可直接抄进答辩稿）

1. **草稿不一次性写满**：`generate_plan` 在 draft 阶段只保证"极短章节有兜底文字"，复杂内容交给后续 revisions 慢慢补，避免一开始就生成几千字让学生不知道该改哪儿。
2. **AI 永远不直接覆盖学生手改**：所有 LLM 增改都进 `pending_revisions`，accept 才落正文；user_edit > ai_draft > 模板兜底。
3. **议题与正文修改解耦**：`competition_agenda` 是"待办评议"，`pending_revisions` 是"待批准的段落 patch"。学生先看议题，再决定要不要让 LLM 真的改正文。
4. **聊天沉淀有节流缓冲池**：避免每轮对话都打 LLM 抽议题，集中 4 条或 10 分钟一次，成本可控。
5. **教练模式切换有门禁**：`maturity tier` 不达 basic_ready 不让进竞赛教练，避免学生在没东西可改时空跑议题板。
6. **主干 / fork 分离**：项目教练（learning）的主干永远干净，竞赛 fork 才会做大改与重排，两份计划书独立迭代，可同时存在。
