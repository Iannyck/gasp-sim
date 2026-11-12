# ADR-0016: Running a model (model definitions, single runs, command line, run length)

- **Status:** Accepted
- **Date:** 2026-11-11
- **Amends:** ADR-0014 (run length, records of loaded plugins), ADR-0015 (manifest
  layout, version 2)
- **Related:** ADR-0008 (Typer, entry points), ADR-0013 (`run_days`), ADR-0014 (registry,
  plugins), ADR-0015 (recording), dev-conventions §9.3, §9.6 and §9.8, ODD §2.7 and §9

## Context

Until now, a run was assembled by hand in a script: load a file, build the model, attach a
recorder, run for a number of days (the toy chatter example does this in `run.py`). The
GASP model needs the same assembly, and so will batches of runs (step 7) and the user
interface (step 8). Researchers must be able to run it without writing code.

Two further needs came up while preparing the GASP model (step 6):

- the `article` preset keeps the length of the runs of the article, 100 consultation
  cycles of 30 minutes, that is **50 working hours**, which is not a whole number of
  8-hour days;
- installed extension packages must be discovered automatically, and the manifest must
  say which package, in which version, provided each plugin.

## Decision

1. **A model is described to the experiment layer by a `ModelDefinition`**: its name, its
   configuration schema, a function that builds its registry, the entry-point group of its
   installed plugins, a function that builds its simulation from a loaded configuration,
   its observation tables and summaries, and the *headline* values shown at the end of a
   run (columns of summaries of the whole run).
   - Definitions live in the **experiment layer**, the only layer allowed to depend on
     both the model and the recording layer. The model itself still does not import the
     recording layer (ADR-0015); the tables and aggregators of the GASP model will live in
     `gasp_sim.experiment` (step 6.1b).
2. **`run_single(definition, loaded, output, run_id=None)`** builds, runs and records one
   run, for the length given in the configuration, and returns the run identifier, its
   directory and the headline values. A failure during the run is raised as
   `RunFailedError`, which gives the directory of the run (recorded as `failed`, ADR-0015)
   and keeps the original error as its cause. Problems found before the run starts (invalid
   run identifier, existing directory) are raised as they are.
3. **Command line** (Typer, ADR-0008):

   ```
   gasp-sim validate CONFIG [--resolved]
   gasp-sim run CONFIG [--output DIR] [--run-id ID]
   ```

   - `validate` reports every error and warning of a file; `--resolved` prints every
     setting, defaults included.
   - `run` records the run in a new directory inside `DIR`, **`results` by default**, so
     that a forgotten option never loses a run; it prints the directory and the headline
     values.
   - Exit status: `0` on success; `1` if the configuration is invalid or the run fails;
     `2` if the command is mistyped.
   - The commands only read their arguments and print results; the work is done by the
     experiment layer, which batches and the user interface will reuse.
   - Only the GASP model runs through `gasp-sim`; the toy chatter example keeps its script.
     Until the GASP model is available (step 6.1b), `validate` and `run` report that it is
     not available yet (exit status 1).
4. **Run length in days or in hours.** The common settings accept either `days` (a whole
   number of working days) or `hours` (working hours, a whole number of ticks: a rounded
   length would silently change the number of consultations); exactly one of the two must
   be given. A run given in hours may end in the middle of a working day.
   `RunSettings.run_ticks()` gives the length in ticks. The rule is checked with the other
   errors of a file, even when other settings are invalid.
5. **Installed plugins are loaded automatically** from the entry-point group of the model
   (`ModelDefinition.plugin_group`). They can only add components (registering a name twice
   is an error, ADR-0014), and a component changes nothing until a file selects it. A
   switch to disable them is left to step 8 (command line and user interface).
6. **Every loaded plugin is recorded** (`PluginRecord`) with how it was named, its kind
   (`entry_point`, `module` or `file`), and the name and version of the installed package
   that provides it, when there is one: the package of an entry point, or the single
   installed package that provides the top-level package of a module. Plugin files have
   none.
7. **Manifest version 2** (ADR-0015): the `time` block gives `days` or `hours` (the other
   empty) and the number of `ticks` of the run; `configuration.plugins` lists the records
   of decision 6 instead of plain names.
8. **Optional durations** (`Hours | None`, `ExactHours | None`) are checked against the
   time grid like other durations, when they are given.

## Implementation notes

- `gasp_sim.experiment.definition`: `ModelDefinition` (`new_registry()`, `load(path)`).
- `gasp_sim.experiment.single`: `run_single`, `RunResult`, `RunFailedError`.
- `gasp_sim.cli.main`: `make_app(model)` builds the application for a function returning a
  model definition; the model is obtained only when a command needs it, so that `--help`
  and `--version` always work. Tests use the toy chatter model.
- `RunRecorder.run_rows`: rows of the summaries of the whole run, once it is completed
  (used for the headline values).
- `gasp_sim.config.schema.run_length_problem` holds the length rule, used both by the
  schema and by the loader for invalid files.
- Looking up the package that provides a plugin module reads the metadata of every
  installed package (about 0.1 to 0.4 s); it is done only when a module plugin is loaded,
  and not cached, so that a package installed during a long session is still found.

## Alternatives considered

- **A script per model** (as for the toy chatter example): would be replaced by the
  command line later; module paths copied into notes outlive it.
- **The command line containing the logic**: batches and the user interface would have to
  duplicate it.
- **GASP tables in a new layer** (`gasp_sim.outputs`) or **in the model** (allowing it to
  import the declarations of the recording layer): a clearer name for the first, everything
  in one place for the second, but one more layer and import rule, or a return on a
  decision of ADR-0015.
- **Run length in consultation cycles** (`cycles: 100`): meaningless once agents have
  different rhythms. **Keeping 100 consultations rather than 50 hours** when the
  consultation period changes: the inertia of the climate is in hours, so the length of
  the run would change the results along with the rhythm.
- **Seven days, measuring only the first 100 consultations**, or **six days (96
  consultations)**: a separate measurement window, or a departure from the article to
  justify at every comparison.
- **Loading installed plugins only when a file lists them**: explicit, but `plugins:`
  already accepts installed modules, and automatic discovery is what lets an installed
  extension appear in the user interface.
- **Without `--output`, recording nothing**: safer for the disk, but a run would be lost.

## Consequences

- Researchers run a model with one command, from a file, and every run is recorded.
- Batches and the user interface will reuse `run_single` and `ModelDefinition`.
- The `article` preset can keep the 50 working hours of the article; its length does not
  change if a researcher changes the length of the working day.
- `RunSettings.days` may now be `None`; models and scripts use `run_ticks()`.
- `Registry.plugins` now returns `PluginRecord` objects (pre-1.0 change of the public
  API).
- Manifests of version 1 (toy runs of step 5) and version 2 differ in the `time` block and
  in the list of plugins.

## Open points

- Switch to disable installed plugins: step 8.
- Plugins cannot yet add their own observation tables or summaries to a model definition.
- Fingerprints of local plugin files in the manifest (ADR-0015).

## Revisit when

- batches (step 7) need more from a single run than its directory and headline values; or
- users need another default output directory.
