# ADR-0004: Intention-based speech model (intentions, then expression), configurable with presets

- **Status:** Accepted
- **Date:** 2026-11-04
- **Related:** ODD §2.5, §7.3, §7.6, §8; ADR-0002, ADR-0005

## Context

Messages are typed (adaptation of Bales' categories) and each type carries a social risk. Three ways of deciding whether and what an agent says were compared:

- **A. One independent decision per message type.** Captures selective silence (posting status updates while withholding disagreement), but participation ("at least one message") rises mechanically with the number of types: moving to the full Bales grid would raise participation with no behavioural change.
- **B. Two stages (decide to speak, then choose a type).** Participation is independent of the typology and comparable to the paper, but the decision to speak ignores what one has to say, and silence on risky content appears as substitution by safe content. The split between "more" and "riskier" would be imposed by the model's structure.
- **C. Intentions, then expression.** Separates what an agent has to say from what it dares to say.

## Decision

Option C as the framework, configurable so that A and (approximately) B are presets.

1. **Intention generation** (replaceable component). For each message type: a source (always present; triggered by an event such as being blocked, receiving a request or making progress; or appearing at an hourly rate) and a lifetime (one consultation, a number of hours, or until resolved). An unexpressed intention stays pending until it is expressed or expires.
2. **Expression decision** (replaceable component, "expression policy"):
   - `independent` (default): each pending intention is expressed or not, independently;
   - `gate_then_choose`: decide first whether to speak, then pick one intention, avoiding risky ones. This approximates option B and is equivalent to it only when intentions are always present.
3. The probability of expressing an intention depends on speak propensity, psychological safety, climate, fear of isolation × social risk of the type, and the agents' courage reaction to the proxy signal (ADR-0005). Functional form: open.
4. **Presets:** `article` (one type, always present, one-consultation lifetime), `independent_types` (option A), `two_stage` (option B), `intentions` (default).
5. **Fixed number of draws per consultation** for every policy, enforced by a generic test (ADR-0002).

## Consequences

- Silence becomes directly measurable as intentions that existed and were not expressed, distinct from having nothing to say. This is close to how organisational silence research describes silence (withholding information or opinions one holds). Candidate reference, to verify before citing: Morrison & Milliken (2000), *Academy of Management Review*.
- Help-request delays follow naturally (age of the intention when expressed).
- The typology no longer inflates participation silently: adding types means adding intention sources with explicit, documented rates.
- The paper's model is recovered with the `article` preset.
- Comparisons are valid only between runs using the same policy and intention sources; both are recorded in the manifest.
- More parameters: presets come first in the user interface; per-type sources and lifetimes are advanced settings.

## Open points

- Functional form and coefficients of the expression probability.
- Rates and lifetimes per type (no direct basis in the paper; sensitivity analysis required).
- Disagreements have no natural cause in the current model: a rate for now; deriving them from an opinion gap with the perceived majority (closer to Noelle-Neumann) requires giving agents an opinion.
- Methodological guardrail (recommended, not yet decided): specify the proxy effect generically (on perceived climate or fear) rather than per message type, and compare several functional forms; otherwise the answer to "riskier or just more?" would be built in.
