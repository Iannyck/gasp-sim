"""Shared pytest configuration.

Hypothesis profiles (dev-conventions §4, ADR-0009):

- ``ci``: deterministic, so that continuous integration runs the same examples every time;
- ``dev`` (default): exploratory, for local development.

Select a profile with the ``HYPOTHESIS_PROFILE`` environment variable.
"""

import os

from hypothesis import settings

settings.register_profile("ci", derandomize=True, database=None, deadline=None, print_blob=True)
settings.register_profile("dev", max_examples=100)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
