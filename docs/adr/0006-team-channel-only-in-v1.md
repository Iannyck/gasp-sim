# ADR-0006: Team channel only in version 1; direct messages planned for version 2

- **Status:** Accepted
- **Date:** 2026-11-04
- **Related:** ODD §2.4, §2.6, §4, §7.6, §7.8, §10; ADR-0005

## Context

In real remote teams, members write both in a shared team channel and in direct messages. Modelling both raises questions with no basis in the paper: how an agent chooses the channel, whom it writes to, whether the proxy sees direct messages, and whether they count in the climate.

## Decision

1. **Version 1 models the team channel only.** Every message is visible to all members.
2. **The data model is ready for version 2:** `Message` has a `channel` field (only `TEAM` in version 1) and an optional `recipient` field (empty in version 1); the `messages` output table has a `channel` column.
3. **The climate and the proxy's observation are defined explicitly on the team channel**, so that adding direct messages later does not change their meaning.
4. No extension point for recipient selection yet: adding an extension point later is non-breaking, while creating one too early would freeze an interface not yet designed.

## Rationale

- The spiral of silence concerns public expression: the team channel captures the core phenomenon.
- Direct comparison with the paper, which models a single channel.
- Avoids three unfounded assumptions at this stage.
- Validates the base model before enriching it; if direct messages change results in version 2, the difference can be attributed to them.

## Consequences

- **Limitation to state in the ODD and in any publication based on version 1:** an intention not expressed in the team channel counts as silence, whereas a real member might have written privately. Results concern **public** silence, not silence in general.

## Open points for version 2

- Channel choice driven by risk (fewer witnesses, lower social risk; social risk becomes a function of type and channel).
- Recipient selection (e.g. the most competent colleague), as a new extension point.
- Whether the proxy observes direct messages (`team_only` or `all_channels`).
- Whether received direct messages contribute to an agent's perceived climate.
