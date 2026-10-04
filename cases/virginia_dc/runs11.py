import json, time
from tg_case9 import Case, run
B = dict(nondc_growth_override=0.01, carbon_price=22.0, net_zero=True)
P = {'none': dict(),
     'pause': dict(credit_flex=True),                                        # training can pause (credited for adequacy)
     'offpeak': dict(credit_flex=True, train_curtail_frac=0.0, train_budget=0.0, train_shift_frac=0.30),  # training rescheduled within the day only
     'inf_tou': dict(credit_flex=True, train_curtail_frac=0.0, train_budget=0.0, price_shift=0.20),       # time-of-use pricing for inference only
     'all': dict(credit_flex=True, train_shift_frac=0.30, price_shift=0.20)}
out = {}
for split in ('mckinsey', 'iea_inference', 'lbnl_half', 'training_heavy'):
    for pol, kw in P.items():
        k = f'{split}|{pol}|high'
        t = time.time(); out[k] = run(Case(**B, load_growth=0.035, split=split, **kw))
        json.dump(out, open('runs11.json', 'w'), default=float); print(k, round(time.time() - t), 's', flush=True)
for split in ('mckinsey', 'iea_inference'):
    for pol in ('none', 'all'):
        k = f'{split}|{pol}|mod'
        out[k] = run(Case(**B, load_growth=0.028, split=split, **P[pol])); json.dump(out, open('runs11.json', 'w'), default=float); print(k, flush=True)
