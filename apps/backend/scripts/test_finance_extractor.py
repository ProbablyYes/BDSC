"""Smoke test for finance_signal_extractor."""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.finance_signal_extractor import extract_finance_signals

CASES = [
    ("我们想做一款给中学生的英语阅读 SaaS, 月费 49 元, 目标月活 5000 人, 付费转化率 3%",  "subscription"),
    ("我们做政企采购, 单合同 30 万, 服务周期 12 个月, 月新签 1 份, 续约率 60%",          "project_b2b"),
    ("做一个公益资助平台, 在期资助 5 个项目, 单个项目年金额 20 万, 续期率 70%, 每月服务受益人 800 人", "grant_funded"),
    ("我们卖智能硬件, 出厂价 1200 元, BOM 成本 600 元, 月销量 800 台",                  "hardware_sales"),
    ("做平台撮合, 月 GMV 200 万, 佣金率 8%, 活跃卖家 50 家",                            "platform_commission"),
    ("客单价 88 元, 月购买人数 3000 人, 复购 1.5 单/人/月",                              "transaction"),
    ("CSR 捐赠为主, 月捐赠方 30 个, 平均捐赠额 5000 元, 留存 50%",                       "donation"),
]

ok_count = 0
for text, expected in CASES:
    r = extract_finance_signals(text, [])
    got = r.get("primary_pattern")
    fields = r.get("pattern_inputs", {}).get(expected, {})
    mark = "OK" if got == expected else "FAIL"
    if got == expected:
        ok_count += 1
    print(f"[{mark}] expected={expected:22s} got={got:22s} fields={list(fields.keys())}")
    if r.get("summary"):
        print(f"        summary: {r['summary']}")
print(f"\n{ok_count}/{len(CASES)} pattern detections correct")
