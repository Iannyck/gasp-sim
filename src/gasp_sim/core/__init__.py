"""Generic simulation engine: clock, event queue, random streams and phases.

This package knows nothing about GASP and depends only on NumPy (dev-conventions §9.3).

Modules
-------
rng
    Named random streams derived from a single run seed.
clock
    Simulation clock and conversion of durations to ticks.
"""
