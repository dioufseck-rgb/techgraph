# Demands associated with actors

## Purpose

A physical network and the rules that govern it rarely cover the same territory. In the Virginia case, the network is the whole PJM Dominion zone, while the state mandates and the residential bill cover only Dominion Energy Virginia's customers. Cooperatives such as NOVEC share the same transmission system but sit outside those rules. A model needs to know which load belongs to whom.

## The mechanism

`techgraph.demands.Demand(name, location, profile, owner, segment)` describes one load. `Scenario.demands` holds any number of them. Demands at the same location add together in the physical balance, so the network still sees one load per location. Their identity is kept for two uses:

- **Institutions.** `EnergyShare(base_owners=..., base_segments=...)` defines a share on one entity's sales, or on some segments only. `AccreditedCapacity(owners=..., segments=...)` defines an obligation for one entity's peak, and `locations=...` for a constrained area.
- **Accounting.** `demands.shares(sc, by='owner' | 'segment', at='peak' | 'energy')` returns shares of the coincident peak or of weighted energy, for attributing costs.

The legacy `Scenario.extra_demand` field still works. Its entries are treated as demands with no owner or segment. With no demands declared, every equation is unchanged.

## Files changed

`demands.py` (new), `catalog.py` (field), `dynamic.py` and `model.py` (location totals from all demands; each window records demand parts with their owner and segment), `flows.py` (legacy detection), `institutions.py` (owner and segment filters).

## Tests

`tests/test_institutions.py` checks that declaring loads as owned demands reproduces the legacy solution exactly, and that a share and an obligation defined on one owner use only that owner's demand. The full suite gives 694 passed and the same 3 pre-existing failures. The GenX Stage A and multi-day benchmarks still match exactly.

## Not yet represented

Supply does not carry owners. Cost attribution to owners is therefore a rule applied outside the optimization, as in the Virginia case, rather than a property of the model. Owner-tagged designs, and contracts between owners, would be the next step.

## Flexibility

A demand can be flexible. `curtail_max_frac`, `curtail_budget` and `curtail_cost` allow part of the load to be curtailed in any period, within an annual energy budget, at a cost; moving work out of the modeled system counts as curtailment. `shift_frac` and `shift_cost` allow part of the load to move between periods of the same representative day, energy-neutral within the day. Both engines add the corresponding variables; `model.solve` reports them in `Result.flexibility`, and balance checks include them.

Whether a rule counts flexibility is the rule's choice: `AccreditedCapacity(credit_flexibility=True)` sizes the requirement to the firm part of flexible demands (`demands.firm_profile`). The credit is valid only when the constraint binds in few enough hours for the budget to cover them. In the Virginia case, crediting flexibility for zone adequacy was sound; crediting it for deliverability into Northern Virginia, which binds most hours, produced large unserved demand.

Not yet represented: limits on the length of each curtailment event, and a credit that adjusts automatically to how often a constraint binds.

Tests: `tests/test_institutions.py` (flexibility off changes nothing; curtailment respects its budget and reduces capacity; shifting is energy-neutral within the day; adequacy can credit flexible load). Full suite: 698 passed, with the 3 pre-existing failures.


## Substances and priority

A demand has a substance (`form`, electricity by default). Demands for other substances enter their own balances,
with the same unmet-demand backstop at the value of lost load. Renewable resources likewise produce their declared
`form_out`, electricity by default. The engine creates balances for the catalog's standard forms and for any other
substance referenced by designs or demands, so existing scenarios keep exactly the same balances.

A demand can carry a `shortage_cost`: it may then go unserved at that cost per unit, which expresses priority.
`policy.apply_priority` assigns decreasing shortage costs by rank (for example, municipal before agricultural use).
