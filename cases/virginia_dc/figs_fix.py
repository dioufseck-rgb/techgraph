import json, os, numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.titlesize': 11, 'axes.titleweight': 'bold'})
BLUE, ORANGE, GREEN, GRAY, RED, PURPLE = '#2a78d6', '#eb6834', '#1baf7a', '#888780', '#c0392b', '#6250d6'
N = json.load(open('numbers.json')); p9 = json.load(open('runs9.json')); p10 = json.load(open('runs10.json'))
A = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figures') + '/'; L = A
# cost by pathway: total and resource, with plan ratio panel
paths = [('NP_mod', 'No Policy'), ('CP_mod', 'Current\nPolicies'), ('DF_local_mod', 'Distributed\nFlexibility,\nlocal'), ('DF_nuclear_mod', 'DF, nuclear,\nfewer imports'), ('DF_limsolar_mod', 'DF, limited\nsolar')]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.9), gridspec_kw={'width_ratios': [1.5, 1]})
x = np.arange(5); tt = [N[k]['total'] for k, _ in paths]; rr = [N[k]['resource'] for k, _ in paths]
a1.bar(x - 0.2, tt, 0.38, color=BLUE, label='Total, including transfers'); a1.bar(x + 0.2, rr, 0.38, color=GREEN, label='Resource cost, excluding transfers')
for i in range(5): a1.text(i - 0.2, tt[i] + 4, f'{tt[i]:.0f}', ha='center', fontsize=7.5); a1.text(i + 0.2, rr[i] + 4, f'{rr[i]:.0f}', ha='center', fontsize=7.5)
a1.set_xticks(x); a1.set_xticklabels([l for _, l in paths], fontsize=8); a1.set_ylabel('System cost 2026–2050, $ billion'); a1.set_ylim(0, 430)
a1.legend(frameon=False, fontsize=8, loc='upper left'); a1.set_title('Model: Dominion zone, moderate demand', loc='left')
pr = [1.0, 422 / 295, 385 / 295]; mt = [1.0, N['CP_mod']['total'] / N['NP_mod']['total'], N['DF_local_mod']['total'] / N['NP_mod']['total']]
mr = [1.0, N['CP_mod']['resource'] / N['NP_mod']['resource'], N['DF_local_mod']['resource'] / N['NP_mod']['resource']]
x3 = np.arange(3)
for off, vals, col, lab in ((-0.27, pr, GRAY, 'Energy Plan (statewide)'), (0, mt, BLUE, 'Model, total'), (0.27, mr, GREEN, 'Model, resource cost')):
    a2.bar(x3 + off, vals, 0.25, color=col, label=lab)
    for i, v in enumerate(vals): a2.text(i + off, v + 0.02, f'{v:.2f}', ha='center', fontsize=7)
a2.set_xticks(x3); a2.set_xticklabels(['No Policy', 'Current\nPolicies', 'Distributed\nFlexibility'], fontsize=8.5); a2.set_ylim(0, 1.75)
a2.set_ylabel('Cost relative to No Policy'); a2.legend(frameon=False, fontsize=7.5, loc='upper left'); a2.set_title('Relative cost: plan and model', loc='left')
fig.tight_layout(); fig.savefig(A + 'f1_cost.png', dpi=180); plt.close(fig)
# leakage levers, resource basis at 0.45
lev = [('L_tie7', 'Import ceiling\n7 GW from 2029'), ('L_border', 'RGGI price\non imports'), ('L_consumption_cap', 'Net-zero cap\ncounting imports')]
avoid = [-N['levers'][k]['per_t']['0.45']['net'] for k, _ in lev]; pt = [N['levers'][k]['per_t']['0.45']['res'] for k, _ in lev]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.4))
a1.bar(range(3), avoid, 0.55, color=GREEN); a2.bar(range(3), pt, 0.55, color=ORANGE)
for i, v in enumerate(avoid): a1.text(i, v + 3, f'{v:.0f}', ha='center', fontsize=8.5)
for i, v in enumerate(pt): a2.text(i, v + 3, f'${v:.0f}', ha='center', fontsize=8.5)
for a in (a1, a2): a.set_xticks(range(3)); a.set_xticklabels([l for _, l in lev], fontsize=8)
a1.set_ylabel('Million tons avoided, 2026–2050'); a2.set_ylabel('Resource cost per ton avoided ($)')
a1.set_title('Emissions avoided (including imports)', loc='left'); a2.set_title('Resource cost per ton', loc='left')
fig.tight_layout(); fig.savefig(A + 'f4_leakage.png', dpi=180); plt.close(fig)
# bills
Y = [x['year'] for x in p10['CP']]
fig, ax = plt.subplots(figsize=(8.5, 4.0))
for k, src, lab, col, ls in (('NP_mod', p9, 'No Policy', GRAY, '-'), ('CP', p10, 'Current Policies', BLUE, '-'), ('CP_noDC', p10, 'Current Policies, no data-center growth', PURPLE, '--'),
                             ('R_assigned', p10, 'Current Policies, costs assigned to data centers', GREEN, ':'), ('R_smr_2x', p10, 'Current Policies, reactors at double cost', RED, '-.')):
    b = [x['bill'] for x in src[k]]; ax.plot(Y, b, color=col, ls=ls, lw=2, label=f'{lab} (2050: ${b[-1]:.0f})')
ax.set_ylabel('$ per 1,000 kWh, constant dollars'); ax.set_title('Typical Dominion Virginia residential bill', loc='left'); ax.legend(frameon=False, fontsize=8, loc='upper left')
fig.tight_layout(); fig.savefig(A + 'f5_bills.png', dpi=180); fig.savefig(L + 'fig_bills.png', dpi=180); plt.close(fig)
# bill decomposition
D = N['decomposition']; bars = [('CP_2035', 'Current Policies\n2035'), ('CP_2049', 'Current Policies\n2050'), ('CP_noDC_2049', 'No data-center\ngrowth, 2050')]
fig, ax = plt.subplots(figsize=(7.5, 3.6)); bottom = np.zeros(3)
for name, key, col in (('Generation and transmission capacity', 'capacity', BLUE), ('Energy', 'energy', ORANGE), ('Distribution and other', 'other', GRAY)):
    v = np.array([D[k][key] for k, _ in bars]); ax.bar(range(3), v, 0.55, bottom=bottom, color=col, label=name); bottom += v
for i, (k, _) in enumerate(bars): ax.text(i, bottom[i] + 4, f"${D[k]['bill']:.0f}", ha='center', fontsize=8.5)
ax.set_xticks(range(3)); ax.set_xticklabels([l for _, l in bars], fontsize=8.5); ax.set_ylabel('$ per 1,000 kWh'); ax.set_ylim(0, 320)
ax.legend(frameon=False, fontsize=8, loc='upper left'); ax.set_title('What the bill pays for', loc='left')
fig.tight_layout(); fig.savefig(A + 'f6_decomposition.png', dpi=180); fig.savefig(L + 'fig_decomp.png', dpi=180); plt.close(fig)
# compute policies (total basis, as cited)
C = N['compute']
splits = [('iea_inference', 'Low AI share,\nmostly inference\n(AI 15% → 59%)'), ('mckinsey', 'High AI share,\nmostly inference\n(AI 53% → 85%)'), ('lbnl_half', 'Training and\ninference equal\n(AI 40% → 70%)'), ('training_heavy', 'Mostly\ntraining\n(AI 50% → 70%)')]
pols = [('pause', 'Pause training', '#1baf7a'), ('offpeak', 'Shift training within the day', '#5dcaa5'), ('inf_tou', 'Time-of-use pricing for inference', '#2a78d6'), ('all', 'All three combined', '#6250d6')]
plt.rcParams.update({'font.size': 10.5, 'axes.titlesize': 11.5})
fig, ax = plt.subplots(figsize=(8.5, 4.4)); xx = np.arange(4); wd = 0.2
for i, (p, lab, col) in enumerate(pols):
    ax.bar(xx + (i - 1.5) * wd, [C[f'{sp}|{p}|high']['sav_tot'] for sp, _ in splits], wd, color=col, label=lab)
ax.set_xticks(xx); ax.set_xticklabels([l for _, l in splits]); ax.set_ylabel('$ billion saved, 2026–2050'); ax.set_ylim(0, 14.5)
ax.legend(frameon=False, fontsize=9, loc='upper left'); ax.set_title('System-cost savings from compute policies, by workload mix', loc='left')
fig.tight_layout(); fig.savefig(L + 'fig3_single.png', dpi=200); fig.savefig(A + 'f8_compute_single.png', dpi=200); plt.close(fig)
print('figures done')
