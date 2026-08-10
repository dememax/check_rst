.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Outline command manual page — check_rst project

######################
check_rst-outline(1)
######################

******
NAME
******

check_rst-outline - print navigable document structure

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst [GLOBAL-OPTION]... outline [OPTION]... [FILE]...

*************
DESCRIPTION
*************

Print section ranges and structural entries without requiring a linear read.
The structure view is always whole-document and never changes the exit status.
In verified Sphinx mode, ``toctree`` children are traversed unless
``--no-toctree`` is given.

*************
COMPOSITION
*************

Parsed includes are visible control entries.  Entries originating in an
included file are prefixed by that physical source and retain the complete
nested include path.  Include cycles are reported without traversal; their
identity is the resolved source plus clipping options, so disjoint fragments
of one file remain valid.

Verified output is parser-effective, not builder-final.  ``only`` and
``ifconfig`` containers are marked builder-dependent.  Extension-mutated or
configured synthetic source remains visible but is marked inexact rather than
given a misleading editable location.

*********
OPTIONS
*********

``--with-findings``
   Add bold/rubric WARNING lines to the structure view.  Findings are counted
   whether displayed here or not.

``--outline-depth N``
   Display entries through nesting depth ``N``.  Hidden entries remain in
   totals.

``--sections-only``
   Hide every leaf kind regardless of depth.  This composes with
   ``--outline-depth``.

``--git-scope``
   Use Git to select files while still showing whole-document structure.
   Finding lines, if requested, retain changed-line scope.

*************
EXIT STATUS
*************

Structure itself never produces status ``1``.  ERROR findings from the
underlying check pipeline still do; invalid invocation returns ``2``.

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-reports(1)`,
:manpage:`check_rst-workflow(7)`
