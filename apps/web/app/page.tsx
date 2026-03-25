import Link from "next/link";

export default function HomePage() {
  const signals = [
    "项目演进",
    "团队差异",
    "过程诊断",
    "文件反馈",
    "能力映射",
    "教学干预",
    "权限治理",
    "平台日志",
  ];
  const roles = [
    {
      title: "学生端",
      href: "/student",
      badge: "Student Workspace",
      desc: "围绕项目迭代、文件上传、智能陪练与竞赛准备，把“学、做、改”组织成一个连续而清晰的成长界面。",
      points: ["项目推进与智能问答", "文档上传与即时诊断", "连续迭代中的成长反馈"],
      icon: "◉",
      tone: "student",
      cta: "进入学生端",
      metrics: ["成长轨迹", "文件诊断", "作品打磨"],
    },
    {
      title: "教师端",
      href: "/teacher",
      badge: "Teaching Studio",
      desc: "从总览、团队、学生到单项目演进，教师可以把分散的学习过程重新看成一张有结构、可解释的教学地图。",
      points: ["团队洞察与学生对比", "项目过程追踪与批改", "教学干预与能力分析"],
      icon: "△",
      tone: "teacher",
      cta: "进入教师端",
      metrics: ["团队洞察", "过程追踪", "教学启发"],
    },
    {
      title: "管理员端",
      href: "/admin",
      badge: "Admin Console",
      desc: "聚合平台治理、权限、风险与运行状态，让平台既有产品质感，也具备课程运行所需的稳定与秩序。",
      points: ["权限与账号管理", "全局运行看板", "安全与日志审计"],
      icon: "□",
      tone: "admin",
      cta: "进入管理端",
      metrics: ["权限治理", "运行监控", "安全审计"],
    },
  ];
  return (
    <main className="home-page">
      <div className="home-bg" aria-hidden="true">
        <span className="home-gradient-wash" />
        <span className="home-light-beam home-light-beam-a" />
        <span className="home-light-beam home-light-beam-b" />
        <span className="home-orb home-orb-a" />
        <span className="home-orb home-orb-b" />
        <span className="home-orb home-orb-c" />
        <span className="home-particle home-particle-a" />
        <span className="home-particle home-particle-b" />
        <span className="home-particle home-particle-c" />
        <span className="home-particle home-particle-d" />
        <span className="home-particle home-particle-e" />
        <span className="home-grid-lines" />
      </div>

      <header className="home-nav fade-up">
        <Link href="/" className="home-nav-brand">
          <span className="home-nav-brand-mark" />
          <span>VentureCheck</span>
        </Link>

        <nav className="home-nav-links" aria-label="home sections">
          <a href="#home-roles" className="home-nav-anchor">三端入口</a>
          <a href="#home-story" className="home-nav-anchor">平台理念</a>
        </nav>

        <div className="home-nav-actions">
          <Link href="/auth/reset-password" className="home-nav-btn home-nav-btn-soft">
            修改密码
          </Link>
          <Link href="/auth/login" className="home-nav-btn home-nav-btn-ghost">
            登录
          </Link>
          <Link href="/auth/register" className="home-nav-btn home-nav-btn-primary">
            注册
          </Link>
        </div>
      </header>

      <section className="home-hero fade-up">
        <div className="home-hero-copy">
          <div className="home-kicker">VentureCheck Platform</div>
          <h1>创检官VentureCheck</h1>
          <p className="home-hero-text">
            面向学生、教师与管理员的三端协同空间。它不是单纯把功能入口摆在一起，而是把项目成长、教学判断与平台治理放进同一套连续的界面语言里。
          </p>
          <p className="home-hero-subtext">
            学生看到的是作品如何一步步变好，教师看到的是问题如何被定位与解释，管理员看到的是整个平台如何稳定运行。
          </p>

          <div className="home-hero-actions">
            <Link href="/auth/register" className="home-hero-action home-hero-action-primary">
              创建账号
            </Link>
            <Link href="/auth/login" className="home-hero-action home-hero-action-secondary">
              立即登录
            </Link>
          </div>

          <div className="home-hero-action-note">
            右上角提供登录、注册、修改密码入口；学生与教师登录后将进入各自的工作空间与个人中心。
          </div>

          <div className="home-hero-pills">
            <span className="home-pill">双创教学</span>
            <span className="home-pill">过程分析</span>
            <span className="home-pill">智能反馈</span>
            <span className="home-pill">角色分层</span>
          </div>

          <div className="home-hero-stats">
            <div className="home-stat-card">
              <strong>3 端入口</strong>
              <span>学生、教师、管理员</span>
            </div>
            <div className="home-stat-card">
              <strong>全流程</strong>
              <span>从提交到诊断与干预</span>
            </div>
            <div className="home-stat-card">
              <strong>可追踪</strong>
              <span>项目演进、团队差异、平台运行</span>
            </div>
          </div>
        </div>

        <div className="home-stage">
          <div className="home-mockup">
            <div className="home-mockup-chrome">
              <span className="home-mockup-dot" style={{background:"#ff5f57"}} />
              <span className="home-mockup-dot" style={{background:"#febc2e"}} />
              <span className="home-mockup-dot" style={{background:"#28c840"}} />
              <span className="home-mockup-chrome-title">VentureCheck Console</span>
            </div>

            <div className="home-mockup-body">
              <aside className="home-mockup-side">
                <div className="home-mockup-side-brand">VA</div>
                <span className="home-mockup-side-item active" />
                <span className="home-mockup-side-item" />
                <span className="home-mockup-side-item" />
                <span className="home-mockup-side-item" />
              </aside>

              <div className="home-mockup-main">
                <div className="home-mockup-topbar">
                  <strong>三端协同控制台</strong>
                  <div className="home-mockup-status"><span className="home-mockup-status-dot" />在线</div>
                </div>

                <div className="home-mockup-flow">
                  <div className="home-mockup-flow-node hm-node-s">
                    <span className="home-mockup-flow-label">学生端</span>
                    <strong>上传与修订</strong>
                  </div>
                  <svg className="home-mockup-flow-arrow" viewBox="0 0 48 24"><path d="M0 12h38M32 4l10 8-10 8" fill="none" stroke="rgba(115,204,255,0.5)" strokeWidth="2" /></svg>
                  <div className="home-mockup-flow-node hm-node-t">
                    <span className="home-mockup-flow-label">教师端</span>
                    <strong>分析与干预</strong>
                  </div>
                  <svg className="home-mockup-flow-arrow" viewBox="0 0 48 24"><path d="M0 12h38M32 4l10 8-10 8" fill="none" stroke="rgba(232,168,76,0.4)" strokeWidth="2" /></svg>
                  <div className="home-mockup-flow-node hm-node-a">
                    <span className="home-mockup-flow-label">管理员端</span>
                    <strong>治理与监控</strong>
                  </div>
                </div>

                <div className="home-mockup-panels">
                  <div className="home-mockup-panel">
                    <div className="home-mockup-panel-head">过程信号</div>
                    <div className="home-mockup-feed">
                      <div className="home-mockup-feed-row"><span className="hm-tag hm-tag-s">学生</span><span>项目文件上传后即时生成诊断与风险提示</span></div>
                      <div className="home-mockup-feed-row"><span className="hm-tag hm-tag-t">教师</span><span>团队对比与学生变化自动聚合</span></div>
                      <div className="home-mockup-feed-row"><span className="hm-tag hm-tag-a">管理</span><span>权限与运行态势集中呈现</span></div>
                    </div>
                  </div>
                  <div className="home-mockup-panel">
                    <div className="home-mockup-panel-head">数据脉冲</div>
                    <div className="home-mockup-pulse">
                      <span className="home-mockup-pulse-bar" /><span className="home-mockup-pulse-bar" /><span className="home-mockup-pulse-bar" />
                      <span className="home-mockup-pulse-bar" /><span className="home-mockup-pulse-bar" /><span className="home-mockup-pulse-bar" /><span className="home-mockup-pulse-bar" />
                    </div>
                    <div className="home-mockup-mini-kpis">
                      <div><strong>学习过程</strong><span>上传 / 修订 / 评分</span></div>
                      <div><strong>教学判断</strong><span>差异 / 风险 / 启发</span></div>
                      <div><strong>平台治理</strong><span>权限 / 日志 / 状态</span></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="home-signal-band fade-up" aria-label="platform signals">
        <div className="home-signal-row home-signal-row-a">
          {[...signals, ...signals].map((item, index) => (
            <span key={`a-${index}`} className="home-signal-chip">
              {item}
            </span>
          ))}
        </div>
        <div className="home-signal-row home-signal-row-b">
          {[...signals.slice().reverse(), ...signals.slice().reverse()].map((item, index) => (
            <span key={`b-${index}`} className="home-signal-chip home-signal-chip-soft">
              {item}
            </span>
          ))}
        </div>
      </section>

      <section id="home-roles" className="home-role-grid">
        {/* 三端连线 SVG */}
        <div className="home-role-network" aria-hidden="true">
          <svg viewBox="0 0 1200 40" preserveAspectRatio="none">
            <path d="M 200 20 Q 400 0, 600 20" stroke="url(#rlg)" strokeWidth="1.5" fill="none" opacity="0.5" />
            <path d="M 600 20 Q 800 0, 1000 20" stroke="url(#rlg)" strokeWidth="1.5" fill="none" opacity="0.5" />
            <circle cx="200" cy="20" r="3" fill="rgba(107,138,255,0.6)" />
            <circle cx="600" cy="20" r="3" fill="rgba(115,204,255,0.6)" />
            <circle cx="1000" cy="20" r="3" fill="rgba(232,168,76,0.6)" />
            <defs><linearGradient id="rlg" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="rgba(107,138,255,0.5)" /><stop offset="50%" stopColor="rgba(115,204,255,0.5)" /><stop offset="100%" stopColor="rgba(232,168,76,0.5)" />
            </linearGradient></defs>
          </svg>
        </div>

        {roles.map((role, index) => (
          <article
            key={role.title}
            className={`home-role-card home-role-card-${role.tone} fade-up`}
            style={{ animationDelay: `${index * 0.1}s` }}
          >
            {/* 序号 + 轨道装饰 */}
            <div className="home-role-topline">
              <span className="home-role-index">0{index + 1}</span>
              <span className={`home-role-orbit home-role-orbit-${role.tone}`} />
            </div>

            <div className="home-role-head">
              <span className="home-role-icon">{role.icon}</span>
              <span className="home-role-badge">{role.badge}</span>
            </div>

            <h2>{role.title}</h2>
            <p className="home-role-desc">{role.desc}</p>

            <div className="home-role-list">
              {role.points.map((point) => (
                <div key={point} className="home-role-point">
                  <span className="home-role-point-dot" />
                  <span>{point}</span>
                </div>
              ))}
            </div>

            <div className="home-role-metrics">
              {role.metrics.map((metric) => (
                <span key={metric} className="home-role-metric">{metric}</span>
              ))}
            </div>

            {/* 迷你预览线条 */}
            <div className="home-role-preview">
              <span className="home-role-preview-line rl-a" /><span className="home-role-preview-line rl-b" /><span className="home-role-preview-line rl-c" />
            </div>

            <Link href={role.href} className="home-role-link">
              <span>{role.cta}</span>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{marginLeft:6}}><path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </Link>
          </article>
        ))}
      </section>

      <section id="home-story" className="home-story">
        <div className="home-story-card home-story-large fade-up">
          <div className="home-story-tag">平台理念</div>
          <h3>为直觉，找到支点；用结构，托举未知</h3>
          <p>
            把那些天马行空的想法，变成一步步可以走的路。你不知道的那部分，我们帮你补上。你知道的那部分，你只管往前走。
            灵感负责出发，逻辑负责到达。我们帮你做的是后者————让感性的判断有个理性的支撑，让每一步都有据可依。
          </p>
        </div>

        <div className="home-story-side">
          <div className="home-story-card fade-up">
            <div className="home-story-tag">学生</div>
            <p>从问题理解、文档完善到作品改进，看到自己的成长轨迹。</p>
          </div>
          <div className="home-story-card fade-up">
            <div className="home-story-tag">教师</div>
            <p>快速定位团队差异、学生表现和项目演进中的关键节点。</p>
          </div>
          <div className="home-story-card fade-up">
            <div className="home-story-tag">管理员</div>
            <p>确保平台可治理、可维护，也能稳定支撑课程运行。</p>
          </div>
        </div>
      </section>
    </main>
  );
}
