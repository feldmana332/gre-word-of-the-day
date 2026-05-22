"""Pytest configuration shared across all test files.

This file gets imported automatically by pytest before any tests run.
Anything you put at module level here is available to every test.
"""

import sys
from pathlib import Path

# Make the project root importable so tests can do `from word_of_the_day import ...`
# without us having to install the project as a package. This is the simplest
# pattern for small repos. For larger projects you'd add a pyproject.toml and
# `pip install -e .` instead.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
