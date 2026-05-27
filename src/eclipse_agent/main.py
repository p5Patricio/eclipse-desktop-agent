"""Minimal CLI entrypoint for Eclipse."""

from __future__ import annotations

import argparse

from eclipse_agent import __version__
from eclipse_agent.config import EclipseConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eclipse-agent",
        description="Eclipse Desktop Agent CLI skeleton.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--mode",
        choices=["observe", "draft", "copilot", "autonomous"],
        default="draft",
        help="Runtime mode. MVP should use observe/draft/copilot only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = EclipseConfig(default_mode=args.mode)
    print(f"Eclipse initialized in {config.default_mode!r} mode.")
    print("Next milestone: voice push-to-talk + spoken response.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
