.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Main command manual page — check_rst project

##############
check_rst(1)
##############

******
NAME
******

check_rst - check, fix, and query reStructuredText and Sphinx documentation

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst [GLOBAL-OPTION]... COMMAND [COMMAND-OPTION]... [FILE]...
   check_rst --help
   check_rst --version

*************
DESCRIPTION
*************

``check_rst`` is a deterministic front end for reStructuredText.  A command
is required: ``check`` and ``diff`` serve reviewers, ``fix`` and
``list-table`` perform bounded source transformations, and ``outline``,
``context``, and ``refs`` expose verified structure.  ``diff-json`` compares
two prior machine-readable reports and ``hierarchy`` prints the live
adornment order.

The executable natively processes ``.rst`` files.  Sphinx verification is
available for trusted projects.  Markdown is not a native input format; see
:manpage:`check_rst-formats(7)`.

****************
GLOBAL OPTIONS
****************

Global options precede the command, in the same style as Git.

``--config FILE``
   Load ``FILE`` instead of discovering configuration in the working
   directory.

``--no-config``
   Disable configuration discovery and use command-line defaults.

``--sphinx-src DIR``
   Use ``DIR`` as the Sphinx source tree, enabling verified Phase 2 and Phase
   3.  This is never inferred automatically.

``--build-dir DIR``
   Reuse ``DIR`` for Sphinx output.  It requires ``--sphinx-src``; otherwise a
   temporary build directory is removed after the run.

``--version``
   Print the package version.

****************
FILE SELECTION
****************

Explicit files are processed in full.  With no files, Git selects changed and
untracked ``.rst`` files and diagnostics are limited to changed lines where
the command supports findings.  ``--recursive`` treats positional paths as
directories and processes every matching file in full.  ``--git-scope``
instead treats positional files as an allowlist over Git selection.

********
PHASES
********

Phase 0 checks byte hygiene.  Phase 1 checks RST formatting, hierarchy, and
directives.  Phase 2 resolves Sphinx-aware structure, using the live project
when verified and documented heuristics otherwise.  Phase 3 runs a real
Sphinx build only in verified mode.

*************
EXIT STATUS
*************

``0`` means no ERROR was found.  ``1`` means one or more ERRORs; preview
commands also use ``1`` when their output shows that files would change.
``2`` is a command-line usage error.  WARNINGs do not by themselves select
status ``1``.

****************
TRUST BOUNDARY
****************

Verified mode imports the selected project's ``conf.py`` and extensions,
which execute Python code.  Use it only with trusted projects.

**********
EXAMPLES
**********

.. code-block:: console

   $ check_rst check
   $ check_rst --sphinx-src docs check docs/guide.rst
   $ check_rst diff document.rst
   $ check_rst outline document.rst

**********
SEE ALSO
**********

:manpage:`check_rst-check(1)`, :manpage:`check_rst-fix(1)`,
:manpage:`check_rst-diff(1)`, :manpage:`check_rst-outline(1)`,
:manpage:`check_rst-list-table(1)`, :manpage:`check_rst-reports(1)`,
:manpage:`check_rst-config(5)`, :manpage:`check_rst-workflow(7)`
