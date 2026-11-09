# ADR-0015: Recording of outputs (tables, summaries, manifest)

- **Status:** Accepted
- **Date:** 2026-11-08
- **Related:** ADR-0002 (seeds and streams), ADR-0007 (time windows), ADR-0008 (CSV and JSON,
  `full` and `summary` levels), ADR-0011 (notification bus), ADR-0014 (resolved
  configuration), dev-conventions §5 and §9.7, ODD §8 and appendix A (pitfall 14)

## Context

Every result must come with what is needed to know exactly what ran: the complete
configuration, the seed, the version of the simulator, the date, the stream mode, the
preset and the definition of the measures (dev-conventions §5). Outputs are CSV and JSON
only, at two levels: `full` (every table) and `summary` (aggregates per run and per time
window) (ADR-0008). With 5-minute ticks, recording the state at every tick would produce
mostly empty rows (ODD, appendix A, pitfall 14); the ODD recommended recording per
consultation and per event. The model must not depend on the recording layer (layer
rules). This ADR fixes how outputs are produced, computed and written. It is demonstrated
on the toy chatter example.

## Decision

1. **The model publishes observations; a recorder listens.** An observation is a frozen
   dataclass published on the notification bus (`context.publish(...)`), for example "an
   agent consulted the channel". It has an integer `tick` field; every other field has a
   `description`, and optionally a `unit`, in its metadata (`dataclasses.field(metadata=...)`,
   standard library only). Outside the model, an `ObservationTable` turns an observation type
   into a table: one row per observation, one column per field. Recording is therefore per
   event, not per tick, and the model does not import the recording layer.
2. **Summaries are computed during the run by aggregators declared with the model.** A
   `SummaryTable` names a row type (a frozen dataclass described like observations) and an
   aggregator factory. An aggregator receives every recorded observation and, at the end of
   each period (each time window, or the whole run), returns the rows of that period. The
   same aggregators run at both levels; at the `full` level the observation tables are
   written as well, so that summaries can be checked against them. This is the `Metric`
   extension point of dev-conventions §9.5 in its online form; indicators computed
   afterwards from full tables belong to the `analysis` layer (later).
3. **One directory per run**, never overwritten:

   ```
   <output>/<run-id>/
     manifest.json        # what ran, how, and what every column means
     config.yaml          # resolved configuration (ADR-0014), loadable as it is
     tables/<name>.csv    # one row per observation (level "full" only)
     summary/<name>.csv   # rows of the aggregators (both levels)
   ```

   Every row starts with `run_id`, so that the tables of many runs can be concatenated as
   they are (long format). The default run identifier is the local date and time followed
   by the seed (`20261108-143205-seed42`); the caller may choose another one (batches will).
   An existing directory is an error.
4. **CSV for tables, JSON for the manifest.** No JSON export of tables.
5. **Writing as the run goes.** Rows are kept in memory and appended to the files at the
   end of every simulated working day. The manifest is written at the start with
   `status: running` and completed at the end with `completed`, or `failed` together with
   the type and message of the error and the tick at which it happened. The error is never
   swallowed. After a failure, the rows of complete days and complete windows are kept; the
   summaries of the window in progress and of the whole run are not written, since they
   would describe an incomplete period. A run interrupted abruptly keeps `running`. Only a
   `completed` run is a result.
6. **Manifest:** layout version; run identifier; status; start and end times (UTC);
   duration; ticks completed; error; versions of gasp-sim, Python, NumPy, pydantic and
   PyYAML, and the platform; seed, stream mode and bit generator; tick and day lengths and
   number of days; configuration file, file name of its source, preset, loaded plugins and
   loading warnings; recording level, window length and CSV conventions; for every table and
   summary its file, description, number of rows and columns (name, type, unit, whether it
   may be empty, description). **No Git commit identifier for now.**
7. **Configuration:** a `recording:` block of the common run settings, with `level` (`full`
   by default) and `window_hours` (8 by default; a duration in hours, rounded to the nearest
   tick with a warning, ADR-0010). The output directory is not part of the configuration: it
   is given when running, so that a configuration describes an experiment wherever it runs.
8. **Format of values:** comma separator, decimal point, UTF-8 without byte-order mark,
   `\n` line endings on every system, fields quoted only when needed (RFC 4180). Decimal
   numbers are written without loss (the shortest text that gives back exactly the same
   value), booleans as `true` and `false`, empty values as empty fields. Values are checked
   against their column: no boolean for a number, no text for a number, no infinite or
   not-a-number value, and no carriage return or NUL character in text, which CSV readers
   (and Python versions) do not all read back the same way.
9. **Time columns:** the recorder adds `tick`, `day` (from 0) and `minutes` (whole working
   minutes since the start of the day) to every observation row. Window rows carry
   `window`, `start_tick`, `end_tick` (exclusive), `start_day` and `complete` (false for a
   last window cut short by the end of the run). Numbering starts at 0 everywhere, as in
   the engine, and is stated in the column descriptions.
10. **Determinism:** the same configuration, seed and run identifier give tables,
    summaries and configuration files identical to the byte; only the dates, duration and
    software versions of the manifest differ. This is tested.

## Implementation notes

- `gasp_sim.recording.tables`: `ObservationTable`, `SummaryTable`, `Aggregator` (protocol
  with `observe(observation)` and `rows(period)`), `Period`, `Column`, `format_value`.
- `gasp_sim.recording.files`: CSV files written by batches; manifest replaced atomically
  (temporary file, then rename), so that it is never half-written.
- `gasp_sim.recording.recorder`: `RunRecorder`, used as a context manager around the run.
  It subscribes to the observation types and to `StepCompleted`; windows are continuous
  across days (ADR-0007).
- An observation published with a tick other than the current one is an error: it would
  otherwise be recorded at the wrong time.
- The toy chatter example publishes `Decision` and `MessageSent`, declares the tables
  `consultations` and `messages`, and the summaries `windows` and `run`; `run.py --output DIR`
  records a run. Its recorded summaries reproduce the reference run (400 consultations,
  272 messages, mean participation 0.68 with seed 42).

## Alternatives considered

- **The model writes into a recorder it receives:** the model would depend on the
  recording layer, or the engine would need an output interface.
- **Snapshots of the state at regular intervals:** either very large files (fine interval)
  or missed events (coarse interval), and the recorder would need to know the model's
  internals.
- **Generic aggregates computed by the recorder** (for example rows per window): simple
  but nearly useless; only the model knows what "participation" means.
- **One file per run holding every table, or wide tables** (one column per agent or per
  tick): harder to open without programming, and impossible to concatenate when the number
  of agents varies.
- **JSON Lines for tables:** no current use; CSV is readable everywhere.
- **Writing everything at the end of the run:** memory grows with simulated time and an
  abrupt stop loses everything. **Writing every row immediately:** much slower for large
  batches.
- **Rounded numbers** (for example 6 significant digits): prettier, but files would no
  longer give back the values of the model.
- **Time in hours:** most values would be long decimals (`0.16666666666666666`); whole
  minutes are exact.
- **Numbering from 1:** more natural for some readers, but every value would differ from
  the engine, with a risk of shifts between code and files.

## Consequences

- New measures are added by writing a dataclass and, for summaries, an aggregator; the
  model stays independent of how and where outputs are written.
- The same observations can later feed other listeners (real-time visualisation, a second
  recorder) without changing the model.
- An indicator that was not planned cannot be computed afterwards from a `summary` run
  (already stated in ADR-0008).
- With French regional settings, Excel does not open these files correctly by
  double-click; they must be imported (Data, From text/CSV) with comma and point.

## Open points

- Git commit identifier of the code in the manifest: declined for now; to reconsider at
  the first release, possibly through version numbers derived from Git (hatch-vcs).
- Fingerprints of local plugin files and versions of plugin packages in the manifest.
- A separator option for spreadsheets with French regional settings, if users need it.
- Layout of batch outputs (step 7): one directory per experiment, a table of runs with
  their seeds and conditions, and concatenated tables.
- Whether the run summary should repeat the seed and the condition (useful once runs are
  concatenated), or leave them to the table of runs of step 7.

## Revisit when

- batch experiments show that writing at the end of each day is too slow or too
  frequent; or
- users need tables in another format.
