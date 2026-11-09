"""Recording of simulation outputs: tables, CSV files and run manifest (ADR-0015).

- :mod:`gasp_sim.recording.tables`: declarations of observation and summary tables,
  aggregators, and the CSV format of values;
- :mod:`gasp_sim.recording.files`: CSV and JSON writers;
- :mod:`gasp_sim.recording.recorder`: :class:`~gasp_sim.recording.recorder.RunRecorder`,
  which records one run into its own directory.

Developers use these names through :mod:`gasp_sim.api`.
"""
