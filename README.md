<!--
Copyright (C) 2026 Maxime P. DEMENTYEV
SPDX-License-Identifier: GPL-3.0-only
-->

# check_rst

`check_rst` is an opinionated deterministic front end for reStructuredText
and Sphinx documentation. It combines byte hygiene, project formatting rules,
structural queries, Sphinx-aware reference analysis, safe fixers, and
machine-readable reports in one command.

The tool is designed for both human and AI-assisted documentation workflows:
semantic decisions stay with the author or reviewer, while exact source
geometry and parser-verifiable transformations are delegated to software.

The detailed reference is in [docs/guide.rst](docs/guide.rst).

## Supported source formats

`check_rst` natively reads and, for explicitly selected operations, rewrites
reStructuredText (`.rst`). With `--sphinx-src`, it also verifies trusted Sphinx
projects against their live configuration and extensions. Markdown (`.md`) is
not a native input format: an explicit Markdown path is ignored with a clear
“no `.rst` files” result.

Markdown can be converted externally with Pandoc and checked as generated RST
for analysis. Diagnostics then refer to converted-RST lines, and round-trip
editing is outside the safety contract; `check_rst` does not rewrite the
Markdown source.

## Installation

Requires Python 3.14 or newer. The shortest path from a clone to a working
command is:

```bash
python3.14 -m pip install /path/to/check_rst
check_rst --help
```

`pip install` builds a wheel internally and installs both the Python package
and its console entry point, along with its bounded dependencies (`docutils`,
`Sphinx`, `snowballstemmer`, `pygit2`).  The supported docutils range is
0.22.4 through 0.23: PyPI's Sphinx 9.1.0 resolves to docutils 0.22.4, while
distributions such as Gentoo may provide a tested Sphinx build with docutils
0.23.  Both runtime combinations run the same test suite.  To build the
wheel explicitly instead:

```bash
cd /path/to/check_rst
python3.14 -m pip wheel --wheel-dir dist .
python3.14 -m pip install dist/check_rst-0.5.0-py3-none-any.whl
```

The generated wheel is a pure-Python, platform-independent package. Its exact
filename includes the package version from `check_rst.__version__`.

On Gentoo, a host-wide checker should reuse the distribution's coherent
Sphinx/docutils stack and its installed Sphinx extensions. Keep the launcher
isolated while exposing those packages with a system-site virtual environment,
then install only `check_rst` into it:

```bash
python3.14 -m venv --system-site-packages ~/opt/check_rst
~/opt/check_rst/bin/python -m pip install --no-build-isolation --no-deps /path/to/check_rst
```

This matters for verified mode: a consuming project's `conf.py` may load
extensions such as `sphinxcontrib.plantuml`, and those extensions must be
importable by the same interpreter that runs `check_rst`. Use ordinary
dependency-resolving `pip install` in a self-contained environment when its
projects also install their Sphinx extensions there.

To reproduce the Gentoo validation stack on Ubuntu, install the same tested
direct dependency versions rather than accepting pip's Docutils downgrade.
Upstream Sphinx 9.1.0 metadata declares `docutils<0.23`; Gentoo removes that
upper bound before building Sphinx. The following mirrors that one
metadata adjustment, so the resulting environment remains coherent under
`pip check` while running Sphinx 9.1.0 with Docutils 0.23:

```bash
python3.14 -m venv ~/opt/check_rst-ubuntu
install -d /tmp/check_rst-sphinx-source
~/opt/check_rst-ubuntu/bin/python -m pip download \
    --no-deps --no-binary=:all: --dest /tmp/check_rst-sphinx-source \
    Sphinx==9.1.0
tar -xf /tmp/check_rst-sphinx-source/sphinx-9.1.0.tar.gz \
    -C /tmp/check_rst-sphinx-source
sed -i 's/docutils>=0.21,<0.23/docutils>=0.21/' \
    /tmp/check_rst-sphinx-source/sphinx-9.1.0/pyproject.toml
~/opt/check_rst-ubuntu/bin/python -m pip install \
    /tmp/check_rst-sphinx-source/sphinx-9.1.0 \
    docutils==0.23 snowballstemmer==3.1.1 pygit2==1.19.3 \
    mypy==2.2.0 types-docutils==0.22.3.20260518 \
    pytest==9.1.1 pytest-cov==7.1.0 setuptools==83.0.0
~/opt/check_rst-ubuntu/bin/python -m pip install \
    --no-build-isolation --no-deps --editable /path/to/check_rst
~/opt/check_rst-ubuntu/bin/python -m pip check
```

Ruff is not installed into this environment. Use the system Ruff 0.16.2,
which is the exact version required by `pyproject.toml`.

For development, install the checkout in editable mode:

```bash
cd /path/to/check_rst
python3.14 -m pip install --editable .
```

Ordinary Python source edits then take effect without reinstalling. Reinstall
after changing packaging metadata or console entry points in `pyproject.toml`.
For a normal installation, use `python3.14 -m pip install --upgrade .`. For
the Gentoo system-site model above, retain its dependency boundary:

```bash
~/opt/check_rst/bin/python -m pip install --no-build-isolation --no-deps --upgrade .
```

The `pyproject.toml` console entry point installs `check_rst` in the
selected Python environment's scripts directory, which must be on `PATH`.
The equivalent module invocation is:

```bash
python3.14 -m check_rst --help
```

## Quick start

```bash
check_rst --help
check_rst check path/to/document.rst
check_rst outline path/to/document.rst
check_rst diff path/to/document.rst
```

A repository can declare its Sphinx source and reusable build directory in
`.check_rst.toml`:

```toml
sphinx-src = "docs"
build-dir = "/tmp/my-project-sphinx-build"
```

Verified Sphinx mode imports the selected project's `conf.py` and extensions,
which execute Python code. Use `--sphinx-src` or configuration that supplies it
only with projects you trust.

With no positional files, `check_rst` selects changed and untracked RST
files from Git. Explicit files are checked in full. Read the complete guide
linked above before enabling mutations in an existing documentation set.

## Manual pages

The repository includes concise Sphinx sources for `check_rst(1)`, individual
commands, configuration and JSON contracts, source formats, workflow, and
semantic boundaries. From a source checkout, build and install every page
registered in `docs/conf.py` under a private prefix with:

```bash
python3.14 tools/install_man_pages.py --prefix "$HOME/opt"
export MANPATH="$HOME/opt/share/man${MANPATH:+:$MANPATH}"
man check_rst
```

The installer invokes Sphinx, installs the registered section 1, 5, and 7
pages, and updates the prefix's manual index with `makewhatis` or `mandb` when
available. Distribution packaging can stage the same registry below a package
root without modifying the host index:

```bash
python3.14 tools/install_man_pages.py --prefix /usr --destdir "$pkgdir"
```

Use `--skip-build` with `--build-dir` to install an existing Sphinx man build,
or `--no-index` when the caller owns index maintenance. The underlying manual
build remains `sphinx-build -b man docs docs/_build/man`. Python wheels do not
choose a host man-page directory, so manual installation is deliberately a
source-checkout or distribution-packaging operation.

## Development

The implementation is divided by responsibility under `src/check_rst/`, with
unit, integration, CLI, packaging, and documentation tests under `tests/`.
Run the complete regression and static-check suite from the repository root:

```bash
python3.14 -m pytest
ruff format --check --no-cache src tests tools
ruff check --no-cache src tests tools
PYTHONPATH=src python3.14 -m check_rst check --recursive docs
```

The standalone repository was seeded from Journal commit `3f7fef1` on
2026-08-02 without importing Journal's Git history. Journal retains that
development history and the original evidence records.

## License

Copyright (C) 2026 Maxime P. DEMENTYEV.

Unless otherwise noted, this notice applies to the original material
throughout this repository.

This project is licensed under the GNU General Public License version 3 only.
See [LICENSE](LICENSE).
