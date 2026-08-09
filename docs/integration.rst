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

The canonical manual-page sources live under ``docs/man``.  Build them with
``sphinx-build -b man docs docs/_build/man``.  A system package can install
the generated section 1, 5, and 7 pages under ``/usr/share/man/man1``,
``man5``, and ``man7`` respectively.  Python wheels intentionally do not guess
a system man directory: a private installation may instead place them under
``~/opt/check_rst/share/man`` and add that directory to ``MANPATH``.  In every
case the generated roff remains derived output, not a second documentation
source.

======================
Documentation layers
======================

``check_rst --help`` is the concise terminal-native command summary.  The
Sphinx-generated manual pages provide focused command and concept references;
the main guide remains the canonical operational contract.  The example
demonstrates a complete workflow, the semantic-rules guide covers decisions
the checker deliberately refuses to make, development records field evidence,
and the roadmap records accepted, deferred, and declined work.  Generated roff
is a build artifact and is never edited independently of its RST source.

``AGENTS.md`` defines development practice for this repository, written
agent-agnostic.  ``CLAUDE.md`` is a deliberately thin adapter so Claude Code
reads the same canonical instructions without maintaining a second copy.

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
