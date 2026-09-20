.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Structural report commands manual page — check_rst project

######################
check_rst-reports(1)
######################

******
NAME
******

check_rst-reports - query entry context, targets, references, and semantic changes

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst [GLOBAL-OPTION]... context [--no-toctree] ENTRY FILE
   check_rst --sphinx-src DIR targets [PATTERN] [--limit N]
   check_rst --sphinx-src DIR targets --exact NAME
   check_rst --sphinx-src DIR refs FILE
   check_rst --sphinx-src DIR refs --target LABEL
   check_rst compare [--staged | --unstaged | --from REV [--to REV]] [--patch] [-U N] [FILE]...
   check_rst compare --snapshots OLD.json NEW.json

*********
CONTEXT
*********

``context`` prints a targeted pre-edit briefing for one structural entry.  An
entry may be an explicit internal label, a stable explicit ID, an
``outline``-generated selector, or an exact title, term, caption, or preview.
For a label, the report distinguishes its definition line from the destination.
A known heading is the reason to use this query instead of raw ``grep``: the
result verifies its physical range, title anchor, uniqueness, parent, depth,
and source owner.  Ambiguous exact matches are reported rather than guessed.
Verified mode can follow ``toctree`` entries; ``--no-toctree`` keeps the query
local.

*********
TARGETS
*********

``targets [PATTERN]`` lists valid ``:ref:`` labels and ``:doc:`` names from
the live Sphinx registry.  ``PATTERN`` is a case-insensitive substring of a
name or title.  The output is bounded to 30 rows by default; ``--limit N``
changes that bound and the report counts suppressed matches.
``targets --exact NAME`` reports the defining document, physical definition
line when known, and resolved destination.  The inventory includes generated
labels such as those from ``autosectionlabel``; ``context LABEL FILE`` resolves
explicit internal labels in a known file.

******
REFS
******

``refs FILE`` reports the selected file's outgoing document/reference targets
and incoming document-level references from other project files.
``refs --target LABEL`` reports exact uses of one valid Sphinx label across the
project, including uses in its defining document.  Each invocation requires
exactly one of ``FILE`` or ``--target LABEL``.  Both modes read the live Sphinx
environment rather than ``objects.inv`` and require ``--sphinx-src`` through
configuration or a global option.

*********
COMPARE
*********

``compare`` defaults to ``HEAD`` against the worktree and reports changed RST
files, zero-context Git hunk geometry, and section ownership.  ``--staged``
selects ``HEAD`` against the index; ``--unstaged`` selects the index against
the worktree; ``--from`` and optional ``--to`` select revisions.  ``--patch``
appends a unified patch and ``-U`` controls its presentation context without
changing semantic ranges.

``compare --snapshots`` instead compares two objects produced by ``check
--format json``.  It matches findings by severity and message rather than
physical line number.  This adapter reads no RST, loads no project, and
rejects project, patch, and file-selection options.

*************
EXIT STATUS
*************

Each query returns ``0`` for a successful report, including a ``compare``
report that describes changes.  Invalid input, an unresolved query, a build
failure, or a rejected incompatible option combination returns ``1``; ``2``
is reserved for an argparse-level syntax error (see :manpage:`check_rst(1)`,
EXIT STATUS).

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-outline(1)`,
:manpage:`check_rst-json(5)`
