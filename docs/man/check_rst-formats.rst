.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Supported source formats manual page — check_rst project

######################
check_rst-formats(7)
######################

******
NAME
******

check_rst-formats - native and bridge source-format boundaries

***************
NATIVE FORMAT
***************

``check_rst`` natively reads reStructuredText ``.rst`` files.  Its checks,
source ranges, structure model, and bounded fixers depend on Docutils' RST
parser.  Verified mode adds Sphinx project semantics; it does not introduce a
different source frontend.

***************
NON-RST INPUT
***************

Explicit paths with another suffix, including ``.md``, are ignored with a
clear “no .rst files” result.  They are not interpreted as RST and are never
rewritten.  This is a format boundary, not a successful Markdown validation.

*****************
MARKDOWN BRIDGE
*****************

Markdown can be converted externally for analysis:

.. code-block:: console

   $ pandoc --from gfm-gfm_auto_identifiers --to rst input.md --output converted.rst
   $ check_rst check --skip-fixable converted.rst

This can expose semantic patterns such as paragraph openers that resemble
headings.  Diagnostics refer to converted-RST lines, source mapping is not
preserved, and round-trip editing is lossy.  It is therefore an analysis
bridge, not permission for ``check_rst fix`` to edit Markdown.

******************
DESIGN PRINCIPLE
******************

The principle is format-agnostic—delegate exact syntax to deterministic
software—but the executable's present safety proof is RST-specific.  A native
frontend for another format requires its own parser, location model, and edit
proof rather than relabeling the existing RST pipeline.

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-workflow(7)`
