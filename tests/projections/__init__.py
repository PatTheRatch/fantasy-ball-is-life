"""D-series (draft port) test package.

Marked as a package because ``tests/`` itself is one — ``tests/__init__.py``
exists, so pytest's default prepend import mode resolves test modules as
``tests.<subpackage>.<module>``. Without this file the modules under here are
imported under a different name than their siblings elsewhere in ``tests/``,
which is how two files can both define a helper and only one win.

Empty otherwise.
"""
