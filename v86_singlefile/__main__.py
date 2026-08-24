from __future__ import annotations
import argparse
import json
from .builder import build, fetch_asset, load_config, validate_output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build auditable self-contained v86 HTML applications")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build"); p.add_argument("config"); p.add_argument("output"); p.add_argument("--cache", default=".v86-cache")
    p = sub.add_parser("validate"); p.add_argument("html")
    p = sub.add_parser("fetch"); p.add_argument("url"); p.add_argument("sha256"); p.add_argument("output"); p.add_argument("--max-mb", type=int, default=512)
    args = parser.parse_args()
    if args.command == "build": result = build(load_config(args.config), args.output, args.cache)
    elif args.command == "validate": result = validate_output(args.html)
    else: result = {"output": str(fetch_asset(args.url, args.sha256, args.output, args.max_mb * 1024 * 1024))}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())

