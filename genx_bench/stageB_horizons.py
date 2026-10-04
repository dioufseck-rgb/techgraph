"""Techgraph rolling policies at shorter horizons, priced with the GenX DDP rule.

Uses the perfect-foresight cost convention (annual cost AIC/(1+r) + FOM). A window of h
epochs charges capital only inside the window, which matches GenX's treatment of costs
after the horizon as recoverable. 'static' assumes today's demand and costs persist;
'true' is the rolling oracle. No GenX counterpart exists for h between 2 and K-1.
"""
import os, sys, json
os.environ.setdefault('TECHGRAPH_BACKEND', 'scipy')
sys.path.insert(0, os.path.dirname(__file__))
from stageB_techgraph import setup, capacity_path, present_value, resource_costs, build_static
from techgraph.dynamic import run_policy

root = sys.argv[1]; case = os.path.join(root, 'stageB_pf')
sc, traj, prm, hist, lines, tr, _ = setup(case, 'pf')
p1 = os.path.join(case, 'inputs', 'inputs_p1')
costs = resource_costs(p1); _, _, existing = build_static(p1)
designs = [n for n in sc.designs if n not in lines]
rows = []
for h in range(1, traj.K + 1):
    for exp in (('true',) if h == traj.K else ('static', 'true')):
        run = run_policy(sc, traj, prm, hist, horizon=h, expectations=exp, forbid=lines)
        path = capacity_path(run, designs, traj.K)
        pv, _ = present_value(path, sc, costs, tr, existing)
        rows.append(dict(horizon=h, forecast=exp, pv=pv))
        print(h, exp, f'{pv:,.0f}', flush=True)
best = min(r['pv'] for r in rows)
for r in rows: r['gap_vs_full_foresight'] = r['pv'] / best - 1
json.dump(rows, open(sys.argv[2], 'w'), indent=1)
for r in rows: print(f"h={r['horizon']} {r['forecast']:6s} PV {r['pv']:,.0f}  gap {r['gap_vs_full_foresight']:+.4%}")
