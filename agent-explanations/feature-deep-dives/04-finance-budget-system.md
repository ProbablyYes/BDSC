# 财务预算系统（BudgetStorage + finance_guard + finance_analyst）

> 对应主索引：`../README.md`、外部行为见 `../business-model-finance-intervention-and-market-sizing.md`
> 本篇是上面两篇的**实现层**补充。
> 对应代码：
> - `apps/backend/app/services/budget_storage.py` —— 落盘 + 现金流重算
> - `apps/backend/app/services/revenue_models.py` —— 7 种收入 Pattern + key_levers
> - `apps/backend/app/services/finance_pattern_formulas.py` —— Pattern 杠杆 / 三档情景乘数
> - `apps/backend/app/services/finance_signal_extractor.py` —— 从对话抽数字到预算
> - `apps/backend/app/services/finance_guard.py` —— 旁路守望 + 红黄绿提醒卡片
> - `apps/backend/app/services/finance_analyst.py` —— 单位经济 / 定价框架 / 合理性判分
> - `apps/backend/app/services/finance_report_service.py` —— 完整财务报告（落 `data/finance_reports/`）

## 1. 一图流：财务预算的 4 个入口、3 条数据流

```
┌────────────── 入口 ──────────────┐    ┌────────────── 数据流 ──────────────┐
│ ① 学生在 /budget 工作台手填       │ →  │ A. 写预算 JSON                       │
│    POST /api/budget/{uid}/{pid}  │    │    data/budgets/{uid}/{pid}.json     │
├──────────────────────────────────┤    ├──────────────────────────────────────┤
│ ② 学生 @AI: "帮我把单位经济算一下" │ →  │ B. 旁路守望 finance_guard.scan_message│
│    走 dialogue/turn 时被钩走     │    │    生成红/黄卡片 → agent_trace        │
├──────────────────────────────────┤    ├──────────────────────────────────────┤
│ ③ 学生发消息 "月费 49 元月活 5000" │ →  │ C. finance_signal_extractor          │
│    走 dialogue/turn               │    │    抽 7 种 Pattern → 写回预算         │
├──────────────────────────────────┤    │    自动 compute_cash_flow 重算         │
│ ④ 学生点 "生成完整财务报告"       │ →  │                                       │
│    POST /api/finance-report/...   │    │ D. finance_report_service.build_report│
│                                   │    │    落 data/finance_reports/{pid}.json│
└──────────────────────────────────┘    └──────────────────────────────────────┘
```

## 2. 预算 JSON 数据模型

文件：`data/budgets/{user_id}/{plan_id}.json`（每个用户一个文件夹，每个方案一个 JSON）

```json
{
  "plan_id": "8 字符 hex",
  "user_id": "...",
  "name": "LegalScan 商业方案 v3",
  "purpose": "quick | competition | business | coursework",
  "visible_tabs": ["cost", "biz", "comp", "compare", "fund"],
  "version": 1,
  "currency": "CNY",
  "created_at": "ISO",
  "updated_at": "ISO",

  "project_costs": { "categories": [
    { "name": "技术开发", "items": [
      { "name": "云服务器", "unit_price": 0, "quantity": 12, "total": 0,
        "note": "按月计费×12", "cost_type": "monthly" }
    ] }
  ] },

  "business_finance": {
    "revenue_streams": [
      {
        "name": "基础订阅",
        "pattern_key": "subscription",
        "inputs": { "monthly_users": 5000, "price": 49, "conversion_rate": 0.04, ... },
        "monthly_revenue": 9800,
        "active_units": 200,
        "_ai_meta": { "ai_created": true, "fields": { "price": { "prev_value": null, ... } } }
      }
    ],
    "fixed_costs_monthly": 30000,
    "variable_cost_per_user": 0,
    "growth_rate_monthly": 0.10,
    "scenario_models": { "conservative": {...}, "baseline": {...}, "optimistic": {...} },
    "scenario_results": {
      "baseline": {
        "monthly_revenue_base": 9800,
        "monthly_users_base": 200,
        "annual_revenue": 144000,
        "annual_cost": 360000,
        "annual_net": -216000,
        "breakeven_month": null,
        "cash_flow_projection": [ {month, revenue, cost, net, cumulative}, ... 12 ]
      },
      "conservative": {...}, "optimistic": {...}
    },
    "key_levers": ["price", "monthly_users", "conversion_rate"],
    "pattern_levers": { "subscription": [ {field, label, scenarios:{...}}, ... ] }
  },

  "competition_budget": {
    "items": [{ "name": "参赛报名费", "amount": 0 }, ...],
    "stages": [{ "name": "初赛", "items": [...] }, ...],
    "funding_sources": [{ "name": "赛事奖金", "amount": 0 }, ...]
  },

  "funding_plan": {
    "startup_capital_needed": 0,
    "sources": [],
    "monthly_gap": [],
    "fundraising_notes": ""
  },

  "ai_suggestions": [ { "timestamp": "...", "suggestions": { ... } } ],
  "summary": {
    "project_cost_total": 0,
    "competition_cost_total": 0,
    "total_investment": 0,
    "baseline_monthly_revenue": 9800,
    "breakeven_baseline": null,
    "health_score": 64,
    "funding_gap": 216000
  }
}
```

字段写得详细一点的目的：前端 `apps/web/app/budget/BudgetContent.tsx` 的所有 Tab 都直接绑这一份 JSON，所以这份 schema 实际上就是 UI 状态。

## 3. 4 种 Purpose 模板（决定显示哪些 Tab）

| purpose | 标签 | 默认成本类目 | 默认 Tab |
| --- | --- | --- | --- |
| `quick` | 快速估算 | 极简 3 类 | `cost` |
| `competition` | 比赛预算 | 极简 3 类 + 比赛专项 | `cost`, `comp`, `fund` |
| `business` | 商业计划 | 完整 4 类 + 收入流 + 情景 | `cost`, `biz`, `comp`, `compare`, `fund` |
| `coursework` | 课程作业 | 完整 4 类（无比赛专项） | `cost`, `biz`, `compare` |

来源：`PURPOSE_META`（`budget_storage.py` 第 21–42 行）。

## 4. 7 种收入 Pattern（revenue_models.py）

| key | 适用 | 关键字段 (key_levers) |
| --- | --- | --- |
| `subscription` | SaaS / 会员 / 订阅 | `monthly_users`, `price`, `conversion_rate` |
| `transaction` | 单次购买 / 复购 | `customers_per_month`, `price_per_order`, `repeat_per_month` |
| `project_b2b` | 大客户项目制 | `contracts_per_month`, `contract_value`, `delivery_months`, `renewal_rate` |
| `platform_commission` | 平台撮合 | `gmv_monthly`, `take_rate` |
| `hardware_sales` | 智能硬件 | `units_per_month`, `unit_price`, `bom_cost` |
| `grant_funded` | 公益资助 / 政府购买 | `active_grants`, `grant_amount_yearly`, `renewal_rate` |
| `donation` | 捐赠 / CSR | `donors_per_month`, `avg_donation`, `retention_rate` |

每个 Pattern 都自带：
- `compute_monthly(inputs)` → 月营收
- `active_users(inputs)` → 活跃载体数（用来算 variable_cost）
- `suit_for` 标签和 `track_hint`（`recommend_patterns` 按学生项目认知推荐）
- 公式人话解释（前端 tooltip）

> 关键设计：一个项目可以**同时挂多条不同 Pattern 的 stream**（公益项目常见：`grant_funded` + `donation` + `subscription`）。最终现金流是所有 stream 之和。

## 5. 三档情景模拟（compute_cash_flow）

```
For scenario in [conservative, baseline, optimistic]:
    For each stream:
        # pattern-aware：按每条 stream 的 Pattern 杠杆乘以该情景的 multiplier
        # 而不是一刀切全局 ×0.75/×1.0/×1.25
        for lever in get_pattern_levers(stream.pattern_key):
            inputs[lever.field] *= lever.scenarios[scenario_key]
        rev_stream = compute_stream_monthly_revenue(stream)

    revenue_base = sum(rev_stream)
    For m in 1..12:
        factor = (1 + growth_rate) ** (m - 1)
        revenue_m = revenue_base * factor
        cost_m    = fixed + variable * users_m
        net_m     = revenue_m - cost_m
        cumulative += net_m
        if cumulative >= 0 and m > 1: breakeven_month = m
    annual_revenue = sum(...)
    ...
```

输出全部塞进 `business_finance.scenario_results[scenario_key]`，前端三档 Tab 直接读。

> Pattern 杠杆 (`finance_pattern_formulas.get_pattern_levers`) 让"悲观情景"对 SaaS 是『留存 ↓ + 转化 ↓』，对 hardware_sales 是『单价 ↓ + 销量 ↓』，模拟更贴合真实业务。

## 6. finance_guard：旁路守望 + 红黄绿提醒卡片

每次走 `/api/dialogue/turn` 时，后端会同步调用 `finance_guard.scan_message`（< 500ms，纯本地正则 + 计算，不调 LLM）。

### 6.1 触发 → 抽假设 → 评级 三步

1. **触发**：`detect_triggers(text)` 用 7 类关键词（pricing / unit_econ / market / cashflow / funding / cost / nonprofit）+ 强信号定价正则（`¥XXX` / `XXX 元/月`）+ 弱信号定价（`XXX 元` 但需要附近出现"定价 / 收费 / 月付"等正向词，且不出现"CAC / 成本"等负向词）。
2. **抽假设**：把消息里的数字（月费、CAC、毛利、留存、付费率、月活）按窗口规则抽到一个 `assumptions` dict。
3. **三模块速判**：
   - `analyze_unit_economics` → CAC / LTV / Payback / LTV/CAC 比
   - `recommend_pricing_framework` → 是否存在"价格无支撑"
   - `evaluate_rationality` → 与行业基准的偏离度
   - 若任意一项命中红线 → 这条卡片 `verdict.level = "red"`，黄线 → `"amber"`，全绿 → 整个 guard 不打扰。

### 6.2 输出结构

```json
agent_trace.finance_guard = {
  "triggered_tags": ["pricing", "unit_econ"],
  "assumptions": { "price": 999, "cac": 1100, "ltv": 8000, ... },
  "cards": [
    {
      "kind": "unit_economics",
      "verdict": { "level": "amber", "reason": "LTV/CAC = 7.3，但 Payback = 9 个月偏长" },
      "metrics": { "ltv_cac": 7.3, "payback_months": 9 },
      "asks": ["把 CAC 拉到 600 以下", "或者把月费抬到 1299"]
    }
  ]
}
```

学生端会把红 / 黄卡片渲染在回复区右上角，并在 chat 主消息里追加一段「财务提醒」。`forced_strict` 也是在这里被触发——任意一张红卡片都会强制把这一轮 tone 切到 strict。

### 6.3 全流程不调 LLM，失败也不会阻塞

```python
try:
    return scan_message(...)
except Exception as exc:
    logger.warning("finance_guard.scan_message failed silently: %s", exc)
    return {"cards": []}
```

设计目标：财务模块永远不能因为一行解析错挂掉主对话链。

## 7. finance_signal_extractor：把消息内容写进预算

`extract_finance_signals(text, history) → {primary_pattern, pattern_inputs, summary}`

- 在 7 种 Pattern 里选最匹配的一种；
- 把可识别的数字塞进 `pattern_inputs[primary_pattern]`；
- 通过 `apply_signals_to_budget(budget, signals)` 写入 `business_finance.revenue_streams[0]`，并在 `_ai_meta.fields` 里记下 `prev_value`，让学生可以一键回滚（`POST /api/budget/{uid}/{pid}/ai-rollback`）。

测试可见：`apps/backend/scripts/test_finance_extractor.py` 7 个 case 覆盖 7 种 Pattern。

## 8. finance_report_service：完整财务报告

落盘：`data/finance_reports/{project_id}.json`

结构（节选）：

```json
{
  "project_id": "...",
  "scenario_id": "v3-2026-04-24",
  "industry_template": "saas_china",
  "sections": {
    "executive_summary": "...",
    "unit_economics": { "ltv": 8000, "cac": 650, "payback_months": 4.5, "ltv_cac": 12.3, "verdict": "..." },
    "pricing": { "framework": "value-based", "anchor": "299/999/1999", "issues": [...] },
    "cash_flow": { "month_to_breakeven": 14, "runway_months": 18, ... },
    "sensitivity": { "biggest_lever": "retention", ... },
    "funding_plan": { "stage": "Pre-A", "target": 6_000_000, "use_of_funds": [...] },
    "risk_warnings": [...]
  },
  "evidence_links": [
    { "claim": "ARPU=480", "source": "对话第 2 轮", "snippet": "..." }
  ]
}
```

回归脚本 `apps/backend/scripts/test_final01_finance_report.py` 直接 import service，跨多个行业模板验证生成结构 + 数字。

## 9. API 全景

### 9.1 预算

| 路径 | 用途 |
| --- | --- |
| `GET /api/budget/purposes` | 4 种 purpose 元数据（label / desc / visible_tabs） |
| `GET /api/budget/revenue-patterns?user_id=` | 7 种 Pattern 元数据 + 推荐列表 |
| `GET /api/budget/plans/{uid}` | 列出该用户所有方案 |
| `POST /api/budget/plans/{uid}` | 新建方案（按 purpose 选模板） |
| `DELETE /api/budget/plans/{uid}/{pid}` | 删方案 |
| `GET /api/budget/{uid}/{pid}` | 加载方案 |
| `PUT /api/budget/{uid}/{pid}` | 保存方案（自动重算 cash flow） |
| `POST /api/budget/{uid}/{pid}/ai-suggest` | 让 LLM 给出诊断 + 模板 + 答辩稿 + FAQ |
| `POST /api/budget/{uid}/{pid}/ai-chat` | 在工作台里跟财务顾问 AI 对话 |
| `POST /api/budget/{uid}/{pid}/ai-rollback` | 回滚 AI 自动写入字段 |

### 9.2 财务报告

| 路径 | 用途 |
| --- | --- |
| `POST /api/finance-report/{project_id}/generate` | 触发完整报告生成 |
| `GET /api/finance-report/{project_id}` | 拉最新报告 |
| `GET /api/finance-report/{project_id}/history` | 列出历史版本 |

## 10. 自测命令

```powershell
# 单元: 7 种 pattern 抽取
.venv\Scripts\python.exe apps\backend\scripts\test_finance_extractor.py

# 端到端: 写预算 → 重算现金流 → 跑 unit economics
.venv\Scripts\python.exe apps\backend\scripts\test_finance_e2e.py

# 走 HTTP: 6 轮财务对话 + 旁路守望卡片
.venv\Scripts\python.exe apps\backend\scripts\test_final01_finance_dialogue.py

# 直接打底层 service: 多行业模板下的报告
.venv\Scripts\python.exe apps\backend\scripts\test_final01_finance_report.py
```

## 11. 设计要点摘录（可直接抄进答辩稿）

1. **预算与对话双向打通**：学生在预算工作台改字段会写盘 → 下一轮对话的 `finance_guard` 会读最新字段；学生在对话里说"月费 49 元"会被抽到预算 → 工作台立即看到新 stream。
2. **Pattern-aware 三档情景**：不再"全局 ×0.75/×1.25"，而是按每条 stream 的关键杠杆乘以该 Pattern 自己的情景倍数，模拟更接近真实业务。
3. **旁路守望永不阻塞**：`finance_guard` 异常静默 + 全程纯本地，主链路安全。
4. **AI 回滚机制**：每个 AI 自动写入的字段都附 `_ai_meta.prev_value`，学生一键退回。
5. **多 Purpose 模板隔离 UI 复杂度**：快速估算只看一个 Tab，商业方案打开 5 个 Tab，给不同阶段的学生提供不同的认知负载。
