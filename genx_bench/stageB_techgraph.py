"""GenX benchmark, Stage B: multi-stage comparison.

Techgraph's dynamic engine (run_policy) is run on the trajectory used to build the GenX
multi-stage case (make_stageB_case.py), in two modes:

  perfect foresight : one window over all epochs, true trajectory (horizon >= K).
  myopic            : horizon 1, which sees only the current epoch, as GenX Myopic=1 does.

Mapping of GenX multi-stage accounting onto Techgraph epochs (one epoch = one stage of L years):

  GenX perfect foresight (DDP) objective = sum_s DF_s [ OCC_s x_s + OPEXMULT (FOM cap_s + ops_s) ],
    DF_s = (1+r)^-(L(s-1)),  OPEXMULT = sum_{i=1..L} (1+r)^-(i-1),
    OCC_s = AIC_s sum_{i=1..Y_s} (1+r)^-i,  Y_s = years from the start of stage s to the horizon end.
  Since sum_{i=1..Y_s}(1+r)^-i = OPEXMULT/(1+r) * sum_{m>=s} (1+r)^-(L(m-s)), this equals
    OPEXMULT * sum_m d^(m-1) [ sum_{v<=m} (AIC_v/(1+r) + FOM) x_v + ops_m ],  d = (1+r)^-L,
  which is Techgraph's window objective with annual cost AIC/(1+r) + FOM, fom_share = 0,
  aging = 0, life beyond the horizon and discount d, multiplied by 365 * OPEXMULT.
  FOM must be constant over stages because GenX applies each stage's FOM to all vintages.

  GenX myopic keeps annualized costs: each stage minimizes AIC_s x_s + FOM cap_s + ops_s with
  earlier capacity fixed. Techgraph's horizon-1 policy with annual cost AIC + FOM makes the same
  decisions (the FOM on inherited capacity is a constant that GenX includes and Techgraph omits).

Both paths are then priced with one common rule (the DDP accounting) so that the myopic-versus-
foresight gap can be compared across models. Operating costs for that pricing come from one
evaluator: a fixed-capacity Techgraph LP for each stage.
"""
import json, os, sys
from dataclasses import replace
import pandas as pd

os.environ.setdefault('TECHGRAPH_BACKEND', 'scipy')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from stageA_techgraph import build as build_static                     # noqa: E402
from techgraph.dynamic import Trajectory, Params, Vintage, run_policy   # noqa: E402
from techgraph.model import solve                                       # noqa: E402


def resource_costs(case_p1):
    """GenX annualized investment (AIC) and FOM per Techgraph design name, from the stage-1 inputs."""
    rd = lambda f: pd.read_csv(os.path.join(case_p1, 'resources', f))
    out = {}
    for f in ('Thermal.csv', 'Vre.csv'):
        for r in rd(f).itertuples():
            out[r.Resource] = (r.Inv_Cost_per_MWyr, r.Fixed_OM_Cost_per_MWyr)
    for r in rd('Storage.csv').itertuples():
        out[r.Resource + '_power'] = (r.Inv_Cost_per_MWyr, r.Fixed_OM_Cost_per_MWyr)
        out[r.Resource + '_energy'] = (r.Inv_Cost_per_MWhyr, r.Fixed_OM_Cost_per_MWhyr)
    return out


def kind(name, decline):
    for k in decline:
        if k in name: return k
    return None


def setup(case_dir, mode):
    tr = json.load(open(os.path.join(case_dir, 'trajectory.json')))
    K, L, r = tr['stages'], tr['stage_length'], tr['wacc']
    p1 = os.path.join(case_dir, 'inputs', 'inputs_p1')
    sc, landscape, existing = build_static(p1)                 # stage-1 day, stage-1 demand
    costs = resource_costs(p1)
    capfac = 1 / (1 + r) if mode == 'pf' else 1.0              # GenX end-of-year capital payments (DDP only)
    designs, mult = dict(sc.designs), {}
    for name, (aic, fom) in costs.items():
        base = aic * capfac + fom
        designs[name] = replace(designs[name], annual_cost=base)
        k = kind(name, tr['inv_mult'])
        if k:
            mult[name] = [(aic * m * capfac + fom) / base for m in tr['inv_mult'][k]]
    sc = replace(sc, designs=designs)
    traj = Trajectory(K=K, fuel_price=[0.0] * K, demand_mult=list(tr['demand_mult']), cost_mult=mult,
                      discount=(1 + r) ** (-L))
    prm = Params(life={n: 10 * K for n in sc.designs}, fom_share=0.0, aging=0.0)
    history = [Vintage(n, -1, c, c, 0.0, 0.0, 100 * K) for n, c in existing.items()]
    opexmult = sum((1 + r) ** -(i - 1) for i in range(1, L + 1))
    return sc, traj, prm, history, tuple(existing), tr, opexmult


def capacity_path(run, designs, K):
    """Installed capacity per design and epoch, from the run's records."""
    path = {n: [0.0] * K for n in designs}
    for k, e in enumerate(run['epochs']):
        for n, c in e.get('capacity', {}).items():
            if n in path: path[n][k] = float(c)
    return path


def genx_path(case_dir, K):
    res = os.path.join(case_dir, 'results')
    cap = pd.read_csv(os.path.join(res, 'capacities_multi_stage.csv'))
    en = pd.read_csv(os.path.join(res, 'capacities_energy_multi_stage.csv'))
    path = {}
    for r in cap.itertuples():
        if r.Resource == 'Total': continue
        vals = [float(getattr(r, f'EndCap_p{s + 1}')) for s in range(K)]
        path[(r.Resource + '_power') if 'battery' in r.Resource else r.Resource] = vals
    for r in en.itertuples():
        if 'battery' in r.Resource:
            path[r.Resource + '_energy'] = [float(getattr(r, f'EndEnergyCap_p{s + 1}')) for s in range(K)]
    return path


def operating_cost(sc, caps, dm):
    """Annual operating cost ($/yr) of fixed capacities at demand multiplier dm (Techgraph LP)."""
    scd = replace(sc, extra_demand={l: [dm * x for x in p] for l, p in sc.extra_demand.items()})
    res = solve(scd, [], existing=caps, fixed=True, existing_fom_share=0.0)
    return 365.0 * res.objective, res


def present_value(path, sc_static, costs, tr, existing_lines):
    """Price a capacity path with the GenX DDP rule. Returns ($ PV, per-stage detail)."""
    K, L, r = tr['stages'], tr['stage_length'], tr['wacc']
    opexmult = sum((1 + r) ** -(i - 1) for i in range(1, L + 1))
    pv, rows = 0.0, []
    for s in range(K):
        df = (1 + r) ** -(L * s)
        yrs = L * (K - s)
        annuity = sum((1 + r) ** -i for i in range(1, yrs + 1))
        inv = fom = 0.0
        caps = dict(existing_lines)
        for n, vals in path.items():
            new = max(0.0, vals[s] - (vals[s - 1] if s else 0.0))
            aic, f = costs[n]
            k = kind(n, tr['inv_mult'])
            m = tr['inv_mult'][k][s] if k else 1.0
            inv += aic * m * annuity * new
            fom += f * vals[s]
            caps[n] = vals[s]
        ops, res = operating_cost(sc_static, caps, tr['demand_mult'][s])
        unmet = sum(sum(v) for v in res.unmet_extra.values())
        stage = df * (inv + opexmult * (fom + ops))
        pv += stage
        rows.append(dict(stage=s + 1, investment=inv, fom=fom, ops=ops, unmet_MWh_day=unmet, discounted=stage))
    return pv, rows


def compare_paths(a, b):
    worst = 0.0
    for n in a:
        for x, y in zip(a[n], b.get(n, [0.0] * len(a[n]))):
            worst = max(worst, abs(x - y))
    return worst


def main(root, out_json):
    pf_dir, my_dir = os.path.join(root, 'stageB_pf'), os.path.join(root, 'stageB_myopic')
    out = {}
    paths = {}
    for mode, case in (('pf', pf_dir), ('myopic', my_dir)):
        sc, traj, prm, hist, lines, tr, opexmult = setup(case, mode)
        run = run_policy(sc, traj, prm, hist, horizon=traj.K if mode == 'pf' else 1,
                         expectations='true', forbid=lines)
        tg = capacity_path(run, [n for n in sc.designs if n not in lines], traj.K)
        gx = genx_path(case, traj.K)
        paths[mode] = dict(techgraph=tg, genx=gx)
        rec = dict(max_capacity_diff_MW=compare_paths(gx, tg))
        if mode == 'pf':
            st = pd.read_csv(os.path.join(case, 'results', 'stats_multi_stage.csv')).tail(1).iloc[0]
            ub, lb = float(st.iloc[2]) * 1e6, float(st.iloc[3]) * 1e6   # DDP upper (path cost) and lower bound, $M -> $
            tg_obj = 365.0 * opexmult * run['window_objective']
            rec.update(genx_objective=ub, genx_lower_bound=lb, techgraph_objective=tg_obj,
                       rel_diff=(tg_obj - ub) / ub, rel_diff_to_lower_bound=(tg_obj - lb) / lb,
                       genx_ddp_iterations=int(st.iloc[0]))
        out[mode] = rec
    # common pricing of all four paths
    sc0, _, _, _, lines, tr, _ = setup(pf_dir, 'pf')
    costs = resource_costs(os.path.join(pf_dir, 'inputs', 'inputs_p1'))
    _, _, existing = build_static(os.path.join(pf_dir, 'inputs', 'inputs_p1'))
    pvs = {}
    for mode in ('pf', 'myopic'):
        for model in ('genx', 'techgraph'):
            pv, rows = present_value(paths[mode][model], sc0, costs, tr, existing)
            pvs[f'{model}_{mode}'] = dict(pv=pv, stages=rows)
    for model in ('genx', 'techgraph'):
        pvs[f'{model}_gap'] = pvs[f'{model}_myopic']['pv'] / pvs[f'{model}_pf']['pv'] - 1
    out['common_pricing'] = pvs
    out['paths'] = paths
    json.dump(out, open(out_json, 'w'), indent=1, default=float)

    print(f"Perfect foresight objective  GenX {out['pf']['genx_objective']:,.0f}  Techgraph "
          f"{out['pf']['techgraph_objective']:,.0f}  rel diff {out['pf']['rel_diff']:+.2e}")
    for mode in ('pf', 'myopic'):
        print(f"{mode:7s} max capacity difference over all designs and stages: {out[mode]['max_capacity_diff_MW']:.3g} MW")
    for k in ('genx_pf', 'genx_myopic', 'techgraph_pf', 'techgraph_myopic'):
        print(f"PV under DDP pricing  {k:17s} {pvs[k]['pv']:,.0f}")
    print(f"myopic gap  GenX {pvs['genx_gap']:+.4%}   Techgraph {pvs['techgraph_gap']:+.4%}")
    return out


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'stageB_comparison.json')
