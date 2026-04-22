# BDSC - 创新创业全智能体平台

面向双创课程的师生协同系统，目标是实现：

- 学生端：上传 `PPT/PDF/计划书` 后自动分析、诊断、给出下一步任务。
- 教师端：查看项目快照、写回反馈、形成班级级洞察。
- 系统端：预留 `Neo4j Community` 接口，后续承接知识图谱与超图规则引擎。

## 当前目录结构

```txt
apps/
  backend/   # FastAPI + 诊断引擎 + 文档解析 + 项目状态存储
  web/       # Next.js 学生/教师协同界面
data/
  corpus/teacher_examples/      # 教师示例项目资料（请将范例放这里）
  uploads/student_submissions/  # 学生上传文件
  project_state/                # 项目状态与反馈快照
  graph_seed/                   # 图谱初始化数据
```

## 后端启动（FastAPI）

首次协作开发建议先初始化本地环境变量：

```bat
scripts\setup-backend-env.cmd
```

这会在 `apps/backend/` 下按 `.env.example -> .env` 复制一份本地配置模板。真实 `API Key` 不会进入 Git；如果团队需要共用同一个 key，请通过私下安全渠道分发后各自填入本地 `.env`。

```bash
cd apps/backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

可用接口：

- `POST /api/upload` 上传并分析文档
- `POST /api/analyze-text` 直接输入文本分析
- `POST /api/teacher-feedback` 教师回写反馈
- `GET /api/project/{project_id}` 查询项目快照
- `GET /api/teacher-examples` 查看教师示例资料目录状态

## 前端启动（Next.js）

```bash
cd apps/web
npm install
npm run dev
```

默认访问 `http://localhost:3000`，通过 `NEXT_PUBLIC_API_BASE` 连接后端 API。

## 一键启动（Windows）

在项目根目录运行：

```bat
scripts\dev-all.cmd
```

会自动拉起后端与前端两个窗口。

## 只做 Agent 调参（更快）

如果你主要在训练 Agent，不需要每次开前端：

```bat
scripts\agent-eval.cmd
```

它会批量跑 `apps/backend/eval/cases.sample.json`，方便你快速迭代规则和话术。

## 教师范例自动入库（metadata + 结构化案例）

```bat
scripts\ingest-teacher-examples.cmd
```

运行后将生成：
- `data/corpus/teacher_examples/metadata.csv`
- `data/graph_seed/case_structured/*.json`

## 下一步建议

1. 将教师范例计划书放入 `data/corpus/teacher_examples/`。
2. 增加“案例抽取 Agent”把范例转成图谱节点/超边。
3. 将当前规则引擎升级为你文档中的 H1-H15 全量校验。

## 教师范例分类建议

建议在 `data/corpus/teacher_examples/` 下按类别建子文件夹（已预创建）：

- `环境保护`
- `科技创新`
- `医疗健康`
- `教育服务`
- `乡村振兴`
- `智能制造`
- `文旅文创`
- `社会治理`
- `社会公益`
- `金融经济`
- `其他`

放文件时直接放入对应类别目录即可，后端会按目录名当作 `category` 返回给前端。
