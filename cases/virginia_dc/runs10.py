import json, time
from tg_case9 import Case, run
B = dict(nondc_growth_override=0.01, load_growth=0.028, carbon_price=22.0, net_zero=True)
cases = {
 'CP': Case(**B),
 'CP_noDC': Case(nondc_growth_override=0.01, dc_dom_2035=4.0, dc_novec_2035=1.2, carbon_price=22.0, net_zero=True),
 'L_tie7': Case(**B, import_cap_mw=7_000.0, import_cap_from=2029),
 'L_border': Case(**B, carbon_on_imports=True),
 'L_consumption_cap': Case(**dict(B, cap_2035_mst=55.0), cap_counts_imports=True),
 'R_limits_relaxed': Case(**B, solar_rate=4_000.0, osw_rate=3_000.0, ldes12_rate=1_500.0, ldes100_rate=1_500.0),
 'R_floor3': Case(**B, cap_floor_mst=3.0),
 'R_ldes_cheap': Case(**B, ldes100_rate=1_500.0),
 'R_smr_2x': Case(**B, smr_cost=1_700_000.0),
 'R_no_smr': Case(**B, smr_from=2099),
}
out = {}
for k, c in cases.items():
    t = time.time(); out[k] = run(c); json.dump(out, open('runs10.json', 'w'), default=float); print(k, round(time.time() - t), 's', flush=True)
# cost causation through 2050 using the no-growth baseline
base = out['CP_noDC']
out['R_assigned'] = run(Case(**B, allocation='assigned', assigned_baseline=tuple(e['res_cap_cost'] for e in base)))
json.dump(out, open('runs10.json', 'w'), default=float); print('R_assigned done', flush=True)
