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

   check_rst [--config FILE | --no-config] [--standalone PATTERN]...
             [--fragment PATTERN]... entitle [--apply] [--quiet] NAME FILE

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
including composed byte-hygiene normalization and final-newline state.

The command writes exactly the one named file and judges it alone, without
Sphinx: ``--sphinx-src`` and ``--build-dir`` are rejected.  A configured
Sphinx source is *discovery-only*: Sphinx never runs, but the directory, which
must contain a ``conf.py``, is searched for includers and resolves an include
path that starts with ``/``.  A file's title levels can belong to a document
that includes it, so ``entitle`` first searches the project for possible
includers, as ``fix --fast`` does, honouring the configuration and the
``--standalone`` and ``--fragment`` declarations.  Before preview or write, it
refuses:

* a file that may be included, or that is declared a fragment;
* a file that includes another file, other than as ``:literal:`` or
  ``:code:`` text, since fast discovery cannot prove what it adds;
* a file outside every discovery root, whose includers cannot be searched;
* any file while another file or directory in the project cannot be read,
  since it may hold an include, or while an include path starting with
  ``/`` names no file and no Sphinx source is configured to resolve it.

``entitle`` has no full mode, and ``fix`` does not wrap, so such a file needs
composition-aware manual restructuring.  A top-level ``include`` directive is
outside the one-file safety boundary too, and is refused even when it is
literal text.  A file whose titles ``fix`` would refuse to renormalize, such as
one that uses a character both with and without an overline, is refused the
same way; the message names the line and the ambiguity, and the guide's
"Refused fixes" section explains how to resolve it.

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
return ``1`` for a rejected ``NAME``, a file refused for its include context,
a top-level ``include`` directive, an ambiguous title structure, a file that cannot be read or written, an
unresolved Git merge conflict, or an incompatible option combination.  ``2`` is reserved for an argparse-level
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
