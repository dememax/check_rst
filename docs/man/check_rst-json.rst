.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. JSON report format manual page — check_rst project

###################
check_rst-json(5)
###################

******
NAME
******

check_rst-json - machine-readable check_rst report format

************
PRODUCTION
************

``check_rst check --format json`` writes exactly one UTF-8 JSON object to
standard output.  Progress and human finding lines are suppressed.  The
process still returns ``1`` when the report contains ERROR findings.

*******************
TOP-LEVEL MEMBERS
*******************

``schema_version`` identifies the contract version.  ``mode`` is ``verified``
or ``heuristic``.  ``runtime`` records versions that can affect results.
``config`` records the selected source and applied or inactive values, or is
null.  ``files`` contains per-document models, ``summary`` contains aggregate
counts, and verified reports may include ``sphinx_findings``.

**************
FILE RECORDS
**************

Each record names its path and findings and exposes structural arrays for the
outline, toctrees, code blocks, block quotes, tables, admonitions, comments,
and lists.  Outline IDs are stable document-and-title identities with an
occurrence suffix only when required.  Statistics distinguish unrequested
word analysis from requested-but-unavailable analysis.

************
COMPARISON
************

``check_rst diff-json OLD.json NEW.json`` validates both basic report shapes
and compares files, stable outline IDs, findings, Sphinx findings, summaries,
and runtime provenance.  Findings match by severity and text, never by line
number.

***************
COMPATIBILITY
***************

Consumers must inspect ``schema_version`` and tolerate additive members.
Runtime provenance is part of a meaningful comparison: a changed parser,
Sphinx, or checker version can change derived structure even when source does
not.

**********
SEE ALSO
**********

:manpage:`check_rst-check(1)`, :manpage:`check_rst-reports(1)`
