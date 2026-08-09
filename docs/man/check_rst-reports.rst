.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Structural report commands manual page — check_rst project

######################
check_rst-reports(1)
######################

******
NAME
******

check_rst-reports - query entry context, references, and JSON changes

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst [GLOBAL-OPTION]... context [--no-toctree] ENTRY FILE
   check_rst --sphinx-src DIR refs FILE
   check_rst diff-json OLD.json NEW.json

*********
CONTEXT
*********

``context`` prints a targeted pre-edit briefing for one structural entry.  An
entry may be a stable explicit ID, an ``outline``-generated selector, or an
exact title, term, or preview.  Ambiguous exact matches are reported rather
than guessed.  Verified mode can follow ``toctree`` entries; ``--no-toctree``
keeps the query local.

******
REFS
******

``refs`` reports the selected file's outgoing document/reference targets and
incoming references from other project files.  It reads the live Sphinx
environment rather than ``objects.inv`` and therefore requires
``--sphinx-src`` through configuration or a global option.

***********
DIFF-JSON
***********

``diff-json`` compares two objects produced by ``check --format json``.  It
matches findings by severity and message rather than physical line number, so
unrelated line movement is not reported as a resolved and reintroduced
finding.  The command reads no RST, loads no project, and rejects global
project options.

*************
EXIT STATUS
*************

Each query returns ``0`` for a successful report, including a ``diff-json``
report that describes changes.  Invalid input, an unresolved query, or a build
failure returns ``1``; invalid invocation or incompatible options returns
``2``.

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-outline(1)`,
:manpage:`check_rst-json(5)`
