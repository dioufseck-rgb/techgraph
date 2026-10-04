import json, os, datetime as dt, time, sys
import prrism_lite as PL, tg_wma as TW
flows, _ = PL.load_flows(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'usgs_01646502_adjusted_little_falls.txt'), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'usgs_01638500_point_of_rocks.txt'))
k = PL.fit_recession(flows)
pub = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'wma_results.json')))
W = {'1930': (dt.date(1930, 3, 1), dt.date(1931, 3, 31)), '1966': (dt.date(1966, 1, 1), dt.date(1967, 3, 31))}
RULE_VALUES = dict(OCC_UP=1.0, PAX_UP=1.0, MS=3.0, JR_UP=2.0, JR_LO=8.0, LS_UP=4.0, LS_LO=10.0, OCC_LO=5.0, PAX_LO=5.0)   # Little Seneca reserved for corrections
V = {'rule_matched': TW.Policy(rule_offpotomac=True, values=RULE_VALUES), 'optimized_h10_forecast': TW.Policy(),
     'optimized_h10_actual': TW.Policy(perfect=True), 'optimized_h30_actual': TW.Policy(perfect=True, horizon=30),
     'optimized_h90_actual': TW.Policy(perfect=True, horizon=90)}
out = {}
for p in pub.values():
    if p['flows'] != 'Historic': continue
    key = f"{p['year']}_{p['demands']}"; out[key] = {'study': dict(zip(('full', '1930', '1966'), p['min_LS_JRws_bg'])), 'study_deficit_days': p['deficit_days']}
    for w, (a, b) in W.items():
        out[key].setdefault('prrism_lite', {})[w] = PL.metrics(PL.simulate(flows, PL.Scenario(p['year'], p['annual_demand'][0]), k, start=a, end=b))['min_LS_JRws_bg']
    for vn, pol in V.items():
        for w, (a, b) in W.items():
            t = time.time(); rec = TW.WMA(flows, p['year'], p['annual_demand'][0], k, policy=pol).run(a, b); m = TW.metrics(rec)
            out[key].setdefault(vn, {})[w] = dict(min_bg=m['min_LS_JRws_bg'], deficit_days=m['deficit_days'], secs=round(time.time() - t, 1))
        json.dump(out, open('tg_scan.json', 'w'), indent=1); print(key, vn, {w: round(v['min_bg'], 2) for w, v in out[key][vn].items()}, '| sim', {w: round(v, 2) for w, v in out[key]['prrism_lite'].items()}, '| study', out[key]['study'], flush=True)
print('DONE', flush=True)
