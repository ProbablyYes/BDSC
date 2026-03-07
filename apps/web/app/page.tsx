import Link from "next/link";

export default function HomePage() {
  return (
    <main className="page">
      <section className="hero fade-up">
        <h1>创新创业智能体平台</h1>
        <p>教师端与学生端分离，支持文件分析、反馈回写、4 Agent 协同诊断与后续图谱扩展。</p>
      </section>

      <section className="grid">
        <article className="card role-card glow">
          <h2>学生端</h2>
          <p className="hint">上传文档、查看诊断、领取下一步唯一任务。</p>
          <Link href="/student">
            <button type="button">进入学生端</button>
          </Link>
        </article>

        <article className="card role-card glow">
          <h2>教师端</h2>
          <p className="hint">查看项目快照、回写反馈、运行教师助手并查看范例分类。</p>
          <Link href="/teacher">
            <button type="button">进入教师端</button>
          </Link>
        </article>
      </section>
    </main>
  );
}
