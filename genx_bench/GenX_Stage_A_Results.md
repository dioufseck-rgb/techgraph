# GenX benchmark, Stage A: results

## Summary

Techgraph reproduces GenX on a one-day, three-zone, greenfield capacity-expansion case. The objectives agree to within about 1e-15 in relative terms. Every built capacity agrees to within about 1e-11 MW. This holds on twelve test days, one per month. The 0.1% and 1% acceptance thresholds in the benchmark spec are therefore met by a wide margin.

Hourly dispatch differs on nine of the twelve days. Each difference is an alternative optimum with zero net cost. Most are shifts in the hour when a battery charges, with Massachusetts gas supplying the energy at a constant marginal cost. As the spec requires, these ties are identified rather than hidden.

## Setup

- GenX 0.4.5 on Julia 1.11.6, solved with HiGHS at 1e-8 tolerances.
- Inputs are the GenX example `1_three_zones` (New England: MA, CT, ME), at the v0.4.5 tag.
- Each case is a single day of 24 hours, weighted to a full year (8,760 hours).
- Unit commitment, ramp limits, minimum output, the CO2 cap, the minimum-capacity requirement, network expansion and time-domain clustering are switched off.
- Demand curtailment uses one segment at $50,000/MWh.
- The two existing transmission lines keep their fixed ratings and linear losses.
- Techgraph runs on its SciPy/HiGHS backend, at commit state v4 with default settings.

The Techgraph case is generated directly from the GenX input files, by `stageA_techgraph.py`. Both models therefore read one source.

## Mapping from GenX to Techgraph

The mapping uses only Techgraph's legacy design kinds. No model code was changed.

| GenX element | Techgraph representation | Exact? |
|---|---|---|
| Gas combined cycle | `convert`, fuel to electricity. Variable cost is VOM plus fuel price times heat rate. | Yes, because fuel prices are constant within each day. |
| Wind and solar | `renewable` with the zone's hourly availability profile. | Yes. |
| Battery, separate MW and MWh | A `store` for energy at a battery node, plus a lossless bidirectional `transport` link for power. | Nearly. See below. |
| Transmission line, loss L split half to each end | Existing bidirectional `transport` with loss L/(1+L/2) and capacity C(1+L/2). | Yes. |
| Unserved energy | Legacy unmet demand at the same value of lost load. | Yes. |

Two GenX battery constraints are not represented. First, GenX limits charge plus discharge in each hour to the power rating, while Techgraph limits each direction separately. Second, the GenX duration bounds (1 to 10 hours) are dropped. Neither binds in any of the twelve solutions. Batteries never charge and discharge in the same hour, and the chosen durations (about 1.1 to 1.5 hours) lie strictly inside the bounds. Because the problems are linear, dropping constraints that are slack at the optimum leaves the optimum unchanged.

One Techgraph default had to be overridden. Designs carry a default capacity cap of 5,000 MW, which GenX exceeds (5,614 MW of gas in Massachusetts on the reference day). The benchmark sets the cap to 1e7.

## Reference case: 14 September (day 257)

Day 257 was chosen as the reference because it builds the widest mix. It builds gas in two zones, wind in two zones and batteries in two zones. Maine builds no gas, so power must move across the network.

| Design | GenX | Techgraph |
|---|---|---|
| MA gas combined cycle (MW) | 5,613.660 | 5,613.660 |
| CT gas combined cycle (MW) | 1,691.183 | 1,691.183 |
| CT onshore wind (MW) | 5,780.672 | 5,780.672 |
| ME onshore wind (MW) | 4,026.578 | 4,026.578 |
| CT battery (MW / MWh) | 914.203 / 993.699 | 914.203 / 993.699 |
| ME battery (MW / MWh) | 137.089 / 149.010 | 137.089 / 149.010 |
| Annual objective ($) | 2,815,523,278 | 2,815,523,278 |

All other designs are zero in both models.

## All twelve days

Full results are in `stageA_all_days.csv`. In every case the relative objective difference is below 1.2e-15, the largest capacity difference is below 1.3e-11 MW, and simultaneous charge and discharge is zero. Dispatch differences, where present, have zero net cost (`dispatch_ties.py`).

## Limitations

- Solar is never built at the stock example costs, so the solar path is exercised only as a zero build. Its equations are the same as wind's.
- The stock example has no gas turbine. The spec listed one, but adding it would require invented cost data.
- One representative day is a strong simplification. It is adequate for testing equivalence, but not for drawing conclusions about the New England system.
- Agreement here shows that Techgraph's static legacy core solves the same linear program as GenX. It does not yet test Techgraph's rolling multi-period engine. That is the purpose of Stage B.

## Correction to the benchmark spec

Section 3.1 of the spec says Julia cannot be installed in this environment. That is no longer correct. Julia and GenX now run here, with packages fetched from GitHub. See `SETUP_JULIA.md`.

## Files

- `stageA_techgraph.py`: builds the Techgraph twin from a GenX case and compares the two.
- `stageA_all.py`: runs the comparison on every case in a directory.
- `dispatch_ties.py`: lists dispatch differences for one day and prices them.
- `make_genx_case.py`, `run_genx_cases.jl`: build and solve the one-day GenX cases.
- `genx_case_day257/`: the reference GenX inputs and key outputs.
- `stageA_all_days.csv`, `day257.json`: results.
