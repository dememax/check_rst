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
Recognizable JSON requests also retain this one-object contract for empty
selections and command, input, or configuration failures.

An undecodable Unix filename byte is serialized as a reversible low-surrogate
JSON escape (``\uDC80`` through ``\uDCFF``), never as a raw non-UTF-8 output
byte.  Consumers that need the physical path bytes must preserve that lone
surrogate while parsing and encode the resulting string with the platform
filesystem encoding and ``surrogateescape`` error handler.

Common JSON processors do not all preserve lone surrogates: in particular,
``jq`` and JavaScript/Node pipelines may replace or reject them.  A consumer
that needs byte-exact Unix paths must test its complete parser and transport,
not only Python's ``json`` module.

*******************
TOP-LEVEL MEMBERS
*******************

``schema_version`` identifies the JSON schema.  ``mode`` is ``verified``,
``heuristic``, or ``unavailable`` when failure precedes project selection.
``scope`` distinguishes ``whole-files`` from ``changed-git-hunks`` on normal
reports.  ``runtime`` records versions that can affect results, including
``runtime.check_rst.contract_version`` for the integer CLI contract queried by
``check_rst --contract-version``.
``config`` records the selected source and applied or inactive values, or is
null.  ``files`` contains per-document models, ``summary`` contains aggregate
counts, and verified reports may include ``sphinx_findings``.  Each finding
records its ``<domain>.<condition>`` rule ``code`` and ``location_exact``;
``summary.suppressed`` counts WARNINGs hidden by
``--no-warnings``, findings hidden by ``--skip-fixable``, and proven fixable
Sphinx restatements, kept apart from the visible totals.  A retainable WARNING
records ``source_sha256``; one hidden by a ``.check_rst-retained.toml`` entry
also records ``retained`` with its reason, ``summary.retained`` counts them,
and ``stale_retentions`` lists entries a whole-file check no longer matched.
Before per-file state exists, ``mode`` is ``unavailable``, ``files`` is empty,
and ``errors`` contains objects with ``kind`` (currently ``command``) and the
human-readable ``message``.  These failure objects retain
``runtime.check_rst.version`` and ``runtime.check_rst.contract_version``.  A
successful empty selection has empty ``files`` and ``errors`` arrays.

**************
FILE RECORDS
**************

Each record names its path and findings and exposes structural arrays for the
outline, toctrees, code blocks, block quotes, tables, admonitions, comments,
and lists.  Outline IDs are stable document-and-title identities with an
occurrence suffix only when required.  Statistics distinguish unrequested
word analysis from requested-but-unavailable analysis.

Outline records include ``labels`` for explicit section labels and ``targets``
for other explicit internal labels.  Each item includes the physical
definition line.  Empty arrays mean no such labels were modeled for that
entry.

For an outline section, ``source_start`` is the first line of its complete
physical block, including an overline; ``lineno`` remains the title-line
anchor, and ``end`` is the final content line.  ``source_start`` is 0 when no
honest editable coordinate survives source transformation.  Consumers should
use ``source_start`` through ``end`` for a source read and retain ``lineno``
for title-anchored identity or diagnostics.

Every finding declares ``severity`` and ``fixable`` independently.  ``scope``
is ``source`` for a located or source-owned finding and ``project-wide`` when
no physical line can own a project diagnostic.  ``source`` is null for the
selected root or identifies a physical or synthetic composed source; line 0
means no honest editable coordinate survived transformation.

*************
COMPOSITION
*************

Each file record declares ``structure_stage``.  Its value is currently
``parser-effective``.  ``includes`` contains parsed include control points and
``conditionals`` contains unresolved ``only``/``ifconfig`` containers.

An entry originating outside the root source has a ``provenance`` object.
``source`` identifies the physical or synthetic owner, ``origin`` identifies
how it entered the effective document, ``include_chain`` records every include
edge, and ``exact`` states whether the reported coordinates still correspond
to editable physical text.  Consumers must not propose a source edit when
``exact`` is false.  An included section's stable ``id`` is based on its
physical source without the ``.rst`` suffix, not on the document that included
it.

************
COMPARISON
************

``check_rst compare --snapshots OLD.json NEW.json`` validates both basic report shapes
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
