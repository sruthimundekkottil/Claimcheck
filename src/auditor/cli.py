"""The `audit` command. Only `validate` exists so far."""

import argparse
import sys

from auditor.pack import PackError, load_pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="check a pack folder and report every problem")
    v.add_argument("pack", help="path to the pack folder")
    args = parser.parse_args(argv)

    try:
        pack = load_pack(args.pack)
    except PackError as e:
        print(f"{args.pack}: {len(e.errors)} problem(s)", file=sys.stderr)
        for err in e.errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    for w in pack.warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(f"OK {pack.manifest.name}: {len(pack.rules)} rules, {len(pack.tests)} tests, "
          f"{len(pack.rubric.dimensions)} dimensions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
