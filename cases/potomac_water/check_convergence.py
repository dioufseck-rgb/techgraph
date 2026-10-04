"""Controlled single-priority JR comparison; reports differences, not a pass threshold.

Run with TECHGRAPH_BACKEND=scipy python3 check_convergence.py [--workers 3].
The standalone model is unchanged. This is implementation comparison, not PRRISM validation.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time

os.environ.setdefault('TECHGRAPH_BACKEND', 'scipy')
import prrism_lite as PL
import tg_wma as TW

HERE = Path(__file__).resolve().parent
WINDOWS = {'1930': (dt.date(1930, 3, 1), dt.date(1931, 3, 31)),
           '1966': (dt.date(1966, 1, 1), dt.date(1967, 3, 31))}
VALUES = dict(OCC_UP=1., PAX_UP=1., MS=3., JR_UP=2., JR_LO=2.,
              LS_UP=4., LS_LO=10., OCC_LO=5., PAX_LO=5.)


def run_one(task):
    p, window = task
    started = time.monotonic()
    flows, _ = PL.load_flows(HERE / 'data/usgs_01646502_adjusted_little_falls.txt',
                            HERE / 'data/usgs_01638500_point_of_rocks.txt')
    k = PL.fit_recession(flows)
    start, end = WINDOWS[window]
    standalone = PL.simulate(flows, PL.Scenario(p['year'], p['annual_demand'][0]), k, start=start, end=end)
    policy = TW.Policy(rule_offpotomac=True, same_info=True, values=VALUES.copy())
    techgraph = TW.WMA(flows, p['year'], p['annual_demand'][0], k, policy=policy).run(start, end)
    # TG uses the first day for initialization. Compare identical realized dates.
    reference = {r[0]: r for r in standalone}
    paired = [reference[r[0]] for r in techgraph]
    a, b = TW.metrics(techgraph), PL.metrics(paired)
    gaps = [(x[1] - y[1]) / 1000 for x, y in zip(techgraph, paired)]
    return dict(scenario=f"{p['year']}_{p['demands']}", window=window,
                annual_demand_mgd=p['annual_demand'][0], recession=k,
                days=len(paired), techgraph=a, standalone=b,
                min_storage_difference_bg=a['min_LS_JRws_bg'] - b['min_LS_JRws_bg'],
                max_absolute_daily_storage_difference_bg=max(map(abs, gaps)),
                mean_absolute_daily_storage_difference_bg=sum(map(abs, gaps))/len(gaps),
                seconds=round(time.monotonic()-started, 2),
                daily=[dict(date=x[0].isoformat(), techgraph_storage_bg=x[1]/1000,
                            standalone_storage_bg=y[1]/1000, techgraph_deficit_mgd=x[2],
                            standalone_deficit_mgd=y[2]) for x, y in zip(techgraph, paired)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    pub = json.loads((HERE / 'data/wma_results.json').read_text())
    tasks = [(p, w) for p in pub.values() if p['flows'] == 'Historic' for w in WINDOWS]
    assert len(tasks) == 18
    files = ['tg_wma.py', 'prrism_lite.py', 'check_convergence.py', 'data/wma_results.json',
             'data/usgs_01646502_adjusted_little_falls.txt', 'data/usgs_01638500_point_of_rocks.txt']
    output = dict(backend=TW.solve.__module__, requested_backend=os.environ['TECHGRAPH_BACKEND'],
                  policy=dict(values=VALUES, same_info=True, rule_offpotomac=True, horizon=10, perfect=False),
                  planned_runs=len(tasks), completed_runs=0,
                  sha256={f: hashlib.sha256((HERE/f).read_bytes()).hexdigest() for f in files}, results=[])
    target = HERE / 'results/convergence_single_zone.json'
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, task) for task in tasks]
        for future in as_completed(futures):
            result = future.result()
            output['results'].append(result)
            output['results'].sort(key=lambda r: (r['scenario'], r['window']))
            output['completed_runs'] = len(output['results'])
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(output, indent=2)+'\n')
            temporary.replace(target)
            print(f"{output['completed_runs']}/18 {result['scenario']} {result['window']}: "
                  f"TG={result['techgraph']['min_LS_JRws_bg']:.3f} "
                  f"standalone={result['standalone']['min_LS_JRws_bg']:.3f} "
                  f"delta={result['min_storage_difference_bg']:+.3f} BG", flush=True)


if __name__ == '__main__':
    main()
