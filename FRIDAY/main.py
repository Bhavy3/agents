from __future__ import annotations

import asyncio
import argparse

from core.app import FridayApp, run_app


def main() -> None:
    parser = argparse.ArgumentParser(description="FRIDAY local AI operating system runtime.")
    parser.add_argument(
        "--burn-in",
        action="store_true",
        help="Run continuous runtime validation (burn-in mode) instead of interactive terminal mode.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=300.0,
        help="Runtime validation duration in seconds.",
    )
    args = parser.parse_args()
    try:
        if args.burn_in:
            report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
            print(report)
        else:
            asyncio.run(run_app())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
