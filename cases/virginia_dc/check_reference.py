"""Regression check: two Virginia runs that exercise every rule type must reproduce the stored reference exactly."""
import json, os
import tg_case10 as T10, tg_case9 as T9
HERE = os.path.dirname(os.path.abspath(__file__))
ref = json.load(open(os.path.join(HERE, 'results', 'reference_runs.json'))); new = {}
r = T10.run(T10.plan_case('DF')); new['v10_DF'] = [(e['year'], e['system_cost_musd'], e['balance']['co2_mst'], e['bill']) for e in r]
r = T9.run(T9.Case(nondc_growth_override=0.01, load_growth=0.028, carbon_price=22.0, net_zero=True, credit_flex=True))
new['v9_CPflex'] = [(e['year'], e['system_cost_musd'], e['balance']['co2_mst'], e['bill']) for e in r]
ok = True
for k in ref:
    d = max(max(abs(a - b) / max(1.0, abs(a)) for a, b in zip(x[1:], y[1:])) for x, y in zip(ref[k], new[k]))
    print(f'{k}: max relative difference {d:.2e}'); ok &= d < 1e-9
print('PASS' if ok else 'FAIL')
