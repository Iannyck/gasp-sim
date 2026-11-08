"""The public API exposes exactly the names it declares."""

import gasp_sim.api as api


def test_every_public_name_is_importable() -> None:
    for name in api.__all__:
        assert hasattr(api, name), f"gasp_sim.api.{name} is declared but missing"


def test_public_names_are_sorted_and_unique() -> None:
    assert api.__all__ == sorted(set(api.__all__))
