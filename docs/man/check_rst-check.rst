.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Check command manual page — check_rst project

####################
check_rst-check(1)
####################

******
NAME
******

check_rst-check - report reStructuredText and Sphinx findings

**********
SYNOPSIS
**********

.. code-block:: text

   check_rst [GLOBAL-OPTION]... check [OPTION]... [FILE]...

*************
DESCRIPTION
*************

Run Phase 0 byte hygiene, Phase 1 RST lint, Phase 2 structure checks, and,
with ``--sphinx-src``, the Phase 3 Sphinx build.  The command does not modify
source files.

*******************
IMPORTANT OPTIONS
*******************

``--format text|json``
   Select human-readable output or one complete JSON object on standard
   output.  See :manpage:`check_rst-json(5)`.

``--skip-fixable``
   Hide findings that ``fix`` can resolve while keeping WARNINGs and
   non-fixable ERRORs.  This is the recommended first pass before mutation.

``--no-warnings``
   Hide WARNING findings while continuing to count and report ERRORs.

``--no-adornments``, ``--no-directives``
   Disable the corresponding checks.  ``--no-adornments`` includes title
   geometry, hierarchy, and effective single-title enforcement.  Phase 0
   remains enabled.

``--no-toctree``
   Do not recurse through ``toctree`` directives in verified mode.

``--max-output-lines N``
   Bound the human report without changing the exit status.  The final status
   line is always retained.

``--quiet``, ``--verbose``, ``--word-samples N``
   Control progress, supporting detail, and prose-word samples.

*************
EXIT STATUS
*************

Return ``0`` when there are no ERROR findings, ``1`` when at least one ERROR
exists, and ``2`` for invalid invocation.  WARNINGs alone return ``0``.

**********
EXAMPLES
**********

.. code-block:: console

   $ check_rst check --skip-fixable
   $ check_rst --sphinx-src docs check docs/guide.rst
   $ check_rst check --format json document.rst >report.json

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-fix(1)`,
:manpage:`check_rst-json(5)`, :manpage:`check_rst-rules(7)`
