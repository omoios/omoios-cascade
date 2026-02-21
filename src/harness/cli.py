import argparse
import sys

from harness import __version__


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Multi-agent orchestration harness",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument(
        "-i",
        "--instructions",
        required=True,
        help="Task instructions",
    )
    run_parser.add_argument(
        "--config",
        help="Path to .env config file",
    )
    run_parser.add_argument(
        "--repos",
        nargs="+",
        help="Paths to target repositories",
    )

    subparsers.add_parser("version")
    return parser


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    parsed = parser.parse_args(args)

    if parsed.command == "version":
        print(__version__)
        return 0

    if parsed.command == "run":
        try:
            from harness.runner import run_harness
        except ImportError as exc:
            print(f"Missing dependency: {exc}")
            print("Run: uv pip install anthropic")
            return 1

        try:
            result = run_harness(
                instructions=parsed.instructions,
                config_path=parsed.config,
                repos=parsed.repos,
            )
            if result:
                print(f"\n--- Planner Result ---\n{result}")
        except KeyboardInterrupt:
            print("\nShutdown requested.")
            return 130
        except Exception as exc:
            print(f"Harness error: {exc}")
            return 1

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
