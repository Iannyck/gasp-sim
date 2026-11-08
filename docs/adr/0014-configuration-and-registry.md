# ADR-0014: Configuration files and registry of extensions

- **Status:** Accepted
- **Date:** 2026-11-08
- **Related:** ADR-0002 (stream modes), ADR-0005 (single replaceable proxy), ADR-0007 and
  ADR-0010 (durations and ticks), ADR-0008 (pydantic, entry points, JSON Schema),
  dev-conventions §5, §9.5 and §9.6

## Context

Researchers must be able to run the simulator without writing code: every input goes
through a versioned YAML file, saved with the results (ODD §6). Developers must be able to
add components (a speaking rule, a proxy, a personality mapping…) without modifying the
simulator, and those components must be selectable from the same files. ADR-0008 chose
pydantic for validation, entry points for discovery, and the JSON Schema of the
configuration for the forms of the future user interface. This ADR fixes how these pieces
fit together. It is demonstrated on the toy chatter example; the GASP schema comes with the
GASP model (step 6).

## Decision

1. **A component is written as its name under `type`, with its parameters at the same
   level:**

   ```yaml
   speaking_rule:
     type: feedback
     base_probability: 0.3
   ```

   The key `type` is reserved; no component parameter may use it.

2. **Strict validation, with every problem listed at once in plain words.**
   - An unknown setting is an error, with a suggestion when a known name is close
     (`n_agnets: unknown setting; did you mean 'n_agents'?`): a typo must never leave a
     parameter at its default value without anyone noticing.
   - No silent conversion: the text `"0.5"` is not a number, `yes` is not a number of
     agents. A whole number is accepted where a decimal number is expected.
   - Each problem gives its location and the rule broken, for example
     `speaking_rule → base_probability: must be at most 1 (got 1.5)`.
   - Infinite and not-a-number values are refused.
   - Reading the YAML is strict too: a setting written twice in the same group is an error
     (YAML libraries usually keep the last one silently), setting names must be text, and
     dates stay text. Lists are read as tuples, so validated configurations contain no
     mutable lists.
   - Durations are written in hours. A field marked `ExactHours` (such as a rhythm period,
     ADR-0007) must be a whole number of ticks; a field marked `Hours` is rounded to the
     nearest tick and the rounding is reported as a **warning** (ADR-0010), collected with
     the errors. A positive duration shorter than half a tick is an error. Durations are
     checked against the time grid of the file, including default values, and are still
     checked when other settings are invalid.

3. **A registry of extension points, components and presets** (`gasp_sim.registry`).
   - An *extension point* is a `typing.Protocol` (runtime-checkable, methods only). A
     *component* is a name, a pydantic model of its parameters (`ComponentParameters`) and
     a factory. A *preset* is a named set of configuration values.
   - The registry is an ordinary object, not a global: each model builds its own.
   - It is filled from three sources, always explicitly: built-in components; installed
     plugins advertised as entry points (`Registry.load_entry_points(group)`); local
     plugins listed under `plugins:` in a configuration file (a module name, or a Python
     file relative to the configuration file). A plugin is a module with a function
     `register(registry)`.
   - **Registering a name twice is an error**, whatever the sources; the message names
     both. A plugin cannot silently replace a component.
   - A plugin registers on a copy of the registry; if it fails, nothing it did is kept.
   - A factory that is a class is checked against the protocol at registration; any other
     factory is checked when the component is created. Python only checks that the
     methods exist; static typing checks their signatures.
   - The plugins of a file are loaded into a copy of the registry, returned with the
     configuration; the registry passed in is not modified.

4. **The result is a resolved, frozen configuration.** Every default is filled in, the
   object cannot be modified, and `LoadedConfig.resolved()` (or `to_yaml()`) gives every
   setting as plain data. Loading it again gives an equal configuration; it is what the
   manifest of a run will record (step 5).

5. **Presets: the mechanism now, the content later.** A file selects a preset with
   `preset: <name>`; its own values are merged over those of the preset. Groups of
   settings merge setting by setting; a component block whose `type` differs from the
   preset's replaces it entirely; lists and single values are replaced. The GASP presets
   (`article`, `independent_types`, `two_stage`, `intentions`) will be written with the
   GASP model.

6. **JSON Schema export.** `config_json_schema(schema, registry)` describes every setting
   with its type, bounds, default and description, including the parameters of every
   registered component (extensions included), as a choice selected by `type`. It will be
   used to generate the forms of the user interface.

7. **Settings common to every run** (`RunSettings`): `seed`, `days`, `stream_mode`
   (`named` by default, `single` for verification only, ADR-0002), `time` (tick length in
   minutes and working-day length in hours), `preset` and `plugins`. A model describes its
   configuration by subclassing it.

8. **Libraries.** pydantic for validation (ADR-0008); PyYAML, with its safe loader, for
   reading files.

9. **Layers.** `gasp_sim.registry` and `gasp_sim.config` may use the engine core, never
   the reverse; the core never imports pydantic or PyYAML. These rules are checked by
   import-linter. The names needed by developers are exported by `gasp_sim.api`.

## Implementation notes

- A schema declares a component field with
  `Annotated[ComponentParameters, Slot(EXTENSION_POINT, default="name")]`. Before
  validation, the schema is *bound* to a registry: each slot becomes a pydantic
  discriminated union of the registered components, selected by `type`. A validated
  configuration is an instance of the schema it was declared with.
- Bound schemas are cached by schema and set of components, so that two loads with the
  same components give configurations of the same classes, which compare equal.
- Slots may be fields of the schema or of nested sections, not items of lists (not needed
  yet).

## Facts checked (2026-11-08)

- PyYAML 6.0.3 is the latest release listed. Source:
  https://simple-repository.app.cern.ch/project/pyyaml
- pydantic 2.14 was released on 2026-10-08 and officially supports Python 3.15. Source:
  https://pydantic.dev/articles/pydantic-v2-14-release
- ruamel.yaml 0.18.15 is the latest release listed. Source:
  https://simple-repository.app.cern.ch/project/ruamel-yaml
- The implementation was tested with pydantic 2.13.5 and PyYAML 6.0.3; the lower bounds of
  the dependencies are set to the tested versions.

## Alternatives considered

- **Parameters in a `params:` sub-block** (`type: feedback` then `params: {…}`): more
  regular for programs, heavier to read and write for researchers.
- **Lenient validation** (pydantic's default: unknown settings ignored, `"0.5"` converted
  to a number): convenient, but typos and wrong types pass unnoticed.
- **ruamel.yaml** instead of PyYAML: keeps comments and supports YAML 1.2 (where `no` is
  text, not false), but it is a larger dependency, and comment preservation is not needed
  since files are only read. PyYAML's YAML 1.1 quirks are covered by strict validation and
  targeted hints (`yes`/`no`, exponents without a decimal point such as `1e-3`).
- **A global registry** filled at import time: shorter, but hidden state makes tests and
  the plugins of one file leak into the next run.
- **Discovery by entry points only:** requires packaging even for a quick experiment;
  local plugins avoid this.
- **Letting a later registration replace an earlier one:** convenient for overriding a
  built-in component, but a replacement would be invisible in the results; a new name is
  required instead.
- **TOML or JSON files:** TOML is less readable for nested component blocks; JSON allows
  no comments. YAML was chosen in dev-conventions §5.

## Consequences

- Researchers get every problem of a file at once, located and explained, before anything
  runs.
- Developers add components and presets from their own package or from a local file, with
  the same validation, error messages and JSON Schema as built-in components.
- A local plugin is ordinary Python code run by the simulator: loading it is as trusted as
  running a script, which is why plugins are only loaded from what the user lists.
- Error messages are in English, like the rest of the project.
- The toy chatter example now has a replaceable speaking rule, three example files
  (default, preset, plugin) and runs from a file; its reference run is unchanged (400
  consultations, 272 messages, mean participation 0.680 with seed 42).

## Open points

- `proxy: none` (control condition, dev-conventions §9.6): a short form for "no
  component" will be designed with the GASP proxy.
- Whether the GASP model declares its parameter models with pydantic (`gasp_sim.model`
  depending on pydantic) or leaves them to `gasp_sim.config`: to decide in step 6.
- Name of the entry-point group of GASP plugins (`gasp_sim.plugins` is the natural
  candidate).
- Lists of components (for example several measures): not supported until needed.

## Revisit when

- the user interface shows that the JSON Schema needs more information (labels, units,
  groups of advanced settings); or
- YAML 1.1 quirks cause errors that the hints do not explain.
