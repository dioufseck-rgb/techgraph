from run_demand_sweep import execute
p=execute(dict(seed=300,treatment='constant',epochs=72,horizon=4))
print(p['record']['status'],p['record']['elapsed_seconds'])
