<!--
Copyright (C) 2026 Maxime P. DEMENTYEV
SPDX-License-Identifier: GPL-3.0-only
-->

# check_rst

## What it is

`check_rst` is a deterministic front end for checking, fixing, and querying
reStructuredText and Sphinx documentation. It checks byte hygiene, RST rules,
and Sphinx-aware structure; verified mode also runs a real Sphinx build.
Authors and reviewers keep control of wording and structure, while the tool
materializes character-exact syntax and returns verified structure for people
and AI agents.

## What it is not

Unlike whole-document reformatters such as Black and Prettier, `check_rst`
does not reprint documents or reflow prose. RST reformatters such as
`docstrfmt` and `rstfmt`, and neighbouring linters such as `doc8`, `rstcheck`,
`sphinx-lint`, and `restructuredtext-lint`, serve different scopes.

`check_rst` is not a Sphinx replacement: verified mode runs the selected
project's Sphinx configuration, while heuristic mode has no live Sphinx
project. It is not a native Markdown tool; an external Pandoc conversion can
support analysis, but `check_rst` never rewrites the Markdown source. It also
does not guess between ambiguous readings: it refuses the unsafe structural
change and explains the remedy.

## What `fix` changes—and never changes

By default, `fix` changes title-adornment geometry and byte hygiene: BOMs,
line endings, control whitespace, and trailing whitespace. It never changes
prose words or meaningful prose spacing by default. The
`--normalize-blank-lines`, `--collapse-title-spaces`, and
`--single-space-prose` modes are explicit, parser-verified opt-ins.

When the title model or include context does not prove one safe structural
edit, `fix` refuses that edit rather than choosing a reading. `diff` computes
the same candidate source without writing it and prints the exact unified diff
for review.

## Commands at a glance

Review:

- `check` — run hygiene, RST, structure, and optional Sphinx validation;
- `diff` — preview the source that `fix` would write;
- `compare` — explain changes between Git states or two saved JSON reports.

Write:

- `fix` — apply bounded hygiene and title-structure corrections;
- `list-table` — preview, or apply with `--apply`, an eligible table's
  conversion to `list-table` syntax;
- `entitle` — preview, or apply with `--apply`, a new top-level title.

Read:

- `outline` — print section structure and complete physical ranges;
- `context` — brief one explicit label, stable id, generated selector, or
  exact title, term, caption, or preview;
- `targets` — list or locate valid Sphinx cross-reference targets;
- `refs` — report a file's references or exact uses of one label;
- `hierarchy` — print the live adornment-character ranking.

Run `check_rst COMMAND --help` for each command's exact options.

## A real structure query

This repository can describe a document without a linear source scan:

```console
$ check_rst outline --outline-depth 1 --sections-only docs/releasing.rst
Outline: docs/releasing.rst
  levels: 1 '#o' (1), 2 '*o' (5), 6 sections total; next free section char: '='
  6-158:#o Releasing check_rst [5 subsections, 5 code blocks, 2 lists]
  (19 entries hidden — --outline-depth 1, --sections-only)
check_rst: 1 file(s) checked, 0 error(s), 0 warning(s), 6600 char(s) (84 distinct, 7 once), 6602 byte(s), 903 space(s) (14%)
```

## Limits and trade-offs

Verified mode imports the selected project's `conf.py` and extensions, which
execute Python code; use it only with trusted projects. Full mode uses
Docutils and, when configured, Sphinx evidence, while `--fast` stays
parser-free and therefore refuses more cases when safety cannot be proved.
Ambiguous title models and unavailable or conflicting include contexts can
make structural changes fail closed.

Only `check --format json` emits a machine-readable report; `compare
--snapshots` consumes two such reports. The supported runtime is Python 3.14
with Docutils `>=0.23,<0.24`. Verified reader queries include Sphinx setup;
measured costs and reproductions are recorded in
[the performance history](docs/performance-history.rst), without promising a
fixed latency. Markdown remains an analysis-only Pandoc bridge, not a native
editing format.

## Install

Build an ordinary installation from a clean Git export so ignored build
artifacts cannot enter the package:

```bash
cd /path/to/check_rst
git archive --prefix=check_rst/ --output=/tmp/check_rst-source.tar HEAD
python3.14 -m pip install /tmp/check_rst-source.tar
check_rst --help
```

The equivalent module invocation is:

```bash
python3.14 -m check_rst --help
```

Host-specific system-site setup, an isolated editable development environment,
and locale-sensitive test notes are in
[the development guide](docs/development.rst). The release procedure owns the
exact wheel-building and versioned-artifact commands.

## Where next

- Follow “Adopting `check_rst` in a new project” in
  [the guide](docs/guide.rst) before enabling writes on an existing corpus.
- Use the concise [manual pages](docs/man/index.rst) for command, configuration,
  JSON, format, workflow, and semantic contracts.
- Read [the development guide](docs/development.rst) for evidence, test
  environments, and review practice, and [the release procedure](docs/releasing.rst)
  for release-only build details.

The standalone repository was seeded from Journal commit `3f7fef1` on
2026-08-02 without importing Journal's Git history. Journal retains that
development history and the original evidence records.

## License

Copyright (C) 2026 Maxime P. DEMENTYEV.

Unless otherwise noted, this notice applies to the original material
throughout this repository.

This project is licensed under the GNU General Public License version 3 only.
See [LICENSE](LICENSE).
