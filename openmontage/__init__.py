"""Public entrypoint for the plain-Python OpenMontage runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence


RUNTIME_ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 4750


def _prepare_runtime() -> None:
    """Make the portable runtime importable without installing a package."""
    runtime = str(RUNTIME_ROOT)
    if runtime not in sys.path:
        sys.path.insert(0, runtime)

    pythonpath = os.environ.get("PYTHONPATH")
    if not pythonpath:
        os.environ["PYTHONPATH"] = runtime
    elif runtime not in pythonpath.split(os.pathsep):
        os.environ["PYTHONPATH"] = os.pathsep.join((runtime, pythonpath))


def run(argv: Sequence[str] | None = None) -> int:
    """Run the local OpenMontage server or Backlot command."""
    _prepare_runtime()

    from backlot.__main__ import main as backlot_main

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0].startswith("-"):
        port = os.environ.get("OPENMONTAGE_PORT") or os.environ.get("BACKLOT_PORT")
        arguments = ["serve", "--port", port or str(DEFAULT_PORT), *arguments]
    return backlot_main(arguments)


__all__ = ["DEFAULT_PORT", "run"]
