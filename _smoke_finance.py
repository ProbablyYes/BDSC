"""临时 smoke test：验证 F1+F3 改动无回归。"""
import os, sys
sys.path.insert(0, 'apps/backend')
os.environ.setdefault('DATA_ROOT', os.path.abspath('data'))

from app.services import finance_analyst as fa
from app.services import finance_baseline_service as fbs
from app.services import finance_guard as fg

print('=== seed init (rewrite v1->v2 if needed) ===')
fbs.init_seed_if_missing()
print()

print('=== resolve_baseline (allow_online=False) ===')
for ind in ['SaaS', '电商', '教育', '社会公益', '硬件', '某个未知行业']:
    b = fbs.resolve_baseline(ind, allow_online=False)
    th = fa._get_thresholds(b)
    meta = b.get('_meta', {})
    print(f"  [{ind:10s}] industry={meta.get('industry'):8s}  source={meta.get('source'):4s}  "
          f"bg={meta.get('bg_refresh_state'):28s}  "
          f"ltv_cac_h={th['ltv_cac_healthy']}  pb_h={th['payback_healthy_months']}m  "
          f"runway_r={th['runway_red_months']}m  be_g={th['breakeven_green_months']}m")
print()

print('=== analyze_unit_economics: 同样数据在不同行业下 verdict 应不一样 ===')
ass = {'monthly_price': 199, 'gross_margin': 0.6, 'monthly_retention': 0.85, 'cac': 800}
for ind in ['SaaS', '电商', '教育']:
    card = fa.analyze_unit_economics(ass, industry=ind)
    out = card['outputs']
    v = card['verdict']
    print(f"  [{ind:6s}] LTV/CAC={out['ltv_cac_ratio']}  Payback={out['payback_period_months']}m  "
          f"th_lc_h={out['ltv_cac_healthy']}  th_pb_h={out['payback_healthy_months']}m  -> "
          f"{v['level']}: {v['reason'][:90]}")
print()

print('=== project_cash_flow: 不同行业 runway/breakeven 评分应不同 ===')
cf_ass = {
    'initial_capital': 500000,
    'fixed_costs_monthly': 50000,
    'variable_cost_per_user': 20,
    'monthly_price': 199,
    'new_users_per_month': 50,
    'monthly_retention': 0.85,
    'growth_rate_monthly': 0.05,
}
for ind in ['SaaS', '电商', '教育']:
    card = fa.project_cash_flow(cf_ass, months=36, industry=ind)
    out = card['outputs']
    v = card['verdict']
    print(f"  [{ind:6s}] breakeven={out.get('breakeven_month')}  "
          f"runway_exh={out.get('runway_exhausted_month')}  "
          f"th_be_g={out.get('breakeven_green_months')}m  th_runway_r={out.get('runway_red_months')}m  -> "
          f"{v['level']}: {v['reason'][:80]}")
print()

print('=== thresholds_used metadata 出现在卡片上 ===')
ue = fa.analyze_unit_economics(ass, industry='SaaS')
print(f"  ue.thresholds_used.source={ue['thresholds_used']['source']}")
print(f"  ue.baseline_meta.bg_refresh_state={ue['baseline_meta'].get('bg_refresh_state')}")
print(f"  ue.thresholds_used.values keys: {sorted(list(ue['thresholds_used']['values'].keys()))[:6]}")
print()

print('=== mark_never_refresh + bg refresh skip ===')
fbs.mark_never_refresh('教育', locked=True)
b = fbs.resolve_baseline('教育', allow_online=False)
print(f"  after lock:   never_refresh={b['_meta']['never_refresh']}  bg_state={b['_meta']['bg_refresh_state']}")
fbs.mark_never_refresh('教育', locked=False)
b = fbs.resolve_baseline('教育', allow_online=False)
print(f"  after unlock: never_refresh={b['_meta']['never_refresh']}  bg_state={b['_meta']['bg_refresh_state']}")
print()

print('=== finance_guard.scan_message smoke test ===')
res = fg.scan_message('我们打算月收 99 元，CAC 大概 800 元，月留存 80%，毛利 60%', industry_hint='SaaS')
print(f"  guard.triggered={res['triggered']}  hits={res.get('hits')}  cards={len(res.get('cards', []))}")
for c in res.get('cards', []):
    th_src = c.get('thresholds_used', {}).get('source', '<missing>')
    bg = c.get('baseline_meta', {}).get('bg_refresh_state', '<missing>')
    print(f"  card[{c['module']:18s}] verdict={c['verdict']['level']}  th_src={th_src}  bg={bg}")
print()

print('=== nonprofit CPB 评分: 公益项目 ===')
np_ass = {'cost_per_beneficiary': 600}
card = fa.analyze_unit_economics(np_ass, industry='社会公益')
print(f"  公益 CPB=¥600  outputs={card['outputs']}")
print(f"  verdict={card['verdict']}")

print('\nALL DONE.')
