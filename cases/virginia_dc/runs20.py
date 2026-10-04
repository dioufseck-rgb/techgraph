import json, time
from tg_case10 import plan_case, run
out = {}
def go(k, c):
    t = time.time(); out[k] = run(c); json.dump(out, open('runs20.json', 'w'), default=float); print(k, round(time.time() - t), 's', flush=True)
for p in ('NP', 'CP', 'DF', 'DF_ISP', 'DF_NNG'):
    go(f'{p}_mod', plan_case(p))
for g, gn in ((0.023, 'low'), (0.035, 'high')):
    for p in ('NP', 'CP', 'DF'):
        go(f'{p}_{gn}', plan_case(p, growth=g))
go('CP_mod_buy60', plan_case('CP', rggi_escape=60.0))
go('DF_mod_buy60', plan_case('DF', rggi_escape=60.0))
go('CP_noDC', plan_case('CP', growth=0.0, dc_dom_2035=4.0, dc_novec_2035=1.2))
go('CP_assigned', plan_case('CP', allocation='assigned', assigned_baseline=tuple(e['res_cap_cost'] for e in out['CP_noDC'])))
