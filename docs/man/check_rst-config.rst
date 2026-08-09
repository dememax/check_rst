.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Configuration file manual page — check_rst project

#####################
check_rst-config(5)
#####################

******
NAME
******

check_rst-config - repository facts for check_rst

*************
DESCRIPTION
*************

Configuration records project identity, not personal policy.  ``check_rst``
supports a dedicated ``.check_rst.toml`` whose whole file is the settings
table, or a ``[tool.check_rst]`` table in ``pyproject.toml``.  When both exist
in the working directory, the dedicated file wins.  Discovery never walks to
parent directories.

******
KEYS
******

``sphinx-src = "DIR"``
   Sphinx source directory, resolved relative to the configuration file.

``build-dir = "DIR"``
   Reusable Sphinx build directory, resolved relative to the configuration
   file.  It is meaningful only with a Sphinx source.

Values must be strings and unknown keys are errors.  Command-line global
options override loaded values.  A non-quiet run reports the source and which
values were applied or inactive.

********************
EXPLICIT SELECTION
********************

``--config FILE`` selects a configuration from any working directory and uses
its containing directory as the project root.  ``--no-config`` disables both
file forms.  Both options must precede the command.

**********
SECURITY
**********

A configured Sphinx source enables verified mode, which imports ``conf.py``
and extensions.  Use configuration from trusted projects only.

*********
EXAMPLE
*********

.. code-block:: toml

   sphinx-src = "docs"
   build-dir = "/tmp/example-sphinx-build"

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-check(1)`
