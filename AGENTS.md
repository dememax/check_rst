<!--
Copyright (C) 2026 Maxime P. DEMENTYEV
SPDX-License-Identifier: GPL-3.0-only
-->

# check_rst

An opinionated deterministic front end for reStructuredText and Sphinx
documentation, distributed as a Python package under `src/check_rst/`, plus
its test suite (`tests/`) and its own Sphinx documentation (`docs/`). See
[README.md](README.md) for what the tool does and how a consuming project
configures it. This file covers conventions for working *on* the tool
itself.

## Purpose and current boundary

`check_rst` checks and fixes exact source geometry, exposes verified
structure for humans and AI assistants, and leaves semantic decisions to an
author or reviewer.

This standalone repository was seeded from Journal commit `3f7fef1` without
importing Journal's Git history. Journal retains the original development
history and evidence records. During extraction, preserve behavior first;
packaging, policy generalization, and module decomposition are separate tasks.

The command-line interface and JSON schema are the supported interfaces. The
Python functions imported by the test suite are implementation details, not a
promised public library API.

## Repository layout

| Path | Purpose |
|---|---|
| `src/check_rst/` | Package and command-line implementation |
| `tests/` | Complete unit and integration regression suite |
| `docs/` | User guide, semantic rules, development evidence, and roadmap |
| `.check_rst.toml` | This repository's explicit Sphinx facts |
| `pyproject.toml` | Packaging, test, formatting, and type-check configuration |

Normative behavior belongs in `docs/guide.rst` and `docs/rules.rst`.
`check_rst --help` stays a concise summary, in the same vocabulary
(notions, actions, roles, terms), pointing back at those pages rather than
restating them — see `docs/guide.rst`'s own note on this choice.
Design history and accepted or deferred work belong in `docs/roadmap.rst`.
Journal-specific paths must not become runtime dependencies; retained
Journal examples must be clearly identified as evidence or provenance.

## File header comment

Every nontrivial file — source, test, config, and documentation alike —
starts with this block, using the comment syntax of the file's format
(`#` for Python/TOML, `<!-- -->` for Markdown, `..` comments for RST):

```text
Copyright (C) 2026 Maxime P. DEMENTYEV
SPDX-License-Identifier: GPL-3.0-only
<one-line description of the file's purpose> — check_rst project
```

Copyright first, then the SPDX identifier — `GPL-3.0-only`, matching this
project's deliberate choice of GPL version 3 only, not "or later" (do not
copy a "*-or-later" example from elsewhere without checking which this
project actually uses). Use the current year for new files. The
description line is omitted for files like this one whose purpose is
already declared by their filename/title. Do not modify the verbatim GPL
text in `LICENSE` to add a project-specific notice.

## Development method

Use TDD for behavioral changes:

1. Add the smallest failing test that states the new predicate or regression.
2. Run the focused test and confirm the intended failure.
3. Implement the minimal coherent behavior.
4. Run the focused tests, then the complete suite.
5. Reconcile CLI help, user documentation, and the roadmap when the contract
   or implementation decision changes.

Keep implementation decomposition behavior-preserving and protect each
boundary move with dedicated characterization tests. Do not combine a
mechanical module move with unrelated policy changes.

Comments should explain decisions, invariants, safety predicates, and relevant
standards or library behavior. Do not narrate obvious syntax. When accepting a
source mutation, state both its candidate geometry and the semantic predicate
that makes it safe.

## Validation

Use the system toolchain, not an activated virtual environment. Python
commands must use Python 3.14 explicitly. Ruff is the system executable and
its version is pinned in `pyproject.toml`.

Run Python tests and static checks from the repository root:

```bash
python3.14 -m pytest
ruff format --check --no-cache src tests tools
ruff check --no-cache src tests tools
python3.14 -m mypy src tests tools
```

After an RST edit, invoke the worktree implementation so validation never
accidentally uses an older installed command:

```bash
PYTHONPATH=src python3.14 -m check_rst check --skip-fixable
PYTHONPATH=src python3.14 -m check_rst fix --fast
PYTHONPATH=src python3.14 -m check_rst check
```

Review semantic WARNINGs in the first pass. Never suppress them merely to
make the validation loop quiet. In a dirty worktree containing unrelated RST
edits, use the same `--git-scope` allowlist on all three commands — see
`docs/guide.rst`, "History protection: bare mode and selective Git scope",
for exactly what stays whole-file regardless of scope.

`fix`, explicit filenames, and recursive scopes can modify source. Inspect
Git state and preview uncertain or foreign content with `diff` before
writing. Preserve unrelated user changes.

Never bound or filter check_rst's own output with `head`/`tail`/`grep` —
apply `docs/guide.rst`'s own "Piping anti-patterns" to this repository's
validation loop first, not only to what the tool checks for others.

When intentionally introducing a bad edit to confirm a check fires against
this repository's own real content — not a `tmp_path` fixture — use `git
stash` or a temporary branch, never an in-place edit with manual cleanup: a
cleanup command like `grep -v "^$"` can silently alter unrelated content
(blank lines, whitespace) and leave the worktree dirty after the test.

## Packaging and compatibility

Keep the package version in one source of truth and expose it through
`check_rst --version` and JSON runtime provenance. A dependency or supported
Python/Sphinx range is a tested compatibility claim, not a guess; update it
only with corresponding test evidence.

Verified Sphinx mode loads the selected project's `conf.py` and extensions,
which execute Python code. Document and preserve the trust boundary: use it
only with trusted projects.

A breaking CLI change fails an un-updated downstream wrapper with a
distinctive, diagnosable signature rather than a silent fallback — e.g. the
subcommand redesign made a stale `check_rst --fix-only` call exit with
argparse's own "the following arguments are required: COMMAND", confirmed
live against a downstream project's own wrapper. Call this signature out in
the commit or release notes for any breaking change, so a consumer hitting
it afterward can rule out a version mismatch before suspecting a real
formatting defect.

## Documentation structure

Ask whether a cold human reader or fresh-context AI will need to retrieve a
concept independently. If yes, make it a real section rather than a bold
paragraph opener or a list item with a bold pseudo-heading. Use lists for
true sequences, classifications, and compact co-equal registers.

Declare new RST sections with a nine-character placeholder underline and let
the worktree `check_rst fix --fast` computation materialize adornment
geometry. Do not count adornment characters manually.

Navigate this repository's own `docs/` — finding a section, checking its
range, following its cross-references — with the worktree `check_rst
outline`/`check_rst context`, never `grep`/`sed` against raw markup. This
project's own documentation repeatedly makes the case against scanning raw
markup for structure; apply that discipline to this repository first, not
only to what the tool checks for others.

## Commits

Keep commits focused and explain the motivating context, findings, chosen
solution, safety boundary, and validation in the body. A concise subject
alone is insufficient when a future reader would otherwise have to
reconstruct why the change exists.

For Codex-authored work, include:

`Co-Authored-By: Codex GPT-5 <noreply@openai.com>`
