.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Entitle command manual page — check_rst project

######################
check_rst-entitle(1)
######################

******
NAME
******

check_rst-entitle - wrap a document under a new top-level title

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst entitle [--apply] [--quiet] NAME FILE

*************
DESCRIPTION
*************

Insert ``NAME`` as ``FILE``'s new depth-1 title, demoting whatever
top-level content already existed into ``NAME``'s own children, then
renormalize the whole document with the same hierarchy and adornment
fixer ``fix`` already uses.  The default is a read-only unified diff;
``--apply`` writes.  Leading front matter (comments, hyperlink targets, and
substitution definitions) is left in place above the new title, including in a
titleless file.  Ordinary introductory prose and field lists remain body
content and are wrapped even when they precede the first existing section.
The preview compares the raw source with the exact text ``--apply`` writes,
including composed byte-hygiene normalization and final-newline state.  The
command is self-contained: it reads and writes exactly the one named file, with
no project or Sphinx settings involved.  A top-level ``include`` directive is
outside that one-file safety boundary and is refused before preview or write;
included or transformed top-level titles require composition-aware manual
restructuring.

***********
PLACEMENT
***********

``NAME`` is always assigned the shallowest adornment character not
already used anywhere in ``FILE``, never an already-established one —
reusing one would make the new title a sibling of whatever established
that character's depth instead of a new, shallower parent.  Every
character already present is then remapped to the project's canonical
order for its new, one-level-deeper rank, exactly as ``fix`` already
does for any valid document.  ``NAME`` must be non-empty, a single
line, and not itself indistinguishable from a bare adornment line
(a string of one repeated character); the rare case where all 32 valid
adornment characters are already in use is refused rather than
silently reusing one.

*************
EXIT STATUS
*************

Return ``0`` after a successful preview or a successful ``--apply``;
return ``1`` for a rejected ``NAME``, a top-level ``include`` directive, a file
that cannot be read or written, an unresolved Git merge conflict, or an
incompatible option combination.  ``2`` is reserved for an argparse-level
syntax error (see :manpage:`check_rst(1)`, EXIT STATUS).  Unlike
``list-table``/``diff``,
a successful preview always exits ``0``: entitle always changes
something, so "would something change" carries no signal here.

**********
EXAMPLES
**********

.. code-block:: console

   $ check_rst entitle "Reference Guide" document.rst
   $ check_rst entitle "Reference Guide" document.rst --apply

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-fix(1)`,
:manpage:`check_rst-outline(1)`, :manpage:`check_rst-rules(7)`
