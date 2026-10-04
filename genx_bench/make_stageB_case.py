"""Build the GenX Stage B multi-stage case from a one-day Stage A case.

Six stages of five years. Demand grows 2%/yr. Annualized investment cost falls
2%/yr for wind, 5%/yr for solar and 6%/yr for batteries; gas and all fixed O&M stay
constant (GenX applies each stage's fixed O&M to all vintages, so it must be constant
for vintage-based accounting to agree). Lifetimes and capital recovery periods exceed
the horizon, so nothing retires and capital is paid to the end of the horizon.
"""
import os, re, shutil, sys, json
import pandas as pd

STAGES, LEN, WACC = 6, 5, 0.045
GROWTH = 0.02
DECLINE = {'wind': 0.02, 'solar': 0.05, 'battery': 0.06}


def trajectory():
    yrs = [LEN * s for s in range(STAGES)]            # years from the start at each stage start
    return dict(stages=STAGES, stage_length=LEN, wacc=WACC, years=yrs,
                demand_mult=[(1 + GROWTH) ** y for y in yrs],
                inv_mult={k: [(1 - r) ** y for y in yrs] for k, r in DECLINE.items()})


def kind(resource):
    for k in DECLINE:
        if k in resource: return k
    return None


def make(src, dst, myopic):
    tr = trajectory()
    shutil.rmtree(dst, ignore_errors=True); os.makedirs(dst)
    shutil.copytree(os.path.join(src, 'settings'), os.path.join(dst, 'settings'))
    shutil.copy(os.path.join(src, 'Run.jl'), dst)
    for s in range(STAGES):
        p = os.path.join(dst, 'inputs', f'inputs_p{s + 1}'); os.makedirs(p)
        for sub in ('system', 'resources'):
            shutil.copytree(os.path.join(src, sub), os.path.join(p, sub))
        d = pd.read_csv(os.path.join(p, 'system/Demand_data.csv'))
        for c in [c for c in d.columns if c.startswith('Demand_MW_z')]:
            d[c] = d[c] * tr['demand_mult'][s]
        d.to_csv(os.path.join(p, 'system/Demand_data.csv'), index=False)
        rows = []
        for f in ('Thermal.csv', 'Vre.csv', 'Storage.csv'):
            fp = os.path.join(p, 'resources', f); r = pd.read_csv(fp)
            r['Can_Retire'] = 0
            for col in ('Inv_Cost_per_MWyr', 'Inv_Cost_per_MWhyr'):
                if col in r.columns: r[col] = r[col].astype(float)
            for i, name in enumerate(r.Resource):
                k = kind(name)
                if k:
                    for col in ('Inv_Cost_per_MWyr', 'Inv_Cost_per_MWhyr'):
                        if col in r.columns: r.loc[i, col] = r.loc[i, col] * tr['inv_mult'][k][s]
                rows.append(dict(Resource=name, WACC=WACC, Capital_Recovery_Period=60, Lifetime=60,
                                 Min_Retired_Cap_MW=0, Min_Retired_Energy_Cap_MW=0, Min_Retired_Charge_Cap_MW=0))
            r.to_csv(fp, index=False)
        pd.DataFrame(rows).to_csv(os.path.join(p, 'resources/Resource_multistage_data.csv'), index=False)
        n = pd.read_csv(os.path.join(p, 'system/Network.csv'))
        n['Line_Max_Flow_Possible_MW'] = n['Line_Max_Flow_MW']; n['WACC'] = WACC; n['Capital_Recovery_Period'] = 60
        n.loc[n.Network_Lines.isna(), ['Line_Max_Flow_Possible_MW', 'WACC', 'Capital_Recovery_Period']] = None
        for col in ('Network_Lines', 'Start_Zone', 'End_Zone', 'Line_Max_Flow_MW', 'Line_Max_Reinforcement_MW',
                    'Line_Max_Flow_Possible_MW', 'Capital_Recovery_Period'):
            n[col] = n[col].astype('Int64')
        n.rename(columns={n.columns[0]: ''}).to_csv(os.path.join(p, 'system/Network.csv'), index=False)
    gs = os.path.join(dst, 'settings/genx_settings.yml'); s = open(gs).read()
    s += '\nMultiStage: 1\n'
    open(gs, 'w').write(s)
    with open(os.path.join(dst, 'settings/multi_stage_settings.yml'), 'w') as f:
        f.write(f"NumStages: {STAGES}\nStageLengths: {[LEN] * STAGES}\nWACC: {WACC}\n"
                f"ConvergenceTolerance: 1.0e-6\nMyopic: {1 if myopic else 0}\nWriteIntermittentOutputs: 0\n")
    json.dump(tr, open(os.path.join(dst, 'trajectory.json'), 'w'), indent=1)


if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    make(src, os.path.join(out, 'stageB_pf'), myopic=False)
    make(src, os.path.join(out, 'stageB_myopic'), myopic=True)
