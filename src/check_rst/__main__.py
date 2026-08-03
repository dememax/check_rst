# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
"""Support ``python -m check_rst``."""


def _run() -> None:
    """Import the CLI lazily so package metadata remains lightweight."""
    from check_rst.cli import main

    main()


if __name__ == "__main__":
    _run()
