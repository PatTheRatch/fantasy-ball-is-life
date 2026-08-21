"""Provider adapters.

Charter §7: provider-specific objects (ESPN, and later Yahoo/Sleeper) live at
the boundary and never become the canonical fantasy domain model. Everything
in this package talks to a provider; the ``domain`` package imports nothing
from here (enforced by ``tests/test_architecture.py``).
"""
