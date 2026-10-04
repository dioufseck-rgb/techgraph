# Single-priority Jennings Randolph comparison — 4 October 2026

This experiment follows HANDOFF section 7, water step 1. It compares Techgraph with the unchanged standalone simulator; it does not validate either against PRRISM.

## Configuration

Run `TECHGRAPH_BACKEND=scipy OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 check_convergence.py --workers 3` from this directory.

The comparison uses all nine Historic demand scenarios, each over March 1930–March 1931 and January 1966–March 1967. Techgraph uses a ten-day recession forecast, `rule_offpotomac=True`, `same_info=True`, and JR_UP = JR_LO = 2. Other storage priorities retain the earlier rule-matched values. Equal values remove the JR priority discontinuity without changing physical capacity or removing the two storage variables.

The output records daily storage and deficits, aggregate comparisons, configuration, and source/input hashes in `results/convergence_single_zone.json`. Results are checkpointed after every completed run. No convergence tolerance has been chosen; the script reports differences rather than declaring PASS.

Both models start full at the beginning of each selected drought window. Techgraph uses the first date for initialization; paired statistics cover only dates actually realized by Techgraph. The standalone model still processes the initial date. This is not a continuous 1929–2009 simulation.

## Remaining structural differences found by inspection

- Standalone JR releases leave storage at dispatch, nine days before arrival. Techgraph schedules an arrival commitment and debits storage when it arrives. Reservoir storage curves therefore do not represent the same in-transit accounting.
- Standalone includes Vulcan quarry from 2040; Techgraph has no Vulcan design.
- `same_info=True` aligns access to actual next-day flow for load-shift decisions and allows same-day Little Seneca response. It does not make all formulas identical: Techgraph's stress trigger subtracts tributary inflows from Little Falls availability, and its projected rule decisions also depend on forecast storage.
- Standalone forecasts a day-nine gap using current withdrawals; Techgraph optimizes an entire forecast horizon, including future demands and storage values.
- Standalone draws Milestone (and Vulcan) under a stress rule. Techgraph commits optimized Milestone use.
- Reservoir refill, river accounting, and operating limits also differ. These differences have not been individually attributed by controlled experiments.

Consequently, matching minimum combined storage alone cannot establish equivalence. Daily storage trajectories and deficits are retained to expose differences hidden by a minimum.

## Completed results

All 18 runs completed using the SciPy backend. All runs have zero deficit days in both implementations. Minimum-storage differences range from -0.951 to +0.588 BG (Techgraph minus standalone). The previous 2030-medium/1930 gap closes to less than 0.001 BG, but convergence across all scenarios is **not established**.

| Demand scenario | Drought | Techgraph minimum (BG) | Standalone minimum (BG) | Difference (BG) | Maximum daily absolute difference (BG) |
|---|---|---:|---:|---:|---:|
| 2030_High | 1930 | 3.771 | 3.771 | +0.000 | 1.496 |
| 2030_High | 1966 | 6.948 | 6.713 | +0.235 | 1.955 |
| 2030_Low | 1930 | 9.561 | 9.507 | +0.054 | 0.790 |
| 2030_Low | 1966 | 11.506 | 11.224 | +0.283 | 1.391 |
| 2030_Medium | 1930 | 5.447 | 5.446 | +0.000 | 1.205 |
| 2030_Medium | 1966 | 9.533 | 9.196 | +0.337 | 1.795 |
| 2045_High | 1930 | 2.951 | 2.643 | +0.308 | 1.625 |
| 2045_High | 1966 | 4.305 | 3.717 | +0.588 | 2.027 |
| 2045_Low | 1930 | 4.524 | 5.475 | -0.951 | 0.951 |
| 2045_Low | 1966 | 8.928 | 9.114 | -0.186 | 1.402 |
| 2045_Medium | 1930 | 3.660 | 3.714 | -0.054 | 1.203 |
| 2045_Medium | 1966 | 5.862 | 6.175 | -0.313 | 1.853 |
| 2050_High | 1930 | 2.327 | 1.989 | +0.338 | 1.750 |
| 2050_High | 1966 | 3.501 | 3.642 | -0.141 | 2.069 |
| 2050_Low | 1930 | 3.740 | 4.541 | -0.802 | 1.000 |
| 2050_Low | 1966 | 8.326 | 8.613 | -0.288 | 1.423 |
| 2050_Medium | 1930 | 3.392 | 3.561 | -0.169 | 1.353 |
| 2050_Medium | 1966 | 4.962 | 5.283 | -0.322 | 1.830 |

The next development task is to align release/transit accounting and the remaining operating rules and facilities, then repeat this comparison with an explicit equivalence criterion. The full horizon scan and draft replacement should follow that reconciliation. No core model or existing scan configuration was changed in this experiment.

Verification in this follow-up: all 18 comparisons completed; unique scenario/window coverage, source/input hashes, and ordered daily trace lengths were checked. The full pytest suite and GenX benchmarks were not rerun.
