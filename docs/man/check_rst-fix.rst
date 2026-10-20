.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Fix command manual page — check_rst project

##################
check_rst-fix(1)
##################

******
NAME
******

check_rst-fix - apply bounded reStructuredText corrections in place

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst [GLOBAL-OPTION]... fix [OPTION]... [FILE]...

*************
DESCRIPTION
*************

Apply Phase 0 byte hygiene and Phase 1 adornment/hierarchy geometry.  The
command rejects the complete selected set before writing if any file has an
unresolved Git merge entry.  Semantic WARNINGs remain author decisions.

Full ``fix`` plans a selected file in every available include context and in
its standalone use when one is declared or proven.  It applies a structural
edit only when every available include context needs the same physical edit,
the edit stays inside the selected file, no required context is unavailable,
and each includer's section tree revalidates.  Otherwise it keeps that file's
titles and reports ``include.context-conflict`` or
``include.context-unavailable``; byte hygiene may still apply.

*********
OPTIONS
*********

``--fast``
   Run the parser-free mechanical pass only: hygiene plus adornment and
   hierarchy fixes, without lint, statistics, or Sphinx.  It uses a
   conservative fast refusal: a possible include, declared fragment,
   incomplete scan, or file outside every discovery root protects structural
   changes that full ``fix`` might be able to prove safe.  For includers that
   both modes discover, fast mode may refuse where full mode proceeds, but it
   does not apply a conflicting structural edit.  Fast discovery scans only
   ``.rst`` includers.  If a non-``.rst`` includer can contribute structure,
   declare its target with ``fragments`` or ``--fragment``; without that fact,
   fast mode cannot protect the target and may differ from full mode.

``--normalize-blank-lines``
   Opt into parser-verified leading and repeated separator blank-line
   normalization.

``--collapse-title-spaces``
   Opt into parser-verified collapsing of space runs in section-title text.

``--single-space-prose``
   Opt into the parser-verified single-ASCII-space policy for eligible prose.

The three parser-verified editorial options are incompatible with ``--fast``.
Common selection and report options are described in :manpage:`check_rst(1)`.

***************
SAFE WORKFLOW
***************

Review semantic findings first, preview the exact mutation with
:manpage:`check_rst-diff(1)`, apply it, and run a complete check afterward.
Use the same ``--git-scope`` allowlist throughout a shared dirty worktree.

*************
EXIT STATUS
*************

Return ``0`` after a successful pass, including one that changed files;
return ``1`` for a non-fixable ERROR, a rejected mutation, or an
incompatible option combination, and ``2`` only for an argparse-level
syntax error (see :manpage:`check_rst(1)`, EXIT STATUS).

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-check(1)`,
:manpage:`check_rst-diff(1)`, :manpage:`check_rst-workflow(7)`
