"""Generate exact, auditable tables after the complete campaign."""
from pathlib import Path
import gzip,json
from plot_demand_sweep import LABELS

ROOT=Path('results/demand_v3_resolved/analysis')
OUT=Path('../../synthesis').resolve()

def fm(x,places=2):return f'{x:+.{places}f}'
def cell(s):return f"{fm(s['median'])} [{fm(s['q25'])}, {fm(s['q75'])}]"

def main():
    s=json.loads((ROOT/'summary.json').read_text())
    assert s['complete']==s['planned']==500
    lines=['# Demand sweep: complete numerical results','',
           '500 complete histories; 24 world ancestries; 36,480 simulated periods. Main comparisons use 480 histories. All numbers are exploratory.',
           '', '## Matched demand changes against constant demand','',
           'Every row contains 24 matched-world differences. Values are median [first quartile, third quartile]. Percentage-point differences are abbreviated pp.', '',
           '| Demand condition | Process-set change frequency (pp) | Net process-capacity change (pp) | Fulfillment (pp) | New designs substantially used (count) |',
           '|---|---:|---:|---:|---:|']
    for t in LABELS:
        if t=='constant':continue
        e=s['effects'][f'{t}__constant']['metrics']
        lines.append('| '+LABELS[t]+' | '+' | '.join(cell(e[m]) for m in ['reconfiguration_pct','capacity_change_pct','fill_pct','new_major_designs_used'])+' |')
    lines+=['','## Contrasts that isolate placement, ordering and return','',
            '| Contrast | Process-set changes (pp) | Fulfillment (pp) | Direct cost (synthetic units) | Late functional activity distance |',
            '|---|---:|---:|---:|---:|']
    selected=['irregular85__irregular0','cycle16__cycle24','geo_far50__geo_ref50','geo_far80__geo_ref80','geo_return80__geo_ref80','mix_return80__constant']
    for key in selected:
        t,c=key.split('__');e=s['effects'][key];m=e['metrics']
        lines.append('| '+LABELS[t]+' − '+LABELS[c]+' | '+' | '.join(cell(m[k]) for k in ['reconfiguration_pct','fill_pct','direct_cost'])+' | '+cell(e['late_functional_tv'])+' |')
    lines+=['','## Direction counts for every selected contrast','',
            'Counts are lower / numerically tied / higher than the control; tolerance is 1e−7 in the reported metric. They are not significance tests.', '',
            '| Contrast | Metric | Lower / tied / higher | Full observed range |','|---|---|---:|---:|']
    for key in selected+['growth40__constant','decline40__constant','mix_a80__constant','mix_b80__constant']:
        t,c=key.split('__');e=s['effects'][key]
        for m in ['reconfiguration_pct','fill_pct','new_major_designs_used','direct_cost']:
            z=e['metrics'][m]
            lines.append(f"| {LABELS[t]} − {LABELS[c]} | {m} | {z['lower']} / {z['tied']} / {z['higher']} | {fm(z['minimum'])} to {fm(z['maximum'])} |")
    lines+=['','## Return-to-demand comparisons','',
            'Demand is identical again during the late window, epochs 60–67. The control for geographic return is stationary concentration at the reference site. Other excursions use constant baseline demand.', '',
            '| Excursion | Median functional activity-share distance | Histories with same functional set in every late epoch | Median capacity-vector relative L1 distance |',
            '|---|---:|---:|---:|']
    for t,c in [('geo_return80','geo_ref80'),('mix_return80','constant'),('cycle16','constant'),('cycle24','constant'),('pulse40','constant'),('irregular0','constant'),('irregular85','constant')]:
        e=s['effects'][f'{t}__{c}']
        lines.append(f"| {LABELS[t]} | {e['late_functional_tv']['median']:.4f} | {e['late_same_functional_every_epoch']} / 24 | {e['late_capacity_relative_l1']['median']:.4f} |")
    lines+=['','## Threshold sensitivity','',
            'Reconfiguration effects at 0.05%, 0.1% and 0.2% of required mass rate. Entries are median difference in percentage points.', '',
            '| Contrast | 0.05% | 0.1% | 0.2% |','|---|---:|---:|---:|']
    for key in selected+['growth40__constant','decline40__constant']:
        e=s['effects'][key]['metrics']
        lines.append('| '+key+' | '+' | '.join(fm(e[k]['median']) for k in ['reconfiguration_pct_0.0005','reconfiguration_pct','reconfiguration_pct_0.002'])+' |')
    lines+=['','## Measurement notes','',
            '- Process-capacity growth compares means of epochs 60–67 and 4–7. Capacities of serial stages add, so this is not final-service capacity.',
            '- Fulfillment is total delivered / required over epochs 8–67. Cost excludes unmet-demand penalties; it uses the model’s synthetic units.',
            '- Functional activity distance is total variation between process-activity shares after collapsing identical physical recipes. It can differ even when the substantial process sets match.',
            '- Return effects are observed for a finite window. They neither establish permanent lock-in nor rule it out.',
            '- All 20 longer controls reproduce the first 69 periods exactly. The primary analysis excludes the last four periods of the short histories.',
            '- See DEMAND_SWEEP_DESIGN.md for exact inputs, matching, source identity and limitations.', '']
    OUT.mkdir(exist_ok=True)
    (OUT/'Techgraph_Demand_Numerical_Results.md').write_text('\n'.join(lines))
    # Compact provenance for other readers and future analyses.
    (OUT/'demand_sweep_summary.json').write_text(json.dumps(s,indent=2)+'\n')
    print(OUT/'Techgraph_Demand_Numerical_Results.md')

if __name__=='__main__':main()
