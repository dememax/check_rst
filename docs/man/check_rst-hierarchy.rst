.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Hierarchy command manual page — check_rst project

########################
check_rst-hierarchy(1)
########################

******
NAME
******

check_rst-hierarchy - print the live adornment-character order

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst hierarchy

*************
DESCRIPTION
*************

Print the complete hierarchy used by adornment checks and fixes for the
installed Docutils runtime.  Preferred project characters are marked.  The
command is self-contained: it does not select files, load project
configuration, or accept Sphinx options.

The output is intentionally generated at runtime instead of copied into help
or documentation, because Docutils owns part of the valid character order.

*************
EXIT STATUS
*************

Return ``0`` after printing the hierarchy and ``1`` if an incompatible
argument (a global project-identity option, since the command is
self-contained) is rejected.  ``2`` is reserved for an argparse-level syntax
error (see :manpage:`check_rst(1)`, EXIT STATUS).

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-fix(1)`,
:manpage:`check_rst-rules(7)`
