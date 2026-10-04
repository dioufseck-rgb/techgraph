import json, time
from tg_case10 import plan_case, run
P = {'none': dict(), 'pause': dict(credit_flex=True), 'offpeak': dict(credit_flex=True, train_curtail_frac=0.0, train_budget=0.0, train_shift_frac=0.30),
     'inf_tou': dict(credit_flex=True, train_curtail_frac=0.0, train_budget=0.0, price_shift=0.20), 'all': dict(credit_flex=True, train_shift_frac=0.30, price_shift=0.20)}
out = {}
for split in ('mckinsey', 'iea_inference', 'lbnl_half', 'training_heavy'):
    for pol, kw in P.items():
        k = f'{split}|{pol}|high'; t = time.time()
        out[k] = run(plan_case('CP', growth=0.035, workloads=True, split=split, **kw)); json.dump(out, open('runs21.json', 'w'), default=float); print(k, round(time.time() - t), 's', flush=True)
for split in ('mckinsey', 'iea_inference'):
    for pol in ('none', 'all'):
        k = f'{split}|{pol}|mod'; out[k] = run(plan_case('CP', workloads=True, split=split, **P[pol])); json.dump(out, open('runs21.json', 'w'), default=float); print(k, flush=True)
