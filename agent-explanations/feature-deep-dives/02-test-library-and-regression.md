# 测试用例库与回归脚本体系

> 对应主索引：`../README.md`
> 对应代码：`apps/backend/scripts/test_*.py`
> 落盘：项目根目录的 `regression_final01_*.json` / `apps/backend/regression_*.json`
> 与 `../test-cases-and-results.md` 的区别：那篇是把跑出来的"结果"当证据展示给评审看；本篇是讲"测试本身"是怎么写的、应该怎么用。

## 1. 总览：5 大类、9 个脚本

| 分类 | 脚本 | 模式 | 轮数 | 主目标 |
| --- | --- | --- | --- | --- |
| ① 多项目漂移 | `test_final01_dialogue.py` | learning | 4 项目 × 多轮 | 验证项目编号、双光谱漂移、ability_subgraph 引用 |
| ② 财务专项 | `test_final01_finance_dialogue.py` | learning | 6 轮 | 单项目里把财务测算从盈利模式打到融资节奏 |
| ② 财务专项（直接打底层） | `test_final01_finance_report.py` | 直接调 service，不走 HTTP | 多场景 | 验证 finance_report_service 在不同行业模板下的输出 |
| ② 财务单元测试 | `test_finance_extractor.py` / `test_finance_e2e.py` | 直接调 service | 7 + 5 场景 | 验证 7 种收入 pattern 抽取 + 端到端写入预算 + 重算现金流 |
| ③ 合规 / 国际化 / 学术 | `test_final01_case9.py` | competition | 6 轮单会话 | 让同一项目编号承接 6 轮，验证 critic / judge / 跨语义维度 |
| ④ 学生学习模式 | `test_final01_case1.py` | learning | 6 轮单会话 | 大一新生入门：验证启发式提问 + 案例引用 + 跨图谱启发 |
| ⑤ 追问语气 | `test_final01_tone_library.py` | learning | 4 轮 | 验证 strict / humorous 在同一会话切换，且 tone_origin 标注正确 |
| ⑤ 评委角色卡 | `test_final01_judges_bank.py` | competition | 4 轮 | 验证 active_judge 跟着学生消息切换 |

> 所有"final-01"脚本都使用 `USER_ID = 99fed9ab-486c-4b22-8329-b3c6466e17d2`（`student_id = 1120230236`），项目编号统一是 `P-1120230236-NN`。

## 2. 通用结构（学这个 → 自己加用例时照抄）

每个脚本都是一个"无外部依赖的纯 Python"，只用 `urllib.request` + `json`：

```python
API        = "http://127.0.0.1:8037"
USER_ID    = "99fed9ab-486c-4b22-8329-b3c6466e17d2"
PROJECT_ID = f"project-{USER_ID}"
STUDENT_ID = "1120230236"

CASES = [
    {
        "tag": "<本轮主题>",
        "expected_keywords": ["关键词1", "关键词2", ...],
        "min_hit": 2,
        "message": "<学生消息原文>",
    },
    ...
]

def main():
    conv_id = None
    for case in CASES:
        payload = {
            "project_id": PROJECT_ID,
            "student_id": STUDENT_ID,
            "message": case["message"],
            "conversation_id": conv_id,        # 第一轮 None；之后沿用
            "mode": "learning|competition|coursework",
            "competition_type": "",
        }
        resp = post("/api/dialogue/turn", payload)
        if not conv_id:
            conv_id = resp["conversation_id"]
        # 断言：关键词命中、tone、judge、family_distribution …
        # 落盘：regression_final01_xxx.json
```

设计要点：

1. **轮间共享 `conv_id`** → 模拟"学生在同一项目上连发 6 轮"，让后端的 `_derive_logical_project_id` 沿用同一个 `P-学号-NN`。
2. **轮间 `time.sleep(2.0)`** → 给 finance_guard、business_plan agenda 等异步钩子留处理余地，避免脏读。
3. **每轮断言三个层级**：
   - 文本层：关键词命中数 ≥ `min_hit`
   - 结构层：`triggered_rules` / `tone` / `judge` 是否符合预期
   - 副产品层：`kg_analysis.entities` / `hypergraph_insight.matched_by.family_distribution` / `rag_cases` 是否非空
4. **末尾 JSON 落盘** → 既是"测试报告"也是"教师演示素材"。

## 3. 逐脚本说明

### 3.1 `test_final01_dialogue.py`（多项目 × 双光谱漂移）

- **目标**：验证 4 个性质完全不同的项目（商业 SaaS / 公益 / 硬件 / 大众工具）能被 `project_cognition` 正确识别到不同象限，并落到不同 `logical_project_id`。
- **重点断言**：
  - 不同 case 之间 `logical_project_id` 必须互不相同（≠ 全部走兜底）。
  - `agent_trace.project_cognition.spectrum` 在 4 个项目里覆盖 `innov_venture` 和 `biz_public` 两个轴的不同象限。
  - `agent_trace.project_stage_v2` 随轮次推进。
- **典型用法**：每次大改 `project_cognition.py` 后跑一次。

### 3.2 `test_final01_case9.py`（合规 / 国际化 / 学术深度，6 轮）

- **目标**：6 个高深度场景在同一会话里推进 → 检验高阶追问、评委切换、跨域知识检索。
- **重点断言**：
  - 关键词命中 + 触发规则 ≥ 3 条 H 系列
  - `agent_trace.competition.tone_origin` 在合规轮自动 `forced_strict`
  - 同一项目编号承接 6 轮（不应该被识别成新项目）
- **配套输出**：`regression_final01_case9.json`（已存在于仓库根，是答辩素材）。

### 3.3 `test_final01_case1.py`（学生学习模式，6 轮）

- **目标**：模拟"大一新生想做创新创业"的零经验场景，**重点不是 CS 追问** 而是：
  - AI 是否能用引导性提问让学生自己想？（`min_questions` 阈值 + 启发词命中）
  - 是否给出对应知识点的案例？（文本里出现"案例 / 例如 / 比如" 或 `rag_cases` 非空）
  - 知识图谱是否触发跨图谱（≥2 实体类型 或 ≥2 超图家族）？
- **关键检查项**（抽自代码）：

```python
ok_q     = q_count >= case["min_questions"] and len(hint_terms_hit) >= 1
ok_case  = bool(case_terms_hit) or len(rag_cases) > 0
ok_cross = (len(ent_types) >= 2) or (len(fam_set) >= 2)
all_ok   = ok_kw and ok_q and ok_case and ok_cross
```

- **输出**：`regression_final01_case1.json`，末尾汇总 `kg_entity_type_union` / `hyper_family_union` / `rag_case_total`。

### 3.4 `test_final01_tone_library.py`（语气变奏）

- **目标**：在 1 个会话里前 2 轮"严肃一点"、后 2 轮"幽默一点"，验证：
  - `agent_trace.preferred_tone` 在 2/4 轮里实际发生切换；
  - `agent_trace.tone_origin` 在第 1 / 3 轮是 `explicit`，第 2 / 4 轮是 `sticky`。
  - `guiding_questions` 文字风格肉眼可见地不同（手工抽 sample 即可）。

### 3.5 `test_final01_judges_bank.py`（评委角色卡）

- **目标**：4 轮里依次显式切到 `aggressive_vc → tech_lead → finance_skeptic → gov_audit`，断言 `agent_trace.competition.active_judge` 在 4 轮里恰好命中 4 个不同 ID。
- **额外检查**：每轮命中评委的 `signature_questions` 至少有一条出现在回复里（保证 persona 真的注入了 prompt）。

### 3.6 财务三件套

- `test_final01_finance_dialogue.py`：走 `/api/dialogue/turn`，6 轮聊财务 → 看 `agent_trace.finance_guard`、回复里的"财务提醒卡片"。
- `test_final01_finance_report.py`：直接 `from app.main import budget_store, finance_report_service` 调底层，不经过 HTTP，专门验证 `finance_report_service.build_report()` 在不同行业模板下输出的"结构 + 数字" 都对。
- `test_finance_extractor.py` / `test_finance_e2e.py`：单元 / 端到端，验证消息里"月费 49 元 / 月活 5000 / 转化 3%"能被抽成 `subscription` pattern 并写进 `BudgetStorage`。

## 4. 输出文件命名约定

| 模块 | 落盘文件 | 关键字段 |
| --- | --- | --- |
| 主对话 | `regression_final01_dialogue.json` | `cases[].project_id`、`logical_project_ids`、`spectrum`、`stage` |
| 合规 | `regression_final01_case9.json` | `rows[].triggered_rules`、`active_judge`、`tone_origin`、`logical_project_id` |
| 学习 | `regression_final01_case1.json` | `rows[].checks.{questions_ok,case_ok,cross_graph_ok}` |
| 语气 | `regression_final01_tone.json` | `rows[].preferred_tone`、`tone_origin` |
| 评委 | `regression_final01_judges.json` | `rows[].active_judge`、`signature_question_hit` |
| 财务对话 | `regression_final01_finance_dialogue.json` | `rows[].finance_guard.cards`、`unit_econ` |
| 财务报告 | `data/finance_reports/{project_id}.json` | 由 `finance_report_service` 直接落盘，脚本读出来对账 |

## 5. 怎么跑（Windows / PowerShell）

```powershell
cd apps\backend

# 单脚本
.venv\Scripts\python.exe scripts\test_final01_case1.py

# 全套
foreach ($s in @(
  "scripts\test_final01_dialogue.py",
  "scripts\test_final01_case9.py",
  "scripts\test_final01_case1.py",
  "scripts\test_final01_tone_library.py",
  "scripts\test_final01_judges_bank.py",
  "scripts\test_final01_finance_dialogue.py",
  "scripts\test_final01_finance_report.py",
  "scripts\test_finance_e2e.py",
  "scripts\test_finance_extractor.py"
)) { .venv\Scripts\python.exe $s }
```

注意：`test_final01_*` 系列依赖后端在 `127.0.0.1:8037` 起着；`test_finance_e2e.py` / `test_finance_extractor.py` / `test_final01_finance_report.py` 不依赖 HTTP，纯本地。

## 6. 编码注意事项

Windows 控制台默认 GBK，`✓` 这种 Unicode 符号会导致 `UnicodeEncodeError`。已在新脚本里统一加上：

```python
import io, sys
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
```

并把成功 / 失败标记从 `✓ / ✗` 改成 `[OK] / [NG]`。

## 7. 回归脚本怎么扩展

1. 复制 `test_final01_case1.py` 改个 `tag` 即可成为新场景。
2. 如果要新增"非文本"断言（比如"这一轮必须返回某个超图边类型"）：
   - 在循环里 `hi = resp["hypergraph_insight"]`
   - 对 `hi["edges"]` 拿 `edge_type` 集合
   - 加自己的 `assert` 或 `ok_xxx` 字段
3. 如果要写"跨脚本汇总"：所有脚本都把单轮记录序列化成 `rows[]`，可以直接 `json.load` 做合并报表。

## 8. 写测试时的 5 条戒律

1. **不要 hardcode `conversation_id`**，永远用第一轮的返回值——否则一旦后端的 conv 自动清理跑了一次，所有用例集体 404。
2. **关键词列表别贪心**，10 个起步反而会被命中 1–2 个误以为通过。3-5 个 + `min_hit` 阈值更稳。
3. **断言 trace 字段时优先比"是否非空"和"是否变化"，不要硬比内容**——LLM 输出永远会有微小差异。
4. **每轮 sleep ≥ 1.5s**：给 finance_guard、business_plan_service.agenda 这种异步钩子留时间。
5. **写 README 在 JSON 顶层**：把 `student_id` / `user_id` / `conversation_id` / `logical_project_ids` 这种"环境元信息"放在最外层，方便人类直接 `head` 看一眼。
