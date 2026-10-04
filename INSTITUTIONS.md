> **Note (October 2026).** The classes described here are now declarations. `institutions.to_primitive` converts each
> into a generic primitive from `techgraph/policy.py` (Requirement, Adequacy or Charge), and only primitives are
> evaluated. Primitives can be passed directly. See `TECHGRAPH_SPACE_AND_POLICY_DESIGN.md`.

# Institutions in Techgraph

## Purpose

The theory treats technological change as a process shaped by society and nature. Institutions are one of the main channels of that shaping. They decide what may be built, how fast, at what price, and in what proportions. Without an explicit representation, institutional effects end up hidden inside cost assumptions, and the model cannot separate what physics requires from what rules require.

## Where institutions act

Institutions act on the technology layer at four points.

| Point of action | Examples | Representation |
|:--|:--|:--|
| What may be built, where and when | Siting and air-permit rules, approvals, moratoria | `forbid`, `Trajectory.avail_from` and `avail_until` |
| How fast it may be built | Permitting, interconnection queues | `Trajectory.build_rate` |
| Prices of building and operating | Tax credits, carbon prices | `Trajectory.cost_mult`, fuel price paths |
| Aggregate requirements across designs | Portfolio standards, procurement mandates, adequacy requirements, emission caps | `techgraph.institutions` (new) |

Rules that act on agents rather than on the network belong to the society layer outside the substrate. Examples are cost allocation among customer classes, export credits for rooftop solar, and where developers choose to site new load. These actors read substrate outputs, such as costs, prices and deliverability, and feed decisions back.

## Principles

1. **Declared, not embedded.** Each institution is an object with a name and a schedule, kept separate from the technology catalog. The catalog describes physics and cost. Institutions describe rules.
2. **Escape valves are part of the rule.** Most real requirements can be missed at a price, such as a compliance payment or a price cap. Some allow cheaper but limited alternatives first, such as out-of-state credits up to a share. The module supports both through `escape_price` and `escape_tiers`.
3. **Every institution reports its implicit price.** The dual of each constraint measures institutional pressure: an implied credit price, an implied capacity price, or an implied subsidy for mandated storage. These are comparable with observed prices and with the network's own mismatch signals.
4. **The base of a requirement is part of the institution.** What counts toward a share, and what the share is measured against, can matter more than the share itself. In the Virginia case, whether data-center load is in the portfolio standard's base changes the 2035 compliance bill by about $2.6 billion a year.
5. **Accreditation must use the right quantity.** A first version accredited storage by power. The optimizer then built power links with almost no energy behind them. Storage is now accredited and mandated by energy. Rules defined on the wrong quantity are gamed by an optimizer, as they can be in practice.
6. **Reliability must be stated as a rule.** With weighted representative days, a peak day carries little weight, and a model relying only on the cost of unserved energy will leave rare peak hours short. Adequacy and deliverability requirements make reliability explicit, as planning standards do in practice.
7. **Everything is switchable.** Each institution can be removed for an ablation, so its effect on the mix, costs and bills can be measured.

## Current module

`techgraph/institutions.py` provides four kinds:

- `EnergyShare`: members' energy must reach a share of demand minus excluded designs. Optional escape tiers and an escape price.
- `CapacityQuantity`: members' capacity must reach a minimum.
- `AccreditedCapacity`: accredited capacity must cover peak demand plus a margin. With `locations`, it covers the peak of a constrained area, as a deliverability or transmission planning requirement.
- `EmissionCap`: recorded emissions must stay under a cap.

They are passed to `dynamic.solve_window(..., institutions=[...])`. Energy quantities are weighted by `Scenario.period_weights` when representative days are declared. With no institutions, the window is unchanged. The existing v4 tests still pass, and `tests/test_institutions.py` covers the new module.

## Not yet represented

- **Intertemporal rules.** Credit banking and multi-year compliance periods would link epochs.
- **Overlapping jurisdictions.** The Virginia case combines state rules with a regional market rule. A general treatment would let each jurisdiction cover a subset of locations and loads.
- **Institutions that change.** Rules respond to their own effects. A rate shock leads to rate reform, and a queue backlog leads to interconnection reform. In the theory's terms, institutions are also subject to service deficits. A natural next step is to let society-layer actors revise institutional parameters when signals cross thresholds.
- **Implicit prices in mixed-integer windows.** Duals are reported only for linear windows. Windows with lumps would need a fixing-and-resolving step.
