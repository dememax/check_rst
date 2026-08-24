.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Launcher, doc layers, and test-suite notes — check_rst project

###############################
check_rst project integration
###############################

*****************************
Standalone project boundary
*****************************

The implementation, complete regression suite, product documentation, roadmap,
and release identity live in this repository.  A consuming documentation
project owns only its local facts: ``.check_rst.toml``, Sphinx configuration,
workflow instructions, and any integration smoke tests.

The CLI and JSON schema are the supported external interfaces.  Consumers run
the installed command; they do not import private implementation functions or
reach into this checkout by filesystem path.  This keeps a project such as the
source Journal independent of implementation layout changes.

==============
Installation
==============

The package declares a ``check_rst`` console entry point and requires Python
3.14.  Install it once with a standards-based Python package installer.  Its
docutils compatibility range deliberately covers both PyPI's Sphinx 9.1.0
stack (docutils 0.22.4) and distribution builds such as Gentoo's Sphinx
9.1.0-r1 stack (docutils 0.23); the suite is validated in both environments.
A host-specific launcher may pin an absolute interpreter or installed
checkout when protection from an activated virtual environment is required;
that launcher belongs to the host configuration, not to a consuming
repository.

Normal Git integration is provided by the declared ``pygit2`` dependency and
does not shell out to the Git CLI.  The ``git`` executable is a conditional
compatibility dependency when a worktree's current status contains a filename
that is not valid UTF-8: ``pygit2`` cannot expose that status path as a Python
string, so ``check_rst`` uses Git's NUL-delimited byte output for that query.
If the executable is unavailable in this exceptional case, the command exits
with a clean ``git status failed`` diagnostic.  The subprocess preserves the
caller's environment except for forcing ``LC_ALL=C`` to keep Git's failure
detail deterministic.

The interpreter boundary must still include every Sphinx extension loaded by
consumer ``conf.py`` files.  On Gentoo, the preferred host-wide installation
is therefore a virtual environment created with ``--system-site-packages``
and containing only ``check_rst`` installed with ``--no-deps``.  It reuses the
distribution's coherent Sphinx, docutils, and extension set while the launcher
still prevents an unrelated activated project environment from changing the
entry point.  A fully isolated pip environment is equally valid only when all
extensions required by its consuming projects are installed inside it.

Verified mode loads the selected project's ``conf.py`` and extensions, which
execute Python code.  Use ``--sphinx-src`` or a repository configuration only
for trusted projects.

--------------------------
Manual-page installation
--------------------------

The canonical manual-page sources live under ``docs/man``.  From a source
checkout, the registry-driven installer builds and installs every page listed
by Sphinx's ``man_pages`` setting in ``docs/conf.py``:

.. code-block:: console

   $ python3.14 tools/install_man_pages.py --prefix "$HOME/opt"
   $ export MANPATH="$HOME/opt/share/man${MANPATH:+:$MANPATH}"
   $ man check_rst

The installer places pages under the appropriate ``share/man/man1``, ``man5``,
and ``man7`` directories and then runs ``makewhatis`` or ``mandb`` when one is
available.  A distribution package stages the same registry without touching
the host's manual index:

.. code-block:: console

   $ python3.14 tools/install_man_pages.py --prefix /usr --destdir "$pkgdir"

``--skip-build`` installs already-generated pages from ``--build-dir``;
``--no-index`` leaves live-prefix index maintenance to the caller.  The direct
build command remains ``sphinx-build -b man docs docs/_build/man``.  Python
wheels intentionally do not guess a host manual directory, so this is a
source-checkout or distribution-packaging operation.  Generated roff remains
derived output, not a second documentation source.

======================
Documentation layers
======================

``check_rst --help`` is the concise terminal-native command summary.  The
Sphinx-generated :doc:`man/index` pages provide focused command and concept
references; :doc:`guide` remains the canonical operational contract.
:doc:`example` demonstrates a complete workflow, :doc:`rules` covers
decisions the checker deliberately refuses to make, :doc:`development`
records field evidence, and :doc:`roadmap` records accepted, deferred, and
declined work.  Generated roff is a build artifact and is never edited
independently of its RST source.

``AGENTS.md`` defines development practice for this repository, written
agent-agnostic.  ``CLAUDE.md`` is a deliberately thin adapter so Claude Code
reads the same canonical instructions without maintaining a second copy.

===============================================================
Anti-pattern: ambient installation metadata in a source build
===============================================================

A source-checkout documentation build must not obtain its version by importing
whatever ``check_rst`` happens to be installed in the invoking interpreter.
That can appear to work in an editable development environment, then fail in a
clean checkout with ``ModuleNotFoundError`` or, more subtly, put an older
installed version into generated manuals.  The checkout is authoritative:
``docs/conf.py`` explicitly prefers its sibling ``src`` tree before importing
the package's single version source.  It must not duplicate that version in a
second hardcoded literal.

The regression runs the configuration under ``python -I -S``.  Removing the
working directory, ``PYTHONPATH``, and site packages makes ambient installation
state unable to satisfy the import and proves that the checkout is sufficient
on its own.

============
Test suite
============

The split suite under ``tests/`` pins rules, fixers, structural queries, CLI
conflicts, packaging metadata, documentation builds, and check/fix-agreement
invariants.  Tests import implementation functions for precise white-box
predicates, but that access is not a public library API.  External
compatibility is established through the command line and JSON output.

************
Provenance
************

The standalone repository was seeded on 2026-08-02 from Journal commit
``3f7fef1`` without importing Journal's Git history.  Journal retains the
original July–August 2026 commit series and calendar evidence.  The initial
import preserves the mature behavior and tests while establishing a new,
explicit release history from version 0.1.0.
