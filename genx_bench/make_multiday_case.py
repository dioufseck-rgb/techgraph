"""Build a GenX case with several representative days and unequal weights (Stage A, multi-day)."""
import os, re, shutil, sys
import pandas as pd


def make(days, weights_h, dst, src='genx_repo/example_systems/1_three_zones'):
    assert abs(sum(weights_h) - 8760) < 1e-6
    shutil.rmtree(dst, ignore_errors=True); shutil.copytree(src, dst)
    n = len(days); T = 24 * n
    d = pd.read_csv(f'{dst}/system/Demand_data.csv'); zc = [c for c in d.columns if c.startswith('Demand_MW_z')]
    rows = pd.concat([d.iloc[day * 24:day * 24 + 24] for day in days]).reset_index(drop=True)
    E = [''] * (T - 1); W = list(weights_h) + [''] * (T - n)
    out = pd.DataFrame({'Voll': [50000] + E, 'Demand_Segment': [1] + E, 'Cost_of_Demand_Curtailment_per_MW': [1] + E,
                        'Max_Demand_Curtailment': [1] + E, 'Rep_Periods': [n] + E, 'Timesteps_per_Rep_Period': [24] + E,
                        'Sub_Weights': W, 'Time_Index': range(1, T + 1)})
    for c in zc: out[c] = rows[c].values
    out.to_csv(f'{dst}/system/Demand_data.csv', index=False)
    g = pd.read_csv(f'{dst}/system/Generators_variability.csv')
    g = pd.concat([g.iloc[day * 24:day * 24 + 24] for day in days]).reset_index(drop=True); g['Time_Index'] = range(1, T + 1)
    g.to_csv(f'{dst}/system/Generators_variability.csv', index=False)
    f = pd.read_csv(f'{dst}/system/Fuels_data.csv')
    body = f.iloc[1:]
    const = {c: float(body[c].mean()) for c in f.columns if c != 'Time_Index'}
    newf = pd.DataFrame([f.iloc[0].to_dict()] + [dict(const, Time_Index=t) for t in range(1, T + 1)])
    newf['Time_Index'] = [0] + list(range(1, T + 1)); newf.to_csv(f'{dst}/system/Fuels_data.csv', index=False)
    t = pd.read_csv(f'{dst}/resources/Thermal.csv'); t['Ramp_Up_Percentage'] = 1.0; t['Ramp_Dn_Percentage'] = 1.0; t['Min_Power'] = 0.0
    t.to_csv(f'{dst}/resources/Thermal.csv', index=False)
    s = open(f'{dst}/settings/genx_settings.yml').read()
    for k, v in {'NetworkExpansion': 0, 'CO2Cap': 0, 'MinCapReq': 0, 'UCommit': 0, 'TimeDomainReduction': 0, 'CapacityReserveMargin': 0,
                 'EnergyShareRequirement': 0, 'MaxCapReq': 0, 'OutputFullTimeSeries': 0, 'WriteShadowPrices': 0}.items():
        s = re.sub(rf'^{k}:\s*\d+', f'{k}: {v}', s, flags=re.M)
    open(f'{dst}/settings/genx_settings.yml', 'w').write(s)
    h = open(f'{dst}/settings/highs_settings.yml').read().replace('1.0e-05', '1.0e-08'); open(f'{dst}/settings/highs_settings.yml', 'w').write(h)
    shutil.rmtree(f'{dst}/policies', ignore_errors=True); shutil.rmtree(f'{dst}/resources/policy_assignments', ignore_errors=True)


if __name__ == '__main__':
    out = sys.argv[1]
    make([14, 104, 197, 287], [2000.0, 2500.0, 2260.0, 2000.0], f'{out}/four_days')
    make([14, 197], [5000.0, 3760.0], f'{out}/two_days')
