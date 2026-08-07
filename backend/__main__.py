"""Entry point: `python -m backend [--port N] [--host HOST]`.

Refuses to start on any non-loopback bind address -- fail closed, per
BACKEND_PLAN.md §5.1. There is no configuration path that can override
this; `--host` is validated, not trusted.
"""

from __future__ import annotations

import argparse
import sys

from backend.errors import OfflineViolationError

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _validate_bind_host(host: str) -> None:
    if host not in LOOPBACK_HOSTS:
        raise OfflineViolationError(
            f"refusing to bind to non-loopback address {host!r} -- "
            f"this service serves COBOL source and banking-shaped data (NFR-S2, DC-1)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8420)
    args = parser.parse_args(argv)

    try:
        _validate_bind_host(args.host)
    except OfflineViolationError as exc:
        print(f"refusing to start: {exc.message}", file=sys.stderr)
        return 1

    import uvicorn

    uvicorn.run("backend.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
