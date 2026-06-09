"""Small argparse-based CLI."""

import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="tool")
    subparsers = parser.add_subparsers(dest="command")

    echo = subparsers.add_parser("echo")
    echo.add_argument("--upper", action="store_true")
    echo.add_argument("text")

    total = subparsers.add_parser("sum")
    total.add_argument("values", nargs="+")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "echo":
        text = args.text.upper() if args.upper else args.text
        print(text)
        return 0
    if args.command == "sum":
        print("".join(args.values))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
