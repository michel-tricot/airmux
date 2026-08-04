from __future__ import annotations

import argparse


def cmd_seed(args: argparse.Namespace) -> int:
    raise NotImplementedError


def cmd_compile(args: argparse.Namespace) -> int:
    raise NotImplementedError


def cmd_verify(args: argparse.Namespace) -> int:
    raise NotImplementedError


def cmd_loadgen(args: argparse.Namespace) -> int:
    raise NotImplementedError


def main() -> int:
    parser = argparse.ArgumentParser(prog="gw")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("seed").set_defaults(func=cmd_seed)
    subparsers.add_parser("compile").set_defaults(func=cmd_compile)
    subparsers.add_parser("verify").set_defaults(func=cmd_verify)
    subparsers.add_parser("loadgen").set_defaults(func=cmd_loadgen)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
