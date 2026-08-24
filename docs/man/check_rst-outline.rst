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

Print complete physical section ranges and structural entries without
requiring a linear read.  A section range starts at its overline when present;
the title line remains a separate anchor.  The structure view is always
whole-document and never changes the exit status.  In verified Sphinx mode,
``toctree`` children are traversed unless ``--no-toctree`` is given.  Use this
command when the target structure is unknown; use ``check_rst context`` when
one exact entry is already known.

Every run prints a ``levels:`` legend: each depth with its adornment
character and section count, the document's total section count, and the
first unused character in check_rst's canonical adornment order — or
``no free section char`` when every valid character is already assigned.
That last field answers which character is currently unused without manually
enumerating the ones already in use.  It may introduce a new outer level in a
self-contained document; it does not identify an existing sibling level and
is not by itself a repair for included or transformed titles.  It is also the
remediation lookup for a ``second effective top-level title`` ERROR.

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
underlying check pipeline still do, as does an incompatible option
combination; ``2`` is reserved for an argparse-level syntax error (see
:manpage:`check_rst(1)`, EXIT STATUS).

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-reports(1)`,
:manpage:`check_rst-workflow(7)`
