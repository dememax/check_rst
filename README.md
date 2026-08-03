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

## Installation

Requires Python 3.14 or newer. The shortest path from a clone to a working
command is:

```bash
python3.14 -m pip install /path/to/check_rst
check_rst --help
```

`pip install` builds a wheel internally and installs both the Python package
and its console entry point, along with its pinned dependencies (`docutils`,
`Sphinx`, `snowballstemmer`). To build the wheel explicitly instead:

```bash
cd /path/to/check_rst
python3.14 -m pip wheel --wheel-dir dist .
python3.14 -m pip install dist/check_rst-0.1.0-py3-none-any.whl
```

The generated wheel is a pure-Python, platform-independent package. Its exact
filename includes the package version from `check_rst.__version__`.

For development, install the checkout in editable mode:

```bash
cd /path/to/check_rst
python3.14 -m pip install --editable .
```

Ordinary Python source edits then take effect without reinstalling. Reinstall
after changing packaging metadata or console entry points in `pyproject.toml`.

The `pyproject.toml` console entry point installs `check_rst` in the
selected Python environment's scripts directory, which must be on `PATH`.
The equivalent module invocation is:

```bash
python3.14 -m check_rst
```

## Quick start

```bash
check_rst --help
check_rst path/to/document.rst
check_rst --outline-only path/to/document.rst
check_rst --diff path/to/document.rst
```

A repository can declare its Sphinx source and reusable build directory in
`.check_rst.toml`:

```toml
sphinx-src = "docs"
build-dir = "/tmp/my-project-sphinx-build"
```

With no positional files, `check_rst` selects changed and untracked RST
files from Git. Explicit files are checked in full. Read the complete guide
linked above before enabling mutations in an existing documentation set.

## Development

The imported implementation is intentionally kept as one module during the
repository extraction. Behavioral decomposition can follow independently,
protected by the complete regression suite:

```bash
python3.14 -m pytest
ruff format --check --no-cache src tests
ruff check --no-cache src tests
PYTHONPATH=src python3.14 -m check_rst --recursive docs
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
