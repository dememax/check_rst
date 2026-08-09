.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Semantic boundary manual page — check_rst project

####################
check_rst-rules(7)
####################

******
NAME
******

check_rst-rules - deterministic checks and human decisions

**********
BOUNDARY
**********

``check_rst`` owns facts that software can prove: bytes, whitespace bounded by
the parser contract, adornment geometry and hierarchy, document structure,
reference resolution, and equality of supported source transformations.  It
does not decide document meaning, information architecture, or editorial
intent.

********
ERRORS
********

An ERROR identifies a violated mechanical contract or a failed requested
operation.  Examples include invalid source geometry, broken byte hygiene,
unresolved structural integrity, an unsafe transformation proof, and Sphinx
build failures.  ERRORs select exit status ``1``.

**********
WARNINGS
**********

A WARNING exposes evidence that requires context: a bold paragraph that may be
a hidden heading, a rubric used as structure, suspicious nested inline markup,
a confusable letter, or prose that resembles an unresolved reference.  The
tool provides source location and context but deliberately does not rewrite
the semantic choice.  WARNINGs alone return status ``0``.

******************
COLD-READER TEST
******************

Judge structure by whether a reader without the author's recent context can
retrieve and navigate the concept.  When the answer depends on role, instance,
or context state, inspect the document with ``outline`` and ``context`` before
promoting prose or suppressing a warning.

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-outline(1)`,
:manpage:`check_rst-workflow(7)`
