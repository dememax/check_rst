.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. List-table command manual page — check_rst project

#########################
check_rst-list-table(1)
#########################

******
NAME
******

check_rst-list-table - convert eligible aligned tables to list-table syntax

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst [--config FILE | --no-config] list-table [OPTION]... [FILE]...

*************
DESCRIPTION
*************

Convert eligible grid and simple tables, including ``table`` directives, to
``list-table`` source.  The default is a read-only unified diff; ``--apply``
writes independently proven conversions.  Processing uses bare Docutils, so
``--sphinx-src`` and ``--build-dir`` are incompatible.

*****************
TABLE SELECTION
*****************

``--only N`` selects the Nth table shown by ``outline`` and may be repeated.
``--skip N`` removes ordinals from that selection and may also be repeated.
Numbering includes existing list-tables and CSV tables, not only convertible
tables.  Default bulk conversion processes nested aligned tables
ancestor-first; selecting an inner table without its required ancestor is
refused.

**************
SAFETY PROOF
**************

Every candidate and the combined file must preserve the whole canonical
Docutils tree.  Source outside the selected table remains byte-for-byte
unchanged.  Captions and compatible ``table`` options carry across, and
effective column geometry is preserved while retaining automatic writer
layout when the source requested ``:widths: auto``.

**********
REFUSALS
**********

A refusal means the source is understood but lacks an equivalent conversion
within the command's boundary.  Existing list-tables are unchanged, CSV tables
are outside scope, and merged rows or columns have no ``list-table``
representation.  The diagnostic states the blocker, impact, and next action.
Ordinary refusals do not prevent unrelated proven tables from converting;
failure of an explicitly requested ``--only`` table leaves that file intact.

*************
EXIT STATUS
*************

Dry-run returns ``1`` if a diff would be produced or an error occurs, otherwise
``0``.  ``--apply`` returns ``1`` only for errors; an ordinary refusal alone is
not an error.  ``1`` is also returned for an incompatible option combination;
``2`` is reserved for an argparse-level syntax error (see
:manpage:`check_rst(1)`, EXIT STATUS).

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-outline(1)`,
:manpage:`check_rst-workflow(7)`
