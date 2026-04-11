"""Seed 4 budget plans with rich test data for user 12345678."""
import json, requests, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "http://127.0.0.1:8037"
UID = "12345678"

def put(plan_id, payload):
    r = requests.put(f"{API}/api/budget/{UID}/{plan_id}", json=payload, timeout=10)
    d = r.json()
    print(f"  PUT {plan_id}: status={d.get('status')}, health={d.get('budget',{}).get('summary',{}).get('health_score','?')}")
    return d

def ai_suggest(plan_id):
    r = requests.post(f"{API}/api/budget/{UID}/{plan_id}/ai-suggest",
                       json={"project_description": "", "project_type": ""}, timeout=60)
    d = r.json()
    sug = d.get("suggestions", {})
    print(f"  AI-suggest {plan_id}: keys={list(sug.keys()) if sug else 'NONE'}")
    return d

def ai_chat(plan_id, question):
    r = requests.post(f"{API}/api/budget/{UID}/{plan_id}/ai-chat",
                       json={"question": question}, timeout=60)
    d = r.json()
    reply = d.get("reply", "")
    preview = reply[:80].replace("\n", " ") + ("..." if len(reply) > 80 else "")
    print(f"  AI-chat {plan_id}: Q='{question}' -> {preview}")
    return d


# ═══════════════════════════════════════════════════════════════
# 1) Quick estimation: NoteMind MVP 资金估算
# ═══════════════════════════════════════════════════════════════
print("\n=== 1. Quick Estimation: NoteMind MVP ===")
QUICK_ID = "e7e9b80a"

put(QUICK_ID, {
    "project_costs": {"categories": [
        {"name": "技术开发", "items": [
            {"name": "阿里云 ECS 2核4G", "unit_price": 158, "quantity": 6, "total": 948, "note": "按月计费×6个月", "cost_type": "monthly"},
            {"name": "域名 .com", "unit_price": 69, "quantity": 1, "total": 69, "note": "首年注册", "cost_type": "once"},
            {"name": "OpenAI API 调用", "unit_price": 200, "quantity": 6, "total": 1200, "note": "GPT-4o 每月~200元", "cost_type": "monthly"},
            {"name": "MongoDB Atlas M10", "unit_price": 120, "quantity": 6, "total": 720, "note": "数据库托管", "cost_type": "monthly"},
            {"name": "SSL证书", "unit_price": 0, "quantity": 1, "total": 0, "note": "Let's Encrypt 免费", "cost_type": "once"},
        ]},
        {"name": "运营推广", "items": [
            {"name": "微信公众号认证", "unit_price": 300, "quantity": 1, "total": 300, "note": "年费", "cost_type": "once"},
            {"name": "B站/小红书推广", "unit_price": 500, "quantity": 3, "total": 1500, "note": "3轮内容投放", "cost_type": "once"},
            {"name": "校园地推物料", "unit_price": 200, "quantity": 1, "total": 200, "note": "传单+易拉宝", "cost_type": "once"},
        ]},
        {"name": "设计与内容", "items": [
            {"name": "UI设计外包", "unit_price": 3000, "quantity": 1, "total": 3000, "note": "Figma 全套页面", "cost_type": "once"},
            {"name": "Logo + VI设计", "unit_price": 800, "quantity": 1, "total": 800, "note": "", "cost_type": "once"},
        ]},
        {"name": "其他", "items": [
            {"name": "软件著作权申请", "unit_price": 500, "quantity": 1, "total": 500, "note": "代理费", "cost_type": "once"},
        ]},
    ]},
})

print("  -> AI analysis for Quick plan:")
ai_suggest(QUICK_ID)
ai_chat(QUICK_ID, "我这个 MVP 阶段资金预算合理吗？有没有什么遗漏的开销？")
ai_chat(QUICK_ID, "如果要申请学校创业孵化资金，我需要怎么准备预算说明？")


# ═══════════════════════════════════════════════════════════════
# 2) Competition: 互联网+省赛参赛预算
# ═══════════════════════════════════════════════════════════════
print("\n=== 2. Competition: 互联网+省赛 ===")
COMP_ID = "6378cb0e"

put(COMP_ID, {
    "project_costs": {"categories": [
        {"name": "技术开发", "items": [
            {"name": "云服务器（比赛演示）", "unit_price": 200, "quantity": 3, "total": 600, "note": "高配3个月", "cost_type": "monthly"},
            {"name": "域名+CDN", "unit_price": 100, "quantity": 1, "total": 100, "note": "", "cost_type": "once"},
            {"name": "API额度", "unit_price": 300, "quantity": 2, "total": 600, "note": "比赛期间用量增大", "cost_type": "monthly"},
        ]},
        {"name": "运营推广", "items": [
            {"name": "用户测试招募", "unit_price": 50, "quantity": 20, "total": 1000, "note": "20名测试用户×50元", "cost_type": "once"},
        ]},
        {"name": "其他", "items": [
            {"name": "知识产权申请", "unit_price": 600, "quantity": 1, "total": 600, "note": "软著代理", "cost_type": "once"},
        ]},
    ]},
    "competition_budget": {"items": [
        {"name": "参赛报名费", "amount": 0, "note": "学校统一缴纳"},
        {"name": "省赛差旅(高铁)", "amount": 1200, "note": "5人×往返240"},
        {"name": "住宿(2晚)", "amount": 1400, "note": "5人×2晚×140/晚"},
        {"name": "餐饮补贴", "amount": 600, "note": "5人×3天×40/天"},
        {"name": "展板+海报打印", "amount": 350, "note": "KT板+A0海报"},
        {"name": "原型设备租赁", "amount": 800, "note": "平板+投影适配器"},
        {"name": "团队文化衫", "amount": 300, "note": "5件定制"},
        {"name": "答辩PPT设计", "amount": 500, "note": "外包美化"},
        {"name": "视频制作", "amount": 1000, "note": "3分钟路演视频"},
        {"name": "样品/Demo制作", "amount": 500, "note": "实体展示材料"},
    ],
    "stages": [
        {"name": "筹备期", "items": []},
        {"name": "校赛", "items": []},
        {"name": "省赛", "items": []},
    ],
    "funding_sources": [
        {"name": "自筹(团队AA)", "amount": 3000, "note": "5人×600"},
        {"name": "学院创新基金", "amount": 2000, "note": "已申请通过"},
        {"name": "指导老师课题经费", "amount": 1500, "note": ""},
        {"name": "学校双创中心补助", "amount": 1500, "note": "凭参赛通知报销"},
    ]},
    "funding_plan": {
        "startup_capital_needed": 8950,
        "sources": [],
        "monthly_gap": [],
        "fundraising_notes": "主要资金来源为学院创新基金和团队自筹。如进入国赛，将额外申请学校双创专项资金（上限2万元）。差旅费可凭比赛通知和发票向学院报销80%。"
    },
})

print("  -> AI analysis for Competition plan:")
ai_suggest(COMP_ID)
ai_chat(COMP_ID, "省赛的预算安排有没有遗漏？评委会关注哪些财务问题？")
ai_chat(COMP_ID, "如果进入国赛，预算大概还需要追加多少？")


# ═══════════════════════════════════════════════════════════════
# 3) Business Plan: NoteMind 完整商业计划书
# ═══════════════════════════════════════════════════════════════
print("\n=== 3. Business Plan: NoteMind 完整模型 ===")
BIZ_ID = "9dfb00e8"

put(BIZ_ID, {
    "project_costs": {"categories": [
        {"name": "技术开发", "items": [
            {"name": "阿里云ECS 4核8G", "unit_price": 298, "quantity": 12, "total": 3576, "note": "生产环境×12月", "cost_type": "monthly"},
            {"name": "阿里云RDS MySQL", "unit_price": 180, "quantity": 12, "total": 2160, "note": "数据库×12月", "cost_type": "monthly"},
            {"name": "Redis缓存实例", "unit_price": 80, "quantity": 12, "total": 960, "note": "session缓存", "cost_type": "monthly"},
            {"name": "OSS对象存储", "unit_price": 50, "quantity": 12, "total": 600, "note": "文件/图片存储", "cost_type": "monthly"},
            {"name": "CDN流量包", "unit_price": 100, "quantity": 4, "total": 400, "note": "季度购买", "cost_type": "once"},
            {"name": "域名 + SSL", "unit_price": 69, "quantity": 1, "total": 69, "note": "", "cost_type": "once"},
            {"name": "OpenAI GPT-4o API", "unit_price": 400, "quantity": 12, "total": 4800, "note": "核心AI功能", "cost_type": "monthly"},
            {"name": "开发工具许可证", "unit_price": 200, "quantity": 1, "total": 200, "note": "JetBrains + Figma", "cost_type": "once"},
        ]},
        {"name": "人力成本", "items": [
            {"name": "全栈开发(兼职)", "unit_price": 4000, "quantity": 6, "total": 24000, "note": "前6月密集开发", "cost_type": "monthly"},
            {"name": "UI/UX设计师(外包)", "unit_price": 5000, "quantity": 2, "total": 10000, "note": "2轮设计迭代", "cost_type": "once"},
            {"name": "运营实习生", "unit_price": 2000, "quantity": 6, "total": 12000, "note": "后6月运营期", "cost_type": "monthly"},
        ]},
        {"name": "运营推广", "items": [
            {"name": "校园大使计划", "unit_price": 200, "quantity": 10, "total": 2000, "note": "10所高校×200/校", "cost_type": "once"},
            {"name": "KOL合作", "unit_price": 1500, "quantity": 3, "total": 4500, "note": "B站/小红书学习类KOL", "cost_type": "once"},
            {"name": "SEM投放", "unit_price": 1000, "quantity": 6, "total": 6000, "note": "百度+知乎 6个月", "cost_type": "monthly"},
            {"name": "线下活动", "unit_price": 800, "quantity": 4, "total": 3200, "note": "4场校园分享会", "cost_type": "once"},
            {"name": "内容营销", "unit_price": 500, "quantity": 12, "total": 6000, "note": "公众号+知乎 12月", "cost_type": "monthly"},
        ]},
        {"name": "法务与知识产权", "items": [
            {"name": "公司注册", "unit_price": 1500, "quantity": 1, "total": 1500, "note": "代理费+刻章", "cost_type": "once"},
            {"name": "商标注册", "unit_price": 800, "quantity": 2, "total": 1600, "note": "2个类别", "cost_type": "once"},
            {"name": "软件著作权×3", "unit_price": 500, "quantity": 3, "total": 1500, "note": "前端+后端+AI模块", "cost_type": "once"},
            {"name": "法律顾问", "unit_price": 500, "quantity": 12, "total": 6000, "note": "合同审核/隐私合规", "cost_type": "monthly"},
        ]},
        {"name": "其他", "items": [
            {"name": "办公场地(孵化器)", "unit_price": 0, "quantity": 12, "total": 0, "note": "学校免费提供", "cost_type": "monthly"},
            {"name": "差旅/会议", "unit_price": 500, "quantity": 4, "total": 2000, "note": "季度投资人见面", "cost_type": "once"},
            {"name": "应急备用金", "unit_price": 3000, "quantity": 1, "total": 3000, "note": "不可预见支出", "cost_type": "once"},
        ]},
    ]},
    "business_finance": {
        "revenue_streams": [
            {"name": "个人Pro会员", "monthly_users": 5000, "price": 19.9, "conversion_rate": 0.06, "monthly_revenue": 5970},
            {"name": "团队协作订阅", "monthly_users": 200, "price": 99, "conversion_rate": 0.12, "monthly_revenue": 2376},
            {"name": "AI高级功能包", "monthly_users": 5000, "price": 9.9, "conversion_rate": 0.08, "monthly_revenue": 3960},
            {"name": "B端定制(高校)", "monthly_users": 3, "price": 5000, "conversion_rate": 1.0, "monthly_revenue": 15000},
        ],
        "fixed_costs_monthly": 8500,
        "variable_cost_per_user": 0.8,
        "growth_rate_monthly": 0.12,
        "scenario_models": {
            "conservative": {
                "label": "悲观", "revenue_multiplier": 0.6, "conversion_multiplier": 0.7,
                "growth_rate_monthly": 0.05, "fixed_costs_monthly": 9000, "variable_cost_per_user": 1.0,
                "note": "市场推广效果不佳，转化率低于预期"
            },
            "baseline": {
                "label": "基准", "revenue_multiplier": 1.0, "conversion_multiplier": 1.0,
                "growth_rate_monthly": 0.12, "fixed_costs_monthly": 8500, "variable_cost_per_user": 0.8,
                "note": "按照当前增长趋势稳步发展"
            },
            "optimistic": {
                "label": "乐观", "revenue_multiplier": 1.4, "conversion_multiplier": 1.3,
                "growth_rate_monthly": 0.22, "fixed_costs_monthly": 10000, "variable_cost_per_user": 0.6,
                "note": "获得爆款传播，高校批量采购"
            }
        },
        "months_to_breakeven": None,
        "cash_flow_projection": [],
        "scenario_results": {},
    },
    "competition_budget": {"items": [
        {"name": "互联网+报名", "amount": 0, "note": "免费"},
        {"name": "省赛差旅", "amount": 1500, "note": ""},
        {"name": "国赛差旅", "amount": 5000, "note": "预留"},
        {"name": "路演视频", "amount": 2000, "note": "专业团队"},
        {"name": "展示物料", "amount": 800, "note": ""},
    ],
    "funding_sources": [
        {"name": "创始团队自筹", "amount": 30000, "note": "4人×7500"},
        {"name": "学校创业孵化基金", "amount": 20000, "note": "通过入驻评审"},
        {"name": "天使投资意向", "amount": 50000, "note": "创新工场pre-seed"},
        {"name": "政府双创补贴", "amount": 10000, "note": "大学生创业补贴"},
    ]},
    "funding_plan": {
        "startup_capital_needed": 96065,
        "sources": [],
        "monthly_gap": [],
        "fundraising_notes": "第一阶段(前6月)以自筹+学校基金为主，控制在5万以内完成MVP上线。第二阶段(7-12月)争取天使投资5万元，用于规模化推广。如B端高校合同落地，可实现第8-9月盈亏平衡。融资节奏：种子轮50万目标，计划在产品上线3个月后启动。",
    },
})

print("  -> AI analysis for Business plan:")
ai_suggest(BIZ_ID)
ai_chat(BIZ_ID, "我的收入模型是否合理？个人Pro会员6%的付费转化率高不高？")
ai_chat(BIZ_ID, "如果要向投资人路演，我的财务数据有哪些薄弱点需要加强？")
ai_chat(BIZ_ID, "B端高校定制这条收入线风险大吗？如何降低依赖？")


# ═══════════════════════════════════════════════════════════════
# 4) Coursework: 创业基础课财务分析
# ═══════════════════════════════════════════════════════════════
print("\n=== 4. Coursework: 创业基础课报告 ===")
CW_ID = "64e09f91"

put(CW_ID, {
    "project_costs": {"categories": [
        {"name": "技术开发", "items": [
            {"name": "云服务器", "unit_price": 100, "quantity": 6, "total": 600, "note": "学生优惠", "cost_type": "monthly"},
            {"name": "域名注册", "unit_price": 59, "quantity": 1, "total": 59, "note": ".cn域名", "cost_type": "once"},
            {"name": "AI接口费用", "unit_price": 100, "quantity": 6, "total": 600, "note": "DeepSeek API", "cost_type": "monthly"},
        ]},
        {"name": "运营推广", "items": [
            {"name": "校内宣传", "unit_price": 100, "quantity": 1, "total": 100, "note": "打印+传单", "cost_type": "once"},
            {"name": "线上推广", "unit_price": 200, "quantity": 1, "total": 200, "note": "朋友圈广告", "cost_type": "once"},
        ]},
        {"name": "人力成本", "items": [
            {"name": "UI设计(同学帮忙)", "unit_price": 500, "quantity": 1, "total": 500, "note": "请客吃饭", "cost_type": "once"},
        ]},
        {"name": "其他", "items": [
            {"name": "软件著作权", "unit_price": 300, "quantity": 1, "total": 300, "note": "", "cost_type": "once"},
        ]},
    ]},
    "business_finance": {
        "revenue_streams": [
            {"name": "基础会员", "monthly_users": 1000, "price": 9.9, "conversion_rate": 0.05, "monthly_revenue": 495},
            {"name": "广告收入", "monthly_users": 1000, "price": 0.5, "conversion_rate": 0.3, "monthly_revenue": 150},
        ],
        "fixed_costs_monthly": 300,
        "variable_cost_per_user": 0.2,
        "growth_rate_monthly": 0.08,
        "scenario_models": {
            "conservative": {
                "label": "悲观", "revenue_multiplier": 0.5, "conversion_multiplier": 0.6,
                "growth_rate_monthly": 0.03, "fixed_costs_monthly": 350, "variable_cost_per_user": 0.3,
                "note": "用户增长缓慢"
            },
            "baseline": {
                "label": "基准", "revenue_multiplier": 1.0, "conversion_multiplier": 1.0,
                "growth_rate_monthly": 0.08, "fixed_costs_monthly": 300, "variable_cost_per_user": 0.2,
                "note": "正常发展"
            },
            "optimistic": {
                "label": "乐观", "revenue_multiplier": 1.5, "conversion_multiplier": 1.4,
                "growth_rate_monthly": 0.15, "fixed_costs_monthly": 400, "variable_cost_per_user": 0.15,
                "note": "口碑传播效果好"
            }
        },
        "months_to_breakeven": None,
        "cash_flow_projection": [],
        "scenario_results": {},
    },
    "funding_plan": {
        "startup_capital_needed": 2359,
        "sources": [],
        "monthly_gap": [],
        "fundraising_notes": "初始资金由团队成员自筹，总计约2500元。如项目发展良好，后续可申请学校大学生创新创业训练计划(SRTP)经费支持，额度5000-10000元。",
    },
})

print("  -> AI analysis for Coursework plan:")
ai_suggest(CW_ID)
ai_chat(CW_ID, "作为课程作业，我的财务分析还需要补充哪些内容？")
ai_chat(CW_ID, "老师可能会问哪些关于财务的问题？我该怎么回答？")
ai_chat(CW_ID, "盈亏平衡分析怎么写比较专业？")

print("\n=== All 4 plans seeded successfully! ===")
