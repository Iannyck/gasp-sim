"""Configuration: validation schemas, YAML loading with readable errors, presets.

- :mod:`gasp_sim.config.base`: strict base classes and duration fields;
- :mod:`gasp_sim.config.schema`: settings common to every run and component slots;
- :mod:`gasp_sim.config.loader`: reading, validating and resolving configuration files.

See ADR-0014. Developers use these names through :mod:`gasp_sim.api`.
"""
