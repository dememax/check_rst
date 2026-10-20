.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Configuration file manual page — check_rst project

#####################
check_rst-config(5)
#####################

******
NAME
******

check_rst-config - repository facts for check_rst

*************
DESCRIPTION
*************

Configuration records project identity, not personal policy.  ``check_rst``
supports a dedicated ``.check_rst.toml`` whose whole file is the settings
table, or a ``[tool.check_rst]`` table in ``pyproject.toml``.  When both exist
in the working directory, the dedicated file wins.  Discovery never walks to
parent directories.

******
KEYS
******

``sphinx-src = "DIR"``
   Sphinx source directory, resolved relative to the configuration file.

``build-dir = "DIR"``
   Reusable Sphinx build directory, resolved relative to the configuration
   file.  It is meaningful only with a Sphinx source.

``standalone = ["PATTERN", ...]``
   Files that remain standalone documents although another visible file
   includes them.  Their standalone reading is one more context to judge.

``fragments = ["PATTERN", ...]``
   Files with at least one includer check_rst cannot see.  That unavailable
   context protects their title structure from an unsupported guess.

The path keys must be strings; the role keys must be arrays of non-empty
pattern strings.  Unknown keys are errors.  Command-line path options override
loaded values, while repeatable ``--standalone`` and ``--fragment`` patterns
add to the configured roles.  A non-quiet run reports the source and which
values were applied or inactive.

************************
PATTERNS AND FILE SETS
************************

Configuration patterns are relative to the configuration directory and may
not be absolute.  ``*``, ``?`` and ``[...]`` stay within one path component;
``**`` as a complete component spans zero or more directories.  A hidden name
matches only an explicitly dotted component, and a directory-only pattern
matches nothing.  An unmatched pattern is an error rather than a silently
disabled safety declaration.

Role patterns match regular files under the discovery roots, including
Git-ignored files.  They never enter ``.git`` or descend through directory
symlinks.  A file symlink is accepted only when its target remains inside a
root.  Automatic includer discovery is narrower: it skips ignored files.
This lets ``fragments`` explicitly protect generated or ignored content while
keeping the automatic scan bounded.

With a configuration, its directory is the first discovery root; a configured
Sphinx source outside it is added.  Without configuration, each selected
file's Git worktree is a root; outside Git, the working directory covers only
selected files beneath it.  A selected file outside every discovery root
cannot have its includers searched.  Run from the intended project root or
pass ``--config FILE``.  An absolute command-line pattern, or one containing
``..``, may match only inside the union of established roots.

********************
EXPLICIT SELECTION
********************

``--config FILE`` selects a configuration from any working directory and uses
its containing directory as the project root.  ``--no-config`` disables both
file forms.  Both options must precede the command.

**********
SECURITY
**********

A configured Sphinx source enables verified mode, which imports ``conf.py``
and extensions.  Use configuration from trusted projects only.

*********
EXAMPLE
*********

.. code-block:: toml

   sphinx-src = "docs"
   build-dir = "/tmp/example-sphinx-build"
   standalone = ["appendix.rst"]
   fragments = ["parts/**/*.rst"]

**********
SEE ALSO
**********

:manpage:`check_rst(1)`, :manpage:`check_rst-check(1)`
