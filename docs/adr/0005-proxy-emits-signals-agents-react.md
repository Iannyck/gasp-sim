# ADR-0005: A single replaceable proxy that emits signals; agents react to them

- **Status:** Accepted
- **Date:** 2026-11-03 (single replaceable proxy, absent in control); 2026-11-04 (signals and agent reactions)
- **Related:** ODD §2.2, §7.4, §7.5; ADR-0004, ADR-0006

## Context

In the paper, the virtual pet does not communicate directly with team members: it observes activity metadata and displays one of three states (Napping, Waiting, Celebrating). The paper names, as a limitation, that all agents respond to the proxy in the same way; this project introduces individual differences. Other proxies must be possible as extensions.

## Decision

1. **A single proxy per run, replaceable** through configuration. The GASP pet is the default.
2. **Control condition = no proxy** (`proxy: none`). Outputs then carry no proxy state.
3. **The proxy never receives nor sends messages.** It observes the team channel's activity metadata over a time window, on its own evaluation period.
4. **The proxy declares its own states** and maps them to a **signal** made of named values. Version 1 defines two binary values:
   - `alert` (communication is going badly; acts before speaking, as a prompt): emitted in `WAITING`;
   - `reward` (communication is resuming; acts after speaking, as reinforcement): emitted in `CELEBRATING`;
   - `NAPPING` emits nothing.
   The two-signal abstraction is a construction of this project, derived from the roles the paper gives to the Waiting and Celebrating states.
5. **Reactions belong to the agents** (replaceable `SignalReaction` components that depend on personality):
   - **courage**: raises the probability of expressing an existing intention (on by default);
   - **pretext**: creates a low-risk socio-emotional intention addressed to colleagues (available, off by default);
   - **distraction**: slows current work; zero when no signal is emitted.
6. **Version 1 parameters:** binary signals; the reward reaches every agent who sees the proxy; the effect is limited to the consultation at which the signal is seen (assumption); no habituation.
7. Agents never read the proxy's state names, only the signal.

## Alternatives considered

- **Several simultaneous proxies:** rejected for now. Adding them later would change the perception object and break the extension API (major version).
- **A "null" proxy always in Napping for the control condition:** rejected; outputs would show proxy states where no pet exists, making state-based measures misleading.
- **Effect computed by the proxy and weighted by agent sensitivity** (initial proposal): rejected; it placed agent psychology inside the proxy, contrary to its role.
- **A single "communication health" value:** rejected; it cannot distinguish prompting from reinforcement.

## Consequences

- Replacing the proxy leaves agent reactions untouched, provided the new proxy emits the same kind of signal.
- Personality effects on reactions live with the personality model.
- The two mechanisms (courage, pretext) can be compared, which serves the question "does the proxy make agents say riskier things, or just more things?".
- A perverse effect becomes observable: since the proxy counts messages without knowing their content, low-risk messages can trigger the reward while risky intentions stay unexpressed. To be observed, not imposed.

## Open points

- Magnitude of each reaction; form of the distraction cost.
- Duration of `CELEBRATING`, hysteresis, minimum and maximum state durations.
- Extensions: graded alert (e.g. growing with silence duration), reward targeted at contributors, effects decaying over several hours, habituation.
