import json
p9, p10, p11, p12 = (json.load(open(f)) for f in ('runs9.json', 'runs10.json', 'runs11.json', 'runs12.json'))
w = lambda yr: 1 if yr == 2025 else 2
cum = lambda r, f: sum(w(x['year']) * f(x) for x in r)
tot = lambda r: cum(r, lambda x: x['system_cost_musd']) / 1e3
res = lambda r: cum(r, lambda x: x['resource_cost_musd']) / 1e3
tr = lambda r, k: cum(r, lambda x: x['transfers_musd'][k]) / 1e3
N = {}
# pathways
for k in ('NP_mod', 'CP_mod', 'DF_local_mod', 'DF_nuclear_mod', 'DF_limsolar_mod', 'NP_high', 'CP_high', 'DF_local_high', 'NP_low', 'CP_low', 'DF_local_low', 'DF_nonewgas_mod'):
    if k in p9: N[k] = dict(total=tot(p9[k]), resource=res(p9[k]), rggi=tr(p9[k], 'rggi'), compliance=tr(p9[k], 'compliance'), shadow_removed=tr(p9[k], 'shadow_removed'),
                            bill35=next(x for x in p9[k] if x['year'] == 2035)['bill'], bill49=p9[k][-1]['bill'])
N['ratio_total'] = N['CP_mod']['total'] / N['NP_mod']['total']; N['ratio_resource'] = N['CP_mod']['resource'] / N['NP_mod']['resource']
N['DF_vs_CP_total'] = N['DF_local_mod']['total'] / N['CP_mod']['total'] - 1; N['DF_vs_CP_resource'] = N['DF_local_mod']['resource'] / N['CP_mod']['resource'] - 1
N['DFnuc_vs_CP_total'] = N['DF_nuclear_mod']['total'] / N['CP_mod']['total'] - 1; N['DFnuc_vs_CP_resource'] = N['DF_nuclear_mod']['resource'] / N['CP_mod']['resource'] - 1
# rates and data-center effects
for k in ('CP', 'CP_noDC', 'R_assigned', 'R_smr_2x', 'R_no_smr', 'R_limits_relaxed', 'R_floor3'):
    r = p10[k]; N['r_' + k] = dict(total=tot(r), resource=res(r), bill35=next(x for x in r if x['year'] == 2035)['bill'], bill49=r[-1]['bill'],
                                   energy=cum(r, lambda x: x['balance']['load_twh']))
N['dc_per_mwh'] = dict(cp_total=1e3 * N['r_CP']['total'] / N['r_CP']['energy'], nodc_total=1e3 * N['r_CP_noDC']['total'] / N['r_CP_noDC']['energy'],
                       cp_res=1e3 * N['r_CP']['resource'] / N['r_CP']['energy'], nodc_res=1e3 * N['r_CP_noDC']['resource'] / N['r_CP_noDC']['energy'])
dec = {}
for k, yr in (('CP', 2035), ('CP', 2049), ('CP_noDC', 2049)):
    e = next(x for x in p10[k] if x['year'] == yr); p = e['cost_parts']; per = lambda m: m * 1e6 / p['net_kwh'] * 1000
    dec[f'{k}_{yr}'] = dict(capacity=per(p['res_cap']), energy=per(p['energy_res']), other=per(p['other_fixed']), bill=e['bill'])
N['decomposition'] = dec
# leakage
imp = lambda r: cum(r, lambda x: x['balance']['imports_twh']); zone = lambda r: cum(r, lambda x: x['balance']['co2_mst'])
N['leak'] = dict(d_imp=imp(p9['CP_mod']) - imp(p9['NP_mod']), d_zone=zone(p9['CP_mod']) - zone(p9['NP_mod']), imp_cp=imp(p9['CP_mod']),
                 zone_cp=zone(p9['CP_mod']), zone_np=zone(p9['NP_mod']))
lev = {}
for k in ('L_tie7', 'L_border', 'L_consumption_cap'):
    r = p10[k]; b = p10['CP']; dcr, dct = res(r) - res(b), tot(r) - tot(b); dz = zone(r) - zone(b); di = imp(r) - imp(b)
    lev[k] = dict(d_resource=dcr, d_total=dct, d_zone=dz, d_imp=di,
                  per_t={f: dict(net=dz + f * di, res=(1e3 * dcr / -(dz + f * di)) if dz + f * di < 0 else None,
                                 tot=(1e3 * dct / -(dz + f * di)) if dz + f * di < 0 else None) for f in (0.2, 0.45, 0.6)})
N['levers'] = lev
# compute policies
cp = {}
for key, r in p11.items():
    sp, pol, dem = key.split('|'); base = p11[f'{sp}|none|{dem}']
    cp[key] = dict(sav_res=res(base) - res(r), sav_tot=tot(base) - tot(r), bill35=next(x for x in base if x['year'] == 2035)['bill'] - next(x for x in r if x['year'] == 2035)['bill'])
N['compute'] = cp
rel = {}
for key, v in p12.items():
    sp = key.split('|')[0]; rel[key] = dict(sav_res=p12[f'{sp}|none']['cum_res'] - v['cum_res'], sav_tot=p12[f'{sp}|none']['cum'] - v['cum'], stress=v['stress'])
N['reliability'] = rel
json.dump(N, open('numbers.json', 'w'), indent=1, default=float)
print('ok')
