import json, time
from tg_case9 import Case, run, stress
B = dict(nondc_growth_override=0.01, carbon_price=22.0, net_zero=True, load_growth=0.035)
ALL = dict(credit_flex=True, train_shift_frac=0.30, price_shift=0.20)
V = {'none': {}, 'all': ALL, 'all_credit50': dict(ALL, flex_credit_share=0.5), 'all_4h_per_day': dict(ALL, train_daily_hours=4.0)}
out = {}
for split in ('mckinsey', 'iea_inference', 'training_heavy'):
    for v, kw in V.items():
        c = Case(**B, split=split, **kw); t = time.time(); r = run(c)
        st = {}
        for yr in (2031, 2035, 2041):
            e = next(x for x in r if x['year'] == yr)
            st[yr] = {'base': stress(c, e, 0.0, 1.0), 'snap+10%': stress(c, e, 0.10, 1.0), 'snap+10%,imports70%': stress(c, e, 0.10, 0.70)}
        cs = r[0]['system_cost_musd'] + sum(2 * x['system_cost_musd'] for x in r[1:])
        out[f'{split}|{v}'] = dict(cum=cs / 1e3, cum_res=(r[0]['resource_cost_musd'] + sum(2 * x['resource_cost_musd'] for x in r[1:])) / 1e3, bill35=next(x for x in r if x['year'] == 2035)['bill'], stress=st)
        json.dump(out, open('runs12.json', 'w'), default=float); print(split, v, round(time.time() - t), 's', flush=True)
