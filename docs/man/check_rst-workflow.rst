.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Operational workflow manual page — check_rst project

#######################
check_rst-workflow(7)
#######################

******
NAME
******

check_rst-workflow - safe reading and edit-validation sequence

*********************
READ BEFORE EDITING
*********************

Run ``check_rst outline FILE`` before modifying a document not already read in
the current session.  Use ``context`` for one exact entry and verified
``refs`` when a cross-reference change depends on incoming or outgoing uses.

*******************
DECLARE STRUCTURE
*******************

For a new RST section, write the title with a nine-character placeholder
underline and let ``fix --fast`` materialize the correct adornment geometry.
Semantic choices—wording, nesting intent, and whether a WARNING represents a
real defect—remain with the author or reviewer.

*****************
VALIDATION LOOP
*****************

.. code-block:: console

   $ check_rst check --skip-fixable
   $ check_rst fix --fast
   $ check_rst check

Review WARNINGs in the first pass.  The middle command handles only bounded
mechanical work; the final pass verifies the resulting document, including
Sphinx when configured.  Use ``diff --fast`` before mutation when the source
is unfamiliar.

******************
SHARED WORKTREES
******************

Bare commands select every changed and untracked RST file.  In a shared dirty
worktree, pass the same ``--git-scope FILE...`` allowlist to all three stages.
Do not apply a fixer to edits whose ownership or intended semantics are
unknown.

***************
VERIFIED MODE
***************

Verified mode executes project Python configuration and extensions.  It is
the authoritative Sphinx result, but only for trusted projects.  Heuristic
mode is useful for standalone and foreign documents and is explicitly not a
substitute for a Sphinx build.

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-check(1)`,
:manpage:`check_rst-fix(1)`, :manpage:`check_rst-rules(7)`
