# Demand-coordinate sweep v3

29 September 2026. The campaign specification was frozen at launch. Analysis is exploratory; response measurements can be extended without changing the simulations.

## Purpose

Separate demand scale, temporal ordering, geographical concentration, placement and service composition in the richer stateful invention model. Observe expansion, contraction, substitution and recurrence without prescribing any technological response. This is a discovery sweep, not an attractor experiment or a calibrated forecast.

## Design and scope

- 24 new world seeds, 300–323. Three/four locations crossed with sparse/dense graph priors, six seeds per cell. Six initial material forms and two required services. Sparse/dense priors also use four/eight extra recipes; they are world families, not isolated graph-density interventions.
- 20 demand conditions per world, 72 periods: 480 main histories.
- 20 boundary controls: first four seeds, constant/growth40/cycle16/geo_return80/mix_return80, extended to 96 periods. Conditions selected before outcomes.
- 500 planned histories, 36,480 periods. Four pilot histories on other seeds 290/291 are excluded from findings.
- One mass-conserving abstract grammar; fixed resource availability, inventories, aged inherited equipment, capability acquisition/renewal, construction delays, free persistent knowledge and recursive invention. No target architecture, adoption path, named trap or convergence outcome is built in.
- One coordinating planner, horizon four, current demand assumed to persist. This sweep measures demand effects under that policy. It does not isolate forecast error from physical constraints.

## Exact demand factorization

For service i, location j and period t:

`d[i,j,t] = base_total * scale[t] * service_share[i,t] * geographic_share[j,t]`.

Both services begin at every site, with equal service shares and uniform geographic shares. Baseline total is inherited from the generator's original sum of required quantities. The old localized demands are replaced, then assets and readiness are reinitialized under the original one-period, current-condition rule. Assets receive independently keyed ages. No future needs enter initialization. This is a new experiment, not a like-for-like continuation of old seeds 120–151.

Supply margin is independently sampled in [0.95,1.65]; inventory capacity scale in [0.5,2]. Every site has some raw supply. All 20 treatments in a world have identical initial catalogues, assets, readiness, stores, supply and proposal streams. These are checked from the raw traces, together with their identical realized first eight periods.

## Demand conditions

| Condition | Definition |
|---|---|
| constant | All demand coordinates remain at baseline. |
| growth20 / growth40 | Scale rises linearly from 1 at period 8 to 1.2/1.4 at 55, then stays there. |
| decline20 / decline40 | Scale falls linearly to 0.8/0.6 on the same schedule. |
| cycle16 / cycle24 | Scale = 1 + 0.4 sin(2π(t−8)/P), periods 8–55; baseline thereafter. Three/two complete cycles; identical total volume and RMS. |
| irregular0 / irregular85 | Same Gaussian innovation tape filtered with persistence 0/0.85, then rank-mapped onto the same 48 values evenly spaced from 0.6 to 1.4. Exact same realized value distribution, cumulative volume and RMS; different ordering. These rank-mapped paths are not exact AR(1) processes. |
| pulse40 | Scale 1.4 during periods 24–39, otherwise 1. |
| geo_ref50 / geo_ref80 | Geographic weights `(1−α)/n + α at reference`, α ramping from zero at 8 to 0.5/0.8 at 15, then fixed. |
| geo_far50 / geo_far80 | Identical concentration schedule, with its center at the distant site. |
| geo_return80 | Same as geo_ref80 until period 24; permute weights to distant site for 24–47; return to reference at 48. Concentration, total and service mix remain exactly matched to geo_ref80 at every period. |
| mix_a65 / mix_a80 | Service A rises from 50% at 8 to 65%/80% at 55, then holds. Total and geography stay fixed. |
| mix_b65 / mix_b80 | Symmetric change toward service B. |
| mix_return80 | Service A rises linearly from 50% at 8 to 80% at 32, returns to 50% at 56, then holds. |

Reference site: greatest raw-resource use in the new baseline's one-period initialization. Distant site: farthest Euclidean site from that reference. This does not guarantee that the reference is optimal for every service or future period. Placement compares permutations of exactly the same weights. With n sites, normalized concentration `(HHI−1/n)/(1−1/n) = α²`; the dominant-site share is `α+(1−α)/n`, not α itself.

Trends and the positive pulse intentionally have different cumulative volume from constant demand. Do not attribute their effects solely to temporal shape. Cycles have the same total volume as baseline. The two irregular paths match their entire realized marginal distributions. Composition and all geography conditions match aggregate demand exactly.

## Observation rules

- Primary intervention window: epochs 8–67 inclusive; final four epochs excluded. Pre-intervention reference: mean of 4–7. Late state: mean of 60–67.
- Reconfiguration frequency: percentage of 60 adjacent transitions whose substantial process set changes. Substantial means activity above 0.1% of current required rate; sensitivity at 0.05% and 0.2% is retained. Storage/disposal excluded from process sets.
- Functional signatures collapse design identity/cost but preserve material ports, locations and coefficients. Generated intermediate forms remain distinct. This is one declared notion of functional equivalence, not all possible substitutes.
- Net physical growth: change in summed alive process capacity. Serial stages contribute separately, so this is not equivalent to final service capacity. Net delivered-service change is recorded separately.
- Additional exploratory path measures: sum of absolute capacity changes, endpoint displacement divided by that path length, and direction reversals among changes exceeding 0.1% of pre-intervention capacity. These distinguish a nearly one-way path from repeated expansion/contraction; reversals alone do not establish periodic oscillation.
- Expansion/contraction: functional set gains only / losses only at a transition. Mixed substitution: both. These labels describe set changes, not necessarily net installed-capacity changes.
- Recurrence: nonconsecutive reappearance of a previously seen substantial functional set within the observation window. No claim of a periodic orbit, basin or attractor follows.
- Functional activity shares and their total-variation distance retain magnitude information absent from set-change counts.
- Cross-site process activity / delivered service is an exposure proxy. It includes multi-location composite recipes; it is not physical transport distance or ton-kilometers.
- Service fulfillment, stocks, resource concentration, new-design use, orders/cancellations and cost excluding unmet-demand penalties are retained.
- Return experiments compare late states with their correct stationary counterfactual: geo_return80 versus geo_ref80; mix_return80 versus constant. Other volume excursions compare with constant. Differences can persist over the observed window; they do not establish permanent lock-in.
- Longer controls must reproduce realized periods 0–68 exactly; horizon-four windows first shorten at 69 in the 72-period histories.

## Integrity and reproducibility

Frozen simulator files are copied unchanged from the completed stateful-v2 checkpoint. New adapter and runner have distinct names; the old checkpoint is untouched. Main manifest pins all simulator and demand-generator source hashes and every specification before execution. Every published trace is fsynced, read back, decompressed and hashed by one parent writer. All statuses, exceptions and prefixes are retained. Complete traces must pass existing physical, stock, knowledge, accounting and lifecycle audits.

Commands, from `source/techgraph`:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m pytest -q tests/test_demand_sweep.py tests/test_stateful.py tests/test_generative.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python run_demand_sweep.py --mode main --workers 7 --out results/demand_v3
TECHGRAPH_BACKEND=scipy OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python run_demand_precision_repair.py --workers 4
TECHGRAPH_BACKEND=scipy OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python run_demand_precision_world323.py --workers 7
python resolve_demand_campaign.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python analyze_demand_sweep.py --data results/demand_v3_resolved
python plot_demand_sweep.py
```

Interrupted campaigns resume using the identical manifest/source, retaining completed traces. A changed scientific source requires a new output identity.

## Executed numerical repair

Two original histories (world 314, pulse40; world 323, growth20) failed the unchanged stock audit after 72 periods because accumulated solver feasibility errors reached 1.7693e−6 and 2.8626e−6 mass units, exceeding the 1e−6 audit threshold. Both original traces are retained. All 20 conditions of each affected world are rerun with native HiGHS primal, dual and MIP feasibility tolerances set to 1e−9; the model and audit thresholds remain unchanged. The accepted dataset is `results/demand_v3_resolved`, with 460 original histories and 40 matched precision reruns. See `provenance/numerical_precision_repair.md` for diagnosis and provenance.

When restoring the finished checkpoint, run `resolve_demand_campaign.py` to recreate its nonduplicated raw-trace view before rerunning analyses. The supplied completed analysis can be read directly. Simulation reruns are unnecessary for normal use of the checkpoint.
