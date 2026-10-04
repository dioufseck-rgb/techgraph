# Techgraph v4: analysis of the completed diagnostic runs

30 September 2026

## 1. What was run

Two diagnostics finished before the compute session ended. Both used the v4 source with only the named option switched on, and every run passed all existing audits.

The first is a forecast replay. Twenty-two demand histories were rerun with an oracle forecast, covering worlds 300–310 under the irregular0 (weakly persistent) and irregular85 (persistent) sequences. The oracle is a rolling four-period oracle: in each window the planner sees realized demand, but nothing beyond the window. It is not a full-horizon perfect-foresight bound. The comparison baseline is the archived v3 history for the same world and sequence, which uses the static forecast. All metrics come from the unchanged v3 analysis code. Worlds 300–310 cover all four design cells, but they are 11 of the 24 worlds.

The second is a relocation-fix replay. Forty-three of the 64 full-model stateful histories (worlds 120–141) were rerun with relocated designs requiring readiness at their destination.

The AR(1) forecast runs, the switching-cost replay and the infrastructure-lump test did not run.

## 2. Forecast replay

### 2.1 Better foresight raises service and reduces churn in every world

| Metric (median over 11 worlds) | irregular0, static | irregular0, oracle | irregular85, static | irregular85, oracle |
|---|---|---|---|---|
| Fulfillment, % | 90.7 | 99.9 | 94.5 | 98.2 |
| Periods with a process-set change, % | 66.7 | 35.0 | 58.3 | 28.3 |
| Activity shift per period (TV) | 0.089 | 0.045 | 0.058 | 0.041 |
| Capacity path length, % of initial | 668 | 410 | 469 | 332 |
| Direct cost per delivered unit | 5.12 | 4.92 | 4.98 | 4.89 |

Under weakly persistent demand, the oracle raises fulfillment in all 11 worlds, by a median of 7.5 points (range 4.8 to 13.1). It cuts the share of periods with a process-set change by a median of 20 points, also in all 11 worlds. Capacity moves much less, and direct cost per unit falls in 10 of 11 worlds. Persistent demand shows the same pattern with smaller gains.

Mean stock barely changes: the median difference is +0.16 under irregular0, and it falls in 3 of 11 worlds. The oracle's gains therefore come mainly from ordering capacity ahead of need through the construction leads, not from storing material. Storage stays a minor channel even when the planner can see the coming demand. This qualifies my earlier review, which attributed idle storage mainly to the static forecast.

### 2.2 The ordering effect reverses sign

This is the main result.

| Ordering effect (irregular85 minus irregular0) | Static forecast (v3) | Oracle forecast |
|---|---|---|
| Fulfillment, points | +1.93, higher in 11 of 11 | −1.74, lower in 9, tied in 2 |
| Periods with a process-set change, points | −6.7, lower in 9 of 11 | −3.3, lower in 6 of 11 |
| Activity shift per period | −0.030, lower in 11 of 11 | −0.007, lower in 10 of 11 |

Under the static forecast, persistent ordering improves fulfillment in every world. That is the published finding in paper §6.1. Under the oracle, persistent ordering lowers fulfillment in 9 of 11 worlds and ties in the other 2. The two ties, worlds 303 and 308, are the two with the largest supply margins (1.49 and 1.56), where service reaches 100% under both orderings.

The reversal has a plausible mechanism. A static forecaster's error depends on how much demand changes between periods, so persistence helps it. A forecaster that sees the coming periods has no such advantage. It then faces a different constraint: persistent sequences contain long runs of high demand, and in supply-limited worlds those runs exhaust raw supply and storage. Alternating highs and lows can be smoothed. This is an inference from the pattern across worlds, not a decomposition I have run.

The ordering effect on reconfiguration keeps its sign but weakens to about half. Its effect on activity shift weakens to about a quarter.

### 2.3 Implication for the paper

The finding that temporal ordering matters beyond variance survives: ordering changes fulfillment under both forecast rules. But its direction depends on the planner's forecast. The statement that persistent ordering improves fulfillment holds only for a myopic forecaster. It should be restated as an interaction between demand structure and the decision rule, and the oracle result should be reported beside it. The AR(1) runs would show where a realistic adaptive forecaster sits between the two. They should run before the section is revised.

## 3. Relocation-fix replay

All 43 reruns passed every audit. Forty were identical to the archived histories, including world 122, the example in paper §5.1.

Three histories differed. In two of them, worlds 133 and 139, the difference also appears when the unmodified code is rerun without the fix. World 139 has no relocated designs at all. These differences are at the level of solver noise between environments: at most 8e-7 in throughput and 1e-4 in objective. They are not effects of the fix.

The fix genuinely changed one history, world 132 at volatility 0.18. The history diverges first at period 57. The all-in objective falls by 23.0, or 0.7%, and the largest throughput change is 1.19. No capability acquisitions differ in kind, so the change comes from timing or location of readiness within existing domains.

Across the 43 histories, 127 relocated designs were documented, and 12 were operated both before and after the fix. The fix therefore corrects the semantics of local readiness without changing any published result. That is expected, given how cheap readiness is in these worlds.

## 4. Remaining work

The following runs are specified but not completed. Each step is resumable from the existing scripts.

1. Forecast replay: the 13 remaining oracle worlds, and the AR(1) rule on all 24.
2. Switching-cost replay: 48 histories on 12 worlds.
3. Infrastructure-only lumps: one smoke run.
4. Relocation fix: the 21 remaining stateful histories.
