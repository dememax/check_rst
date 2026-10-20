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
whole-document.  In verified Sphinx mode,
``toctree`` children are traversed unless ``--no-toctree`` is given.  Use this
command when the target structure is unknown; use ``check_rst context`` when
one exact entry or explicit label is already known.  Explicit labels attached
to headings appear beside their sections; other internal labels appear as
target metadata on the containing section.  They remain visible under
``--sections-only``.

Every section line names its title style, the adornment character and its
form, because reStructuredText reads the same character with and without an
overline as two distinct styles.  The style token is the character followed
by ``o`` for overline and underline or ``u`` for underline only, such as
``*o`` or ``*u``.  It is a bare ``n`` when the physical source does not prove
the complete style: a section without a source line, or one from transformed
or synthetic source.  The suffix letters are unambiguous because alphanumeric
characters cannot be adornment characters; the unknown token is never
``?n``, because ``?`` is itself a valid adornment character.  To add a sibling
title, copy the token shown on a sibling's line.

Every run prints a ``levels:`` legend: each depth with its title styles and
section count, the document's total section count, and the
first unused character in check_rst's canonical adornment order — or
``no free section char`` when every valid character is already assigned.
When any section's style is unproven (``n``), the hint is ``unknown``,
followed by how many sections are unproven: such a title may use any
character, so none can be called free.
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

When the selected file is itself a fragment, each section and leaf is
projected into every effective include context.  One outline is printed only
when those contexts agree and none is unavailable; otherwise the command
refuses rather than display a standalone hierarchy that no consumer uses.
Content after a title Docutils drops remains under the last surviving parsed
section, and nested-fragment leaves use their composed positions.

Verified output is parser-effective, not builder-final.  ``only`` and
``ifconfig`` containers are marked builder-dependent.  Extension-mutated or
configured synthetic source remains visible but is marked inexact rather than
given a misleading editable location.

*********
OPTIONS
*********

``--with-findings``
   Restore the complete validation report — every finding, the phase banners,
   and runtime provenance — with the structure view.  Findings are counted
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

Return ``1`` when include contexts disagree or one is unavailable, even if
the underlying validation has no ERROR.  A selected file outside every
discovery root is one such refusal: run from the intended project root or pass
``--config FILE`` so includers can be searched.  ERROR findings from the
underlying check pipeline also produce status ``1``, as does an incompatible
option combination; ``2`` is reserved for an argparse-level syntax error (see
:manpage:`check_rst(1)`, EXIT STATUS).  When the structure-only view hides
ERRORs, the line before the final status says how many and that
``--with-findings`` shows them.

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-reports(1)`,
:manpage:`check_rst-workflow(7)`
