"""GenX benchmark, Stage A: build the Techgraph twin of a one-day GenX case and compare.

The Techgraph scenario is generated from the GenX input CSVs, so both models read one source.

Mapping (GenX -> Techgraph legacy kinds), all exact unless noted:
  Thermal (no UC, ramps relaxed)   -> convert fuel->elec. var_cost = VOM + fuel price x heat rate
                                      (fuel prices are constant over the day). Fuel is free at every zone.
  VRE                              -> renewable with the zone's availability profile.
  Storage (separate MW and MWh)    -> store (energy, $/MWh-yr) at a battery node, plus a lossless
                                      bidirectional transport (power, $/MW-yr) from the zone to that node.
                                      GenX VOM on charge and discharge -> transport var_cost per direction.
                                      Not exact: GenX limits charge + discharge <= P jointly; Techgraph
                                      limits each direction separately. The min/max duration bounds are dropped.
  Line (loss L, half at each end)  -> existing bidirectional transport, loss L/(1+L/2), capacity C(1+L/2).
  Unserved energy                  -> legacy unmet at VOLL (one GenX demand segment).
Costs: Techgraph reports $/day with days=1, so the annual objective is 365 x the Techgraph objective.
"""
import json, os, sys
import pandas as pd

os.environ.setdefault('TECHGRAPH_BACKEND', 'scipy')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from techgraph.catalog import Design, Scenario          # noqa: E402
from techgraph.model import solve, check_balances       # noqa: E402

BIG = 1e7  # replaces the default 5,000 MW design cap


def build(case_dir):
    rd = lambda p: pd.read_csv(os.path.join(case_dir, p))
    dem, var, fuel = rd('system/Demand_data.csv'), rd('system/Generators_variability.csv'), rd('system/Fuels_data.csv')
    net = rd('system/Network.csv').dropna(subset=['Network_Lines'])
    th, vre, st = rd('resources/Thermal.csv'), rd('resources/Vre.csv'), rd('resources/Storage.csv')
    zones = list(rd('system/Network.csv').iloc[:, 0])           # MA, CT, ME in zone order
    T = int(dem.Timesteps_per_Rep_Period[0])
    assert int(dem.Rep_Periods[0]) == 1 and float(dem.Sub_Weights[0]) == 8760, 'Stage A expects one day weighted to a year'
    hours = fuel.iloc[1:]
    designs, profiles, existing = {}, {}, {}

    for r in th.itertuples():
        price = hours[r.Fuel]
        assert price.min() == price.max(), 'fuel price must be constant over the day'
        designs[r.Resource] = Design(r.Resource, 'convert', annual_cost=r.Inv_Cost_per_MWyr + r.Fixed_OM_Cost_per_MWyr,
                                     var_cost=r.Var_OM_Cost_per_MWh + price.iloc[0] * r.Heat_Rate_MMBTU_per_MWh,
                                     form_in='fuel', form_out='elec', loc=zones[r.Zone - 1],
                                     eff=3.412 / r.Heat_Rate_MMBTU_per_MWh, max_cap=BIG)
    for r in vre.itertuples():
        profiles[r.Resource] = list(var[r.Resource].astype(float))
        designs[r.Resource] = Design(r.Resource, 'renewable', annual_cost=r.Inv_Cost_per_MWyr + r.Fixed_OM_Cost_per_MWyr,
                                     var_cost=r.Var_OM_Cost_per_MWh, loc=zones[r.Zone - 1], profile=r.Resource, max_cap=BIG)
    bat_nodes = []
    for r in st.itertuples():
        z = zones[r.Zone - 1]; node = f'{z}_bat'; bat_nodes.append(node)
        assert r.Var_OM_Cost_per_MWh == r.Var_OM_Cost_per_MWh_In and r.Self_Disch == 0
        designs[r.Resource + '_energy'] = Design(r.Resource + '_energy', 'store',
                                                 annual_cost=r.Inv_Cost_per_MWhyr + r.Fixed_OM_Cost_per_MWhyr,
                                                 form='elec', loc=node, duration_h=1e-3,   # power limit set by the link
                                                 eta_c=r.Eff_Up, eta_d=r.Eff_Down, max_cap=BIG)
        designs[r.Resource + '_power'] = Design(r.Resource + '_power', 'transport',
                                                annual_cost=r.Inv_Cost_per_MWyr + r.Fixed_OM_Cost_per_MWyr,
                                                var_cost=r.Var_OM_Cost_per_MWh, form='elec', loc_from=z, loc_to=node,
                                                loss=0.0, bidirectional=True, max_cap=BIG)
    for r in net.itertuples():
        L = r.Line_Loss_Percentage; name = r.transmission_path_name
        designs[name] = Design(name, 'transport', annual_cost=0.0, form='elec',
                               loc_from=zones[int(r.Start_Zone) - 1], loc_to=zones[int(r.End_Zone) - 1],
                               loss=L / (1 + L / 2), bidirectional=True, max_cap=BIG)
        existing[name] = r.Line_Max_Flow_MW * (1 + L / 2)

    zc = [c for c in dem.columns if c.startswith('Demand_MW_z')]
    sc = Scenario(periods=T, hours=1.0, demand_D=[0.0] * T, hub_energy=0.0, hub_max_rate=0.0,
                  profiles=profiles, fuel_price_R=0.0, voll=float(dem.Voll[0]), designs=designs, days=1.0,
                  extra_demand={zones[i]: list(dem[c].astype(float)) for i, c in enumerate(zc)},
                  locations=tuple(zones) + tuple(bat_nodes) + ('D',),   # 'D' is an empty legacy demand node
                  fuel_sites=tuple(zones))
    landscape = [n for n in designs if n not in existing]
    return sc, landscape, existing


def genx_reference(case_dir):
    res = os.path.join(case_dir, 'results')
    obj = float(pd.read_csv(os.path.join(res, 'status.csv')).Objval[0]) * 1e6   # ParameterScale: $M
    c = pd.read_csv(os.path.join(res, 'capacity.csv')); c = c[c.Resource != 'Total']
    cap = {}
    for r in c.itertuples():
        if r.EndEnergyCap > 0 or 'battery' in r.Resource:
            cap[r.Resource + '_power'] = float(r.EndCap); cap[r.Resource + '_energy'] = float(r.EndEnergyCap)
        else:
            cap[r.Resource] = float(r.EndCap)
    return obj, cap


def main(case_dir, out_json):
    sc, landscape, existing = build(case_dir)
    res = solve(sc, landscape, existing=existing)
    resid = check_balances(sc, res)
    tg_obj = 365.0 * res.objective
    gx_obj, gx_cap = genx_reference(case_dir)
    rows = []
    for name in sorted(gx_cap):
        g, t = gx_cap[name], res.capacity.get(name, 0.0)
        rel = abs(t - g) / g if g > 1e-6 else None
        rows.append(dict(design=name, genx=g, techgraph=t, abs_diff=t - g, rel_diff=rel))
    # simultaneous charge and discharge would make the separate power limits looser than GenX's joint limit
    simul = {}
    for name, ser in res.activity.items():
        if name.endswith('_power'):
            simul[name] = max(min(f, b) for f, b in zip(ser['forward'], ser['backward']))
    out = dict(case=case_dir, techgraph_objective_per_year=tg_obj, genx_objective_per_year=gx_obj,
               objective_rel_diff=(tg_obj - gx_obj) / gx_obj, techgraph_costs_per_year={k: 365 * v for k, v in res.costs.items()},
               balance_residuals=len(resid), max_simultaneous_charge_discharge_MW=simul,
               unmet_MWh_per_day=sum(sum(v) for v in res.unmet_extra.values()), solver=res.solver, capacities=rows)
    with open(out_json, 'w') as f:
        json.dump(out, f, indent=1, default=float)
    print(f"GenX      objective: {gx_obj:,.0f} $/yr")
    print(f"Techgraph objective: {tg_obj:,.0f} $/yr   relative difference {out['objective_rel_diff']:+.2e}")
    print(f"balance residuals: {len(resid)}   unmet MWh/day: {out['unmet_MWh_per_day']:.3g}   "
          f"max simultaneous charge+discharge MW: {max(simul.values()) if simul else 0:.3g}")
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f'{x:,.3f}'))
    return out


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'stageA_comparison.json')
