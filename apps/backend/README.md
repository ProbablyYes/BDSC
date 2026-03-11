# Backend

## Run

首次启动前，先在 `apps/backend` 下准备本地环境变量：

```bash
copy .env.example .env
```

或在仓库根目录直接运行：

```bat
scripts\setup-backend-env.cmd
```

说明：
- `.env.example` 是共享模板，会提交到 Git。
- `.env` 是本地真实配置，会被 `.gitignore` 忽略。
- 如果要启用真实 LLM，请把你的 `LLM_API_KEY` 填到本地 `.env`；不要把真实 key 提交到仓库。

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

> 如果看到 `tool.uv.dev-dependencies` 的 warning，说明是旧字段提示。项目已升级为 `dependency-groups.dev`，可忽略旧终端中残留提示。

## 当前内置 4 个 Agent

1. `student_learning` 学习导师
2. `project_coach` 项目教练
3. `competition_advisor` 竞赛顾问
4. `instructor_assistant` 教师助手

通过 `POST /api/agent/run` 可以单独运行某个 Agent，`agent_type=all` 则一次运行全部。

## Current APIs

- `GET /health`
- `POST /api/analyze-text`（自动运行 all agents，并回写项目状态）
- `POST /api/upload` (supports `txt/md/docx/pdf/pptx`)
- `POST /api/teacher-feedback`
- `GET /api/project/{project_id}`
- `GET /api/teacher-examples`（按分类目录返回教师范例）
- `GET /api/teacher/dashboard`（教师画像：类别分布/高风险项目/规则命中）
- `GET /api/teacher/project/{project_id}/evidence`（单项目证据链与rubric覆盖）
- `GET /api/teacher/compare`（历史基线 vs 本班现状对比 + 干预建议）
- `POST /api/agent/run`（运行指定 agent）

## Agent 调试（无需启动前端）

```bash
uv run python eval/run_eval.py
```

它会读取 `eval/cases.sample.json` 批量跑 4 个 Agent，输出触发规则和下一步任务，适合快速调参。

## 教师范例入库流水线（metadata + 结构化抽取）

```bash
uv run python -m ingest.build_metadata
uv run python -m ingest.extract_case_struct
```

建议高质量模式（先做质量闸门，再做增强抽取）：

```bash
# 1) 深度扫描（非 --fast），生成质量等级与失败清单
uv run python -m ingest.build_metadata --max-parse-mb 25

# 2) 仅抽取 A/B 质量文档；低质量样本写入 rejections.csv
uv run python -m ingest.extract_case_struct --llm --llm-verify --min-quality B
```

启用千问（SiliconFlow OpenAI兼容）做增强抽取：

```bash
# .env 中配置
# LLM_PROVIDER=qwen
# LLM_BASE_URL=https://api.siliconflow.cn/v1
# LLM_API_KEY=sk-...
# LLM_FAST_MODEL=Qwen/Qwen2.5-14B-Instruct
uv run python -m ingest.extract_case_struct --llm --max-cases 2
```

一键执行：

```bash
uv run python -m ingest.pipeline
```

产物目录：
- `data/corpus/teacher_examples/metadata.csv`
- `data/graph_seed/case_structured/`

失败清单：
- `data/corpus/teacher_examples/parse_failures.csv`（扫描件/超大文件/解析失败）
- `data/graph_seed/case_structured/rejections.csv`（质量闸门拦截/抽取失败，建议回改后重跑）

## Neo4j 最小图谱入库（Step 2）

```bash
uv run python -m kg.import_to_neo4j
uv run python -m kg.query_category_patterns
```

最小节点：`Project/Category/PainPoint/Solution/Market/RiskRule`  
最小关系：`BELONGS_TO/HAS_PAIN/HAS_SOLUTION/HITS_RULE/HAS_EVIDENCE/EVALUATED_BY`

## Agent 接入案例检索（Step 3）

- `project_coach`：按类别返回参考案例
- `competition_advisor`：返回基准案例列表
- `instructor_assistant`：返回类别级样本分布
