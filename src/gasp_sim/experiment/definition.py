"""Definition of a model for the experiment layer (ADR-0016).

To run a model from a configuration file, the experiment layer needs to know, for that
model:

- its configuration schema (a subclass of :class:`~gasp_sim.config.schema.RunSettings`);
- how to build its registry of components, and which entry-point group advertises its
  installed plugins;
- how to build a simulation from a loaded configuration;
- the observation tables and summaries to record (ADR-0015);
- which values of the run summaries to show when a run ends (the *headline*);
- further checks of a loaded configuration that only the model can make, reported as
  warnings.

A :class:`ModelDefinition` gathers these. The model itself does not import the recording
layer, so its definition lives outside it, in the experiment layer.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from gasp_sim.config.loader import ConfigIssue, LoadedConfig, load_config
from gasp_sim.config.schema import RunSettings
from gasp_sim.core.simulation import Simulation
from gasp_sim.recording.tables import ObservationTable, SummaryTable
from gasp_sim.registry import Registry

__all__ = ["ModelDefinition"]


@dataclass(frozen=True, slots=True)
class ModelDefinition[S: RunSettings]:
    """Everything needed to load, build, run and record a model.

    Parameters
    ----------
    name : str
        Name of the model, shown to users.
    schema : type
        Configuration schema of the model.
    registry : callable
        Called without arguments; returns a new registry holding the built-in components
        and presets of the model.
    build : callable
        Called with a loaded configuration; returns the simulation of the model, which has
        not run yet.
    plugin_group : str or None
        Entry-point group in which installed packages advertise plugins of the model; they
        are loaded automatically. ``None`` if the model has none.
    tables : tuple of ObservationTable
        Observation tables to record (level ``full``).
    summaries : tuple of SummaryTable
        Summary tables to record (both levels).
    headline : tuple of (str, str)
        Values shown at the end of a run, as pairs (summary table, column). Each table must
        be a summary of the whole run that gives one row.
    checks : callable or None
        Called with a loaded configuration; returns further warnings, for example on
        settings that are valid one by one but make little sense together.

    Raises
    ------
    ValueError
        If a headline value does not name a column of a summary of the whole run.
    """

    name: str
    schema: type[S]
    registry: Callable[[], Registry]
    build: Callable[[LoadedConfig[S]], Simulation]
    plugin_group: str | None = None
    tables: tuple[ObservationTable, ...] = ()
    summaries: tuple[SummaryTable, ...] = ()
    headline: tuple[tuple[str, str], ...] = ()
    checks: Callable[[LoadedConfig[S]], Sequence[ConfigIssue]] | None = None

    def __post_init__(self) -> None:
        """Check that every headline value names a column of a run summary."""
        columns = {
            summary.name: {column.name for column in summary.columns}
            for summary in self.summaries
            if summary.per == "run"
        }
        for table, column in self.headline:
            if column not in columns.get(table, set()):
                raise ValueError(
                    f"Headline value {table}.{column} of model {self.name!r} is not a column "
                    "of a summary of the whole run."
                )

    def new_registry(self) -> Registry:
        """Return a registry with the built-in components and the installed plugins.

        Raises
        ------
        gasp_sim.registry.PluginError
            If an installed plugin cannot be loaded.
        """
        registry = self.registry()
        if self.plugin_group is not None:
            registry.load_entry_points(self.plugin_group)
        return registry

    def load(self, path: str | Path) -> LoadedConfig[S]:
        """Load and validate a configuration file of the model.

        Raises
        ------
        gasp_sim.config.loader.ConfigError
            If the file cannot be read or the configuration is invalid.
        gasp_sim.registry.PluginError
            If an installed plugin cannot be loaded.
        """
        loaded = load_config(path, self.schema, self.new_registry())
        if self.checks is None:
            return loaded
        found = tuple(self.checks(loaded))
        return dataclasses.replace(loaded, warnings=(*loaded.warnings, *found))
