.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Diff command manual page — check_rst project

###################
check_rst-diff(1)
###################

******
NAME
******

check_rst-diff - preview check_rst fix output as a unified diff

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst [GLOBAL-OPTION]... diff [OPTION]... [FILE]...

*************
DESCRIPTION
*************

Compute the same candidate source as ``check_rst fix`` without writing it,
then print a unified diff.  Fix options such as ``--fast`` and the opt-in
parser-verified text policies have the same meaning as for ``fix``.

``--max-output-lines`` is intentionally unavailable: a truncated patch could
look complete or applicable.  Narrow the file scope with explicit files or
``--recursive --exclude PATTERN`` instead.

*************
EXIT STATUS
*************

Return ``0`` when no change is needed, ``1`` when a diff is printed, an
ERROR prevents the preview, or an incompatible option combination is
rejected, and ``2`` only for an argparse-level syntax error (see
:manpage:`check_rst(1)`, EXIT STATUS).  Status ``1`` therefore means
“attention required,” not necessarily “execution failed.”

**********
EXAMPLES
**********

.. code-block:: console

   $ check_rst diff document.rst
   $ check_rst diff --fast document.rst

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-fix(1)`,
:manpage:`check_rst-workflow(7)`
