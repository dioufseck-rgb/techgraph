# GenX benchmark, Stage B: results

## Summary

Techgraph's dynamic engine reproduces GenX's multi-stage planning in both of GenX's modes.

- **Perfect foresight.** Techgraph's single full-horizon window gives a present-value cost of $56,712,421,772.68. GenX's dual dynamic programming (DDP), converged to a tolerance of 1e-9, gives the same value to the cent. Every capacity in every stage agrees to within 6e-9 MW.
- **Myopic.** Techgraph's one-epoch rolling policy reproduces GenX's myopic capacity path to within 1.5e-11 MW in every stage.
- **The cost of myopia.** Priced with one common rule, the myopic path costs 0.7718% more than the perfect-foresight path. The figure is identical in both models.

The spec's Stage B criteria are therefore met: the full-horizon solves agree within the Stage A tolerances, and the myopic-to-foresight gap is the same in both models.

A further result concerns Techgraph alone. With the static forecast, every horizon from 1 to 5 gives exactly the myopic path. This suggests that, in settings like this one, static-forecast results behave as myopic results regardless of horizon. It may bear on the earlier forecast-ordering result and should be checked in the v4 setting.

## Case

The case extends the Stage A reference day (14 September) to six investment stages of five years each, 30 years in total.

- Demand grows 2% per year in every zone.
- Annualized investment cost falls 2% per year for wind, 5% for solar and 6% for batteries (both power and energy).
- Gas investment cost, fuel prices and all fixed O&M are constant.
- The discount rate (WACC) is 4.5%, applied system-wide and to every technology.
- Lifetimes and capital recovery periods are 60 years, so nothing retires within the horizon and capital is paid to the end of the horizon.
- All Stage A simplifications still apply: no unit commitment, no policies, fixed existing transmission, one representative day per stage.

GenX runs in two modes. Myopic mode solves each stage alone with earlier capacity fixed. The perfect-foresight mode uses DDP, which iterates until its upper and lower bounds meet. At the default tolerance used first (1e-6), DDP stopped with a path about $12,000 above the optimum, and capacities differed from Techgraph's by up to 21 MW. At 1e-9 the bounds met exactly and the difference vanished.

## Mapping of the cost accounting

GenX and Techgraph account for multi-stage costs differently on the surface, but the perfect-foresight objectives are equal up to one constant factor. The derivation is in the header of `stageB_techgraph.py`.

- One Techgraph epoch is one GenX stage. The epoch discount factor is (1.045)^-5.
- Each design's Techgraph annual cost is the GenX annualized investment divided by 1.045, plus fixed O&M. The division reflects that GenX pays investment at the end of each year but discounts operating costs from the start of each year.
- Techgraph's fixed O&M share and aging are set to zero, and design lives exceed the horizon. With these settings, Techgraph charges each vintage its full annual cost in every epoch from build to the horizon end, which is what GenX's truncated overnight cost does.
- The Techgraph window objective, multiplied by 365 and by GenX's multi-year operating factor (4.587 for five years at 4.5%), equals the GenX objective.

GenX's myopic mode keeps undiscounted annualized costs, so the Techgraph myopic twin uses investment plus fixed O&M, without the division by 1.045.

Fixed O&M must be constant across stages for this mapping. GenX charges each stage's fixed O&M rate to all installed capacity, whereas Techgraph charges each vintage the rate at which it was built.

## Capacity paths

Perfect foresight (GenX and Techgraph identical):

| | S1 | S2 | S3 | S4 | S5 | S6 |
|:--|--:|--:|--:|--:|--:|--:|
| Gas (MW) | 9,941 | 9,941 | 9,941 | 9,941 | 9,975 | 10,632 |
| Wind (MW) | 5,888 | 7,937 | 10,245 | 11,502 | 12,563 | 13,556 |
| Solar (MW) | 0 | 0 | 0 | 0 | 0 | 1,431 |
| Battery power (MW) | 1,006 | 1,097 | 1,187 | 2,225 | 3,490 | 4,468 |
| Battery energy (MWh) | 1,094 | 1,193 | 1,290 | 3,413 | 7,172 | 10,837 |

Myopic (GenX and Techgraph identical):

| | S1 | S2 | S3 | S4 | S5 | S6 |
|:--|--:|--:|--:|--:|--:|--:|
| Gas (MW) | 7,305 | 7,915 | 8,675 | 9,680 | 10,493 | 11,657 |
| Wind (MW) | 9,807 | 10,533 | 10,999 | 11,552 | 12,380 | 13,162 |
| Solar (MW) | 0 | 0 | 0 | 0 | 1,038 | 1,616 |
| Battery power (MW) | 1,051 | 1,429 | 1,969 | 2,385 | 3,049 | 3,576 |
| Battery energy (MWh) | 1,143 | 1,889 | 2,987 | 3,974 | 5,825 | 7,491 |

The two paths differ in a way that is consistent with the cost trajectory. With foresight, the planner builds most gas at the start and defers wind, solar and storage, because those technologies become cheaper. Without foresight, the planner builds wind early, adds gas gradually and adopts solar one stage earlier. By stage 6 the myopic system has more gas and less storage.

## The cost of myopia

All paths are priced with the GenX DDP rule. Operating costs for this pricing come from one evaluator, a fixed-capacity Techgraph LP for each stage. The pricing function reproduces GenX's own reported path cost to within $8, which checks it independently.

| Path | Present value ($) |
|:--|--:|
| GenX, perfect foresight (DDP at 1e-6) | 56,712,433,566 |
| Techgraph, perfect foresight | 56,712,421,773 |
| GenX, myopic | 57,150,126,623 |
| Techgraph, myopic | 57,150,126,623 |

The myopic penalty is +0.7718% in both models.

## Techgraph at shorter horizons

The spec asks for Techgraph runs at shorter horizons with the static forecast. GenX has no counterpart for horizons between 2 and 5. These runs use the perfect-foresight cost convention and the same pricing rule. A window charges capital only inside the window, which matches GenX's treatment of costs after the horizon as recoverable.

| Horizon (stages) | Static forecast | Rolling oracle |
|--:|--:|--:|
| 1 | +0.7795% | +0.7795% |
| 2 | +0.7795% | +0.6110% |
| 3 | +0.7795% | +0.2778% |
| 4 | +0.7795% | +0.1753% |
| 5 | +0.7795% | +0.0147% |
| 6 | — | 0 |

Gaps are relative to the full-foresight optimum.

The rolling oracle closes the gap steadily as the horizon grows. The static forecast does not improve at all. The reason appears to be structural. Under a static forecast, every future epoch in the window looks like the current one. Capital is charged per epoch as an annuity, so building ahead of need adds cost without any expected benefit. The window then repeats its first-epoch decision, which is the myopic decision.

This result was obtained without lumps, construction leads, aging or a positive fixed O&M share. Those mechanisms can make early building worthwhile even under a stationary forecast, so the equivalence may not hold in the v4 campaigns. It would be useful to test it there before interpreting static-forecast results.

The horizon-1 gap here (+0.7795%) differs slightly from the GenX myopic gap (+0.7718%) because of the cost convention. GenX's myopic mode charges full annualized investment, while these runs divide it by 1.045.

## Limitations

- Each stage is represented by one day. The results test the equivalence of the planning logic, not the realism of the New England system.
- Fixed O&M is held constant, and nothing retires. Techgraph's vintage-specific fixed O&M, aging and early retirement are therefore not tested against GenX.
- The benchmark runs Techgraph with fixed O&M share and aging set to zero. Techgraph's campaign defaults (0.2 and 0.05) are different, and Stage C is the natural place to measure their effect.
- GenX's perfect-foresight mode is an iterative decomposition. Its result depends on the convergence tolerance, as the 21 MW difference at 1e-6 shows.

## Files

- `make_stageB_case.py`: builds the GenX perfect-foresight and myopic cases from a Stage A case.
- `run_stageB.jl`: runs the GenX cases (set `STAGEB_DIR`, `STAGEB_CASES` and `GENX_ENV`).
- `stageB_techgraph.py`: runs the Techgraph twins, compares them with GenX and prices all paths.
- `stageB_horizons.py`: runs Techgraph at horizons 1 to 6 with static and oracle forecasts.
- `genx_stageB_cases/`: GenX inputs and results for the myopic, perfect-foresight (1e-6) and tight (1e-9) runs.
- `stageB_comparison.json`, `stageB_pf_tight_paths.json`, `stageB_horizons.json`: results.
