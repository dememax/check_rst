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

*********
OPTIONS
*********

``--fast``
   Run the parser-free mechanical pass only: hygiene plus adornment and
   hierarchy fixes, without lint, statistics, or Sphinx.

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
return ``1`` for findings or a rejected mutation and ``2`` for invalid usage.

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-check(1)`,
:manpage:`check_rst-diff(1)`, :manpage:`check_rst-workflow(7)`
