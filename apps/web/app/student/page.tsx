"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export default function StudentPage() {
  const [projectId, setProjectId] = useState("demo-project-001");
  const [studentId, setStudentId] = useState("student-001");
  const [mode, setMode] = useState("coursework");
  const [textInput, setTextInput] = useState("");
  const [response, setResponse] = useState("等待学生端分析结果...");

  async function analyzeText(event: FormEvent) {
    event.preventDefault();
    const resp = await fetch(`${API_BASE}/api/analyze-text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, student_id: studentId, input_text: textInput, mode }),
    });
    const data = await resp.json();
    setResponse(JSON.stringify(data, null, 2));
  }

  async function uploadFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    form.set("project_id", projectId);
    form.set("student_id", studentId);
    form.set("mode", mode);
    const resp = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: form });
    const data = await resp.json();
    setResponse(JSON.stringify(data, null, 2));
  }

  return (
    <main className="page">
      <section className="hero fade-up">
        <div className="nav">
          <Link href="/" className="nav-link">
            返回首页
          </Link>
          <Link href="/teacher" className="nav-link">
            去教师端
          </Link>
        </div>
        <h1>学生端工作台</h1>
        <p>上传计划书/PDF/PPT，触发4个 Agent 协同分析，获取下一步唯一任务。</p>
      </section>

      <section className="grid">
        <article className="card glow">
          <h2>项目信息</h2>
          <label>项目 ID</label>
          <input value={projectId} onChange={(e) => setProjectId(e.target.value)} />
          <label>学生 ID</label>
          <input value={studentId} onChange={(e) => setStudentId(e.target.value)} />
          <label>模式</label>
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="coursework">课程作业辅导</option>
            <option value="competition">竞赛冲刺辅导</option>
          </select>
        </article>

        <article className="card">
          <h2>文本分析</h2>
          <form onSubmit={analyzeText}>
            <label>项目描述</label>
            <textarea
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              placeholder="描述你的项目、目标用户、价值主张和目前困惑。"
            />
            <button type="submit">提交文本分析</button>
          </form>
        </article>

        <article className="card full">
          <h2>文件上传分析</h2>
          <form onSubmit={uploadFile}>
            <label>支持 docx / pdf / pptx / txt / md</label>
            <input type="file" name="file" required />
            <button type="submit">上传并分析</button>
          </form>
        </article>

        <article className="card full">
          <h2>分析输出</h2>
          <pre>{response}</pre>
        </article>
      </section>
    </main>
  );
}
