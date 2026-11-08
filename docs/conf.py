"""Sphinx configuration for the gasp-sim documentation."""

from importlib.metadata import version as _package_version

project = "gasp-sim"
author = "gasp-sim contributors"
copyright = "2026, gasp-sim contributors"
release = _package_version("gasp-sim")
version = release

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "numpydoc",
]

# Pages are written in Markdown (MyST); reStructuredText is also accepted because
# autosummary generates .rst files internally.
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
exclude_patterns = ["_build"]

myst_heading_anchors = 3

html_theme = "alabaster"
html_title = f"gasp-sim {release}"
