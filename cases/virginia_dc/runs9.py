import json, time
from tg_case9 import Case, run
B = dict(nondc_growth_override=0.01)
CP = dict(carbon_price=22.0, net_zero=True)
DF = dict(CP, credit_flex=True, price_shift=0.20, fuel_cells=True, der_solar_2035=2_000.0, vpp_2035=1_500.0)
cases = {}
for dname, g in (('mod', 0.028), ('low', 0.023), ('high', 0.035)):
    cases[f'NP_{dname}'] = Case(**B, load_growth=g, institutions_on=False)
    cases[f'CP_{dname}'] = Case(**B, load_growth=g, **CP)
    cases[f'DF_local_{dname}'] = Case(**B, load_growth=g, **DF)
cases['DF_nuclear_mod'] = Case(**B, load_growth=0.028, **DF, import_cap_mw=6_500.0, import_cap_from=2029, smr_from=2031, smr_cost=650_000.0)
cases['DF_nonewgas_mod'] = Case(**B, load_growth=0.028, **DF, no_new_gas=True)
cases['DF_limsolar_mod'] = Case(**B, load_growth=0.028, **DF, solar_rate=1_250.0)
out = {}
for k, c in cases.items():
    t = time.time(); out[k] = run(c)
    json.dump(out, open('runs9.json', 'w'), default=float)
    print(k, round(time.time() - t), 's', flush=True)
