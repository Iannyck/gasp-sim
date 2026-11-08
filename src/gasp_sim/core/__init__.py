"""Generic simulation engine: clock, event queue, random streams and phases.

This package knows nothing about GASP and depends only on NumPy (dev-conventions §9.3).

Modules
-------
rng
    Named random streams derived from a single run seed.
clock
    Simulation clock and conversion of durations to ticks.
events
    Event queue for future events and synchronous notification bus.
deferred
    Append-only logs whose entries become visible one tick after they are written.
context
    What a phase receives during one tick.
phases
    Interface of the ordered processes executed at every tick.
simulation
    The simulation loop.
"""
