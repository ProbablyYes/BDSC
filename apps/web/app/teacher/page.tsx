"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export default function TeacherPage() {
  const [projectId, setProjectId] = useState("demo-project-001");
  const [teacherId, setTeacherId] = useState("teacher-001");
  const [feedback, setFeedback] = useState("");
  const [response, setResponse] = useState("等待教师端数据...");

  async function loadSnapshot() {
    const resp = await fetch(`${API_BASE}/api/project/${projectId}`);
    const data = await resp.json();
    setResponse(JSON.stringify(data, null, 2));
  }

  async function loadExamples() {
    const resp = await fetch(`${API_BASE}/api/teacher-examples`);
    const data = await resp.json();
    setResponse(JSON.stringify(data, null, 2));
  }

  async function submitFeedback(event: FormEvent) {
    event.preventDefault();
    const resp = await fetch(`${API_BASE}/api/teacher-feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        teacher_id: teacherId,
        comment: feedback,
        focus_tags: ["evidence", "feasibility"],
      }),
    });
    const data = await resp.json();
    setResponse(JSON.stringify(data, null, 2));
  }

  async function runAgent() {
    const resp = await fetch(`${API_BASE}/api/agent/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        agent_type: "instructor_assistant",
      }),
    });
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
          <Link href="/student" className="nav-link">
            去学生端
          </Link>
        </div>
        <h1>教师端控制台</h1>
        <p>查看项目快照、写回反馈、检查教师范例分类以及运行教师助手 Agent。</p>
      </section>

      <section className="grid">
        <article className="card glow">
          <h2>项目与教师信息</h2>
          <label>项目 ID</label>
          <input value={projectId} onChange={(e) => setProjectId(e.target.value)} />
          <label>教师 ID</label>
          <input value={teacherId} onChange={(e) => setTeacherId(e.target.value)} />
          <button type="button" onClick={loadSnapshot}>
            查看项目快照
          </button>
          <button type="button" onClick={runAgent}>
            运行教师助手 Agent
          </button>
          <button type="button" onClick={loadExamples}>
            查看教师范例分类
          </button>
        </article>

        <article className="card">
          <h2>写回反馈</h2>
          <form onSubmit={submitFeedback}>
            <label>反馈内容</label>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="例如：先修正渠道可达性，再补充支付意愿证据。"
            />
            <button type="submit">提交反馈</button>
          </form>
        </article>

        <article className="card full">
          <h2>教师端输出</h2>
          <pre>{response}</pre>
        </article>
      </section>
    </main>
  );
}
