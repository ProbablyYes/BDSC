import Link from "next/link";

export default function HomePage() {
  return (
    <main className="page">
      <section className="hero fade-up">
        <h1>创新创业智能体平台</h1>
        <p>基于 RBAC 权限架构，严格区隔学生端、教师端与教务管理端。多智能体协同驱动全链路双创教学。</p>
      </section>

      <section className="grid">
        <article className="card role-card glow" style={{ gridColumn: "span 4" }}>
          <h2>学生端</h2>
          <p className="hint">沉浸式对话界面，支持理论学习、BP辅助生成、竞赛路演模拟与评分。</p>
          <Link href="/student">
            <button type="button">进入学生端</button>
          </Link>
        </article>

        <article className="card role-card glow" style={{ gridColumn: "span 4" }}>
          <h2>教师端</h2>
          <p className="hint">班级洞察、项目批改、能力映射与教学干预计划生成。</p>
          <Link href="/teacher">
            <button type="button">进入教师端</button>
          </Link>
        </article>

        <article className="card role-card glow" style={{ gridColumn: "span 4", borderColor: "rgba(224,112,112,0.3)" }}>
          <h2>管理员端</h2>
          <p className="hint">全局数据大盘、用户与权限管理、高频漏洞看板与安全日志。</p>
          <Link href="/admin">
            <button type="button" style={{ background: "linear-gradient(135deg, #e07070, #e0a84c)" }}>进入管理端</button>
          </Link>
        </article>
      </section>
    </main>
  );
}
