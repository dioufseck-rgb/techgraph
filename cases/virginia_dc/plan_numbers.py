import json
p20, p21, p22 = (json.load(open(f)) for f in ('runs20.json', 'runs21.json', 'runs22.json'))
w = lambda yr: 1 if yr == 2025 else 2
cum = lambda r, f: sum(w(x['year']) * f(x) for x in r)
tot = lambda r: cum(r, lambda x: x['system_cost_musd']) / 1e3
res = lambda r: cum(r, lambda x: x['resource_cost_musd']) / 1e3
instate = lambda r: cum(r, lambda x: x['balance']['co2_mst'])
imports = lambda r: cum(r, lambda x: x['balance']['imports_twh'])
mtstorm = lambda r: cum(r, lambda x: 0.6 * x['balance']['generation'].get('COAL', 0.0) * 1.1)     # Mt Storm, counted as an import by the plan
consump = lambda r, f=0.45: instate(r) + f * imports(r) + mtstorm(r)
SCC = 262 / 1.1023                                                                                     # $/short ton
built = lambda r, n: sum(x['builds'].get(n, 0) for x in r) / 1e3
N = {}
for k, r in p20.items():
    e35 = next(x for x in r if x['year'] == 2035); e = r[-1]; g = e['balance']['generation']; L = e['balance']['load_twh']
    G = lambda ns: sum(g.get(n, 0) for n in ns) / L
    N[k] = dict(total=tot(r), resource=res(r), instate=instate(r), consumption=consump(r), imports=imports(r), shortfall=cum(r, lambda x: x.get('cap_shortfall_mst', 0.0)),
                bought=cum(r, lambda x: x.get('allowances_bought_mst', 0.0)), bill35=e35['bill'], bill49=e['bill'],
                imp_share49=e['balance']['imports_twh'] / L, co2_49=e['balance']['co2_mst'],
                mix49=dict(nuclear=G(('NUCLEAR', 'SMR', 'FUSION')), gas=G(('GAS_CC_EXIST', 'GAS_CT_EXIST', 'NEW_CC', 'NEW_CT', 'NEW_CT_NOVA')), solar_wind=G(('SOLAR', 'ONSHORE_WIND', 'ROOF_NOVA', 'ROOF_VA', 'DER_SOLAR')),
                           osw=G(('OSW',)), coal=G(('COAL',)), fc=G(('FC_NOVA', 'FC_VA')), imports=e['balance']['imports_twh'] / L),
                built=dict(smr=built(r, 'SMR'), fusion=built(r, 'FUSION'), osw=built(r, 'OSW'), solar=built(r, 'SOLAR'), gas=built(r, 'NEW_CC') + built(r, 'NEW_CT'),
                           batt=built(r, 'BATT4') / 4, ldes=built(r, 'LDES12') / 10, fc=built(r, 'FC_NOVA') + built(r, 'FC_VA')),
                transfers=dict(rggi=cum(r, lambda x: x['transfers_musd']['rggi']) / 1e3, compliance=cum(r, lambda x: x['transfers_musd']['compliance']) / 1e3),
                energy=cum(r, lambda x: x['balance']['load_twh']))
    N[k]['scc_instate'] = SCC * N[k]['instate'] / 1e3; N[k]['scc_consumption'] = SCC * N[k]['consumption'] / 1e3   # $B
plan = dict(NP=295, CP=422, DF=385)
N['ratios'] = dict(plan_CP=422 / 295, plan_DF=385 / 295, model_CP_total=N['CP_mod']['total'] / N['NP_mod']['total'], model_DF_total=N['DF_mod']['total'] / N['NP_mod']['total'],
                   model_CP_res=N['CP_mod']['resource'] / N['NP_mod']['resource'], model_DF_res=N['DF_mod']['resource'] / N['NP_mod']['resource'])
dec = {}
for k, yr in (('CP_mod', 2035), ('CP_mod', 2049), ('CP_noDC', 2049)):
    e = next(x for x in p20[k] if x['year'] == yr); pp = e['cost_parts']; per = lambda m: m * 1e6 / pp['net_kwh'] * 1000
    dec[f'{k}_{yr}'] = dict(capacity=per(pp['res_cap']), energy=per(pp['energy_res']), other=per(pp['other_fixed']), bill=e['bill'])
N['decomposition'] = dec
cp = {}
for key, r in p21.items():
    sp, pol, dem = key.split('|'); b = p21[f'{sp}|none|{dem}']
    cp[key] = dict(sav_tot=tot(b) - tot(r), sav_res=res(b) - res(r), bill35=next(x for x in b if x['year'] == 2035)['bill'] - next(x for x in r if x['year'] == 2035)['bill'],
                   d_instate=instate(r) - instate(b))
N['compute'] = cp
N['compute_base_total_high'] = {sp: tot(p21[f'{sp}|none|high']) for sp in ('mckinsey', 'iea_inference', 'lbnl_half', 'training_heavy')}
rel = {}
for key, v in p22.items():
    sp = key.split('|')[0]; rel[key] = dict(sav_tot=p22[f'{sp}|none']['cum'] - v['cum'], sav_res=p22[f'{sp}|none']['cum_res'] - v['cum_res'], stress=v['stress'])
N['reliability'] = rel
json.dump(N, open('plan_numbers.json', 'w'), indent=1, default=float)
print('ok')
