# 追问策略库与挑战机制

> 对应主索引：`../README.md`
> 对应代码：
> - `apps/backend/app/services/challenge_strategies.py` —— 10 条 CS 策略 + 6 种语气变奏
> - `apps/backend/app/services/competition_judges.py` —— 评委角色卡库（VC / 技术专家 / 财务 / 政府等）
> - `apps/backend/app/services/diagnosis_engine.py` —— H1–H12 诊断规则（追问的"导火索"）
> - `apps/backend/app/services/graph_workflow.py` —— `resolve_tone_for_state` / `_competition_out` 字段拼装
> - `apps/backend/scripts/test_final01_tone_library.py` / `test_final01_judges_bank.py` —— 回归脚本
> 对应前端：学生端 topbar tone 切换、`agent_trace` 面板的 critic / pressure_test / competition 三个 Tab

## 1. 一图流：追问从触发到落地的完整链路

```
学生消息
   │
   ▼
diagnosis_engine.py             ──▶ triggered_rules（H1–H12 红/黄线）
   │                                │
   ▼                                ▼
challenge_strategies.py        匹配策略 = 关键词 ∩ 触发规则 ∩ 谬误标签 ∩ 偏好边类型
 select_probing_strategies         │
   │                                ▼
   ▼                          probing_layers（3 层递进追问）
                                 + counterfactual（反事实问题）
                                 + expected_evidence（要求学生补什么）
   │
   ▼
按 preferred_tone（cool/strict/humorous/warm/coaching/socratic）
重写 probing_layers 文本（tone_variants）
   │
   ▼
critic_agent / advisor / coach 把追问写进 assistant_message
   │
   ▼
agent_trace.critic / challenge_strategies / pressure_test_trace
agent_trace.preferred_tone / tone_origin
agent_trace.competition.active_judge
```

## 2. 三层结构（要求文档原话："怎么问"分三层）

| 层 | 概念 | 字段 |
| --- | --- | --- |
| L1 触发 | 什么时候开始追问 | `trigger_keywords`、`trigger_rules`、`applies_to_spectrum`（项目阶段向量窗口）、`applies_to_stage`、`applies_to_competition` |
| L2 目的 | 追问什么 | `probing_layers`（3 层递进）、`expected_evidence`、`counterfactual` |
| L3 表达 | 用什么口吻 | `tone_variants`：`cool` 默认 → `strict / humorous / warm / coaching / socratic` 五种重写 |

> L3 的设计目的是 **"语义不变、表达可变"**：高频策略（CS01/02/03/04/05/07/08/10）在代码里直接写死了 5 套手写文本；低频策略走 LLM 兜底（advisor/coach 在 system prompt 里按 `TONE_DESCRIPTORS` 风格指南即时改写 cool 版本）。

## 3. 内置 10 条策略（CS01–CS10）

| ID | 名称 | 一句话定位 | 主触发 |
| --- | --- | --- | --- |
| CS01 | 无竞争对手三层探测 | "蓝海"幻觉 → 隐形替代品 / 巨头入场 / 切换成本 | H6 + 关键词「无竞争 / 蓝海 / 没人做过」 |
| CS02 | 1% 市场份额幻觉 | "只要 1% 就够"→ 获客路径 / CAC-LTV / 前 100 用户 | H9 + H4 + 关键词「1% / 只要 / 中国人」 |
| CS03 | 技术门槛幻觉 | "壁垒极高"→ 复现时间 / 用户视角 / 资源缺口 | H7 + H12 + 关键词「专利 / 核心算法」 |
| CS04 | 需求证据缺失 | "我觉得很多人需要"→ 访谈数 / 付费意愿 / 行为证据 | H5 + 关键词「我觉得 / 应该 / 肯定」 |
| CS05 | 商业模式闭环断裂 | "先免费再变现"→ 价值传递 / 渠道单经济 / 变现时间表 | H1/H2/H3/H8 + 关键词「先免费 / 流量变现」 |
| CS06 | 里程碑过度乐观 | "三个月做完 MVP"→ 任务拆解 / 资源瓶颈 / Plan B | H10 + 关键词「快速上线 / 一个月内」 |
| CS07 | 合规伦理盲区 | 涉及隐私/医疗/数据 → 合规依据 / 数据处理 / 最坏情境 | H11 + 关键词「人脸 / 隐私 / 个人信息」 |
| CS08 | 定价无支撑 | 价格直接拍脑袋 → 价格敏感度 / 免费替代 / 锚定 | 关键词「定价 / 月费 / 售价」 + 缺乏对照 |
| CS09 | 创新点不可验证 | "技术领先 / SOTA"→ 实验设计 / 对照组 / 复现 | 关键词「SOTA / benchmark / 算法创新」 |
| CS10 | 市场口径混乱 | TAM/SAM/SOM 算成"全国人口×单价"→ 自下而上口径校验 | 关键词「市场规模 / 行业空间」 + 数字偏离 |

每条策略在 `_STRATEGY_EDGE_PREFS` / `_STRATEGY_FALLACY_PREFS` 里也声明了它**偏好哪些超图边类型 / 谬误标签**，参与 `select_probing_strategies` 的打分（见下一节）。

## 4. 评分函数：`select_probing_strategies`

```python
score = 0
score += len(关键词命中) * 2.0
score += len(触发规则命中) * 3.0          # 高权重
score += len(谬误标签命中) * 2.5
score += len(偏好边类型命中) * 1.8
score += 0.8 if 项目阶段匹配 else 0
score += 0.8 if 落在阶段向量窗口 else 0
```

最终按分数排序取前 `max_results` 条（默认 3）。返回字段如下：

| 字段 | 含义 |
| --- | --- |
| `strategy_id` | CS01–CS10 |
| `match_score` | 上面公式得到的总分 |
| `probing_layers` | 已按当轮 tone 重写过的 3 层追问 |
| `probing_layers_default` | 默认 cool 版本，便于前端对比展示 |
| `tone` / `tone_descriptor` | 实际使用的语气 + 风格描述 |
| `expected_evidence` | 学生需要补的证据清单 |
| `counterfactual` | 反事实假设问题 |
| `preferred_edge_types` | 偏好的超图边类型 |
| `matched_keywords / matched_rules / matched_edge_types` | 这次具体命中了哪些信号，便于审计 |
| `strategy_logic` | 一句话写明这条策略背后的逻辑名（如「广义竞争 + 隐形替代 + 迁移成本」） |

## 5. 语气解析：`resolve_tone_for_state`

```
priority:
  1) 学生当轮消息显式要求（"严肃一点 / 幽默一点 / 像审稿人 …"）→ explicit
  2) sticky：上一轮非 cool 的 tone 在该会话内继续保留若干轮 → sticky
  3) project_state.preferred_tone（教师在干预里设定的）→ project_state
  4) 兜底默认 → default = cool
  5) 强制覆盖：财务红线触发 → forced_strict / 学生情绪低落触发 → forced_warm
```

最终返回 `(tone, tone_origin)` 写入 state 后，会同时塞进：
- `agent_trace.preferred_tone` / `agent_trace.tone_origin`
- `agent_trace.competition.preferred_tone` / `agent_trace.competition.tone_origin`

便于前端 topbar 角标 + 测试脚本断言。

## 6. 评委角色卡（competition_judges.py）

数据落点：`apps/backend/config/competition_judges.json`
代码模型：

```python
@dataclass
class JudgePersona:
    id: str
    name: str
    archetype: str          # 激进型 VC / 技术专家 / 财务老炮 / 评审政府代表 …
    focus: list[str]        # 这位评委在意什么维度
    tone: str               # 默认 tone（可被学生显式覆盖）
    trigger_keywords: list[str]
    signature_questions: list[str]   # 几个标志性追问
    killer_metrics: list[str]        # "你必须给我数字"的关键指标
    typical_pitfalls: list[str]      # 常见学生踩坑
```

运行流程：

1. 进入 competition pipeline 时，在 system prompt 里**只放角色目录**（不放全文，避免 prompt 体积爆炸）。
2. `pick_judge(message, competition_type)` 优先匹配学生消息里的"请扮演 X / 切到 X 视角"，否则按 `default_by_competition[competition_type]` 给一个默认。
3. 命中的 `judge.id` 写到 `agent_trace.competition.active_judge`。
4. 命中的完整 persona 才被拼进当轮 system prompt（避免污染其它轮）。

## 7. Critic Agent：把上面所有信号收口成"反质询包"

`agents.py::critic_agent_*` 是把这些散信号整理成 LLM 可消费段落的最后一环：

```json
agent_trace.critic = {
  "counterfactual_questions": ["如果你的免费用户永远不付费 …"],
  "challenge_points": ["定价缺乏支付意愿测试"],
  "missing_evidence": [">=5 份用户访谈原话", "前 100 用户获取计划"],
  "logic_assessment": { ... }
}
```

写到 assistant_message 里时，模板会自动按 markdown：

```
### 反质询
- ❓ 如果你的免费用户永远不付费 …
### 你需要补的证据
- ≥5 份用户访谈原话（明确说"愿意每月花 X 元"）
- 前 100 用户获取计划（含具体渠道、单次成本）
```

## 8. Pressure Test Trace（压力测试追溯）

`pressure_test_trace` 是"高压追问"专属的诊断字段，主要在 `mode=competition` 下出现。结构示例：

```json
{
  "round": 3,
  "previous_chain": ["CS04", "CS01"],
  "next_pressure_layer": "数字化逼供",
  "logic_gaps": ["未给出 CAC 估算依据"],
  "expected_response_shape": "数字 + 出处 + 单位"
}
```

它的作用是让前端能展示"这是第 N 轮的压力测试，前面已经追到哪里了，本轮要把哪个洞往死里追"。

## 9. 关键 API / 字段对照

| 入口 | 路径 | 关键 input | 关键 output |
| --- | --- | --- | --- |
| 主对话 | `POST /api/dialogue/turn` | `mode`、`competition_type`、`message` | `agent_trace.critic` / `agent_trace.challenge_strategies` / `agent_trace.competition.active_judge` / `agent_trace.preferred_tone` / `pressure_test_trace` |
| SSE 流式 | `POST /api/dialogue/turn-stream` | 同上 | 流式增量；最后一个 `event=done` 携带相同 `agent_trace` |

## 10. 自测命令（带断言的回归脚本）

```bash
# 验证 6 种语气在同一会话里能被显式 / 隐式触发，且 tone_origin 标注正确
python -u apps/backend/scripts/test_final01_tone_library.py

# 验证 4 个评委角色卡能被消息里"请扮演 X"切换，active_judge 同步切
python -u apps/backend/scripts/test_final01_judges_bank.py

# 完整 6 轮合规 / 国际化 / 学术深度场景，间接验证 CS04 / CS07 / CS10 触发
python -u apps/backend/scripts/test_final01_case9.py
```

每个脚本输出 `regression_final01_*.json`，里面逐轮记录了：
- `triggered_rules`、`tone_origin`、`active_judge`、`preferred_tone`
- 关键词命中数 + 回复片段
- 是否通过断言

## 11. 设计要点摘录（可直接抄进答辩稿）

1. **三层结构互不绑死**：触发条件、追问目的、表达风格分别由 `trigger_*`、`probing_layers + counterfactual`、`tone_variants` 表达，可以单独迭代。
2. **关键词 + 规则 + 谬误 + 边类型 4 信号联合打分**，而不是单关键词命中——避免"提一句蓝海就触发 CS01"。
3. **tone 不改语义**：所有 `tone_variants[X]` 是同一句追问的不同重写，确保学生不会因为换了语气就丢掉原本要回答的硬问题。
4. **forced_strict / forced_warm 是兜底安全阀**：当财务出现红线（如 "1 元定价"）时强制切 strict；当学生连发 2 条"我做不下去了"时强制切 warm。
5. **active_judge 写入 trace** 让评委切换可被前端可视化、可被测试断言、也可被教师后台审计。
