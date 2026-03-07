# Backend

## Run

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

一键执行：

```bash
uv run python -m ingest.pipeline
```

产物目录：
- `data/corpus/teacher_examples/metadata.csv`
- `data/graph_seed/case_structured/`
