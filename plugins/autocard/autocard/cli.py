from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extractors import extract_character
from .ooxml import load_workbook_path
from .render import render_png, render_pngs
from .render_review import render_review_png
from .service import serve


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="autocard")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect", help="识别并读取人物卡")
    inspect_parser.add_argument("workbook", type=Path)
    render_parser = commands.add_parser("render", help="生成人物卡 PNG")
    render_parser.add_argument("workbook", type=Path)
    render_parser.add_argument("output", type=Path)
    review_parser = commands.add_parser("review", help="生成艾拉背景故事评审 PNG")
    review_parser.add_argument("workbook", type=Path)
    review_parser.add_argument("output", type=Path)
    serve_parser = commands.add_parser("serve", help="启动 HTTP 服务")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.host, args.port)
        return
    character = extract_character(load_workbook_path(args.workbook))
    if args.command == "inspect":
        print(json.dumps(character.to_dict(), ensure_ascii=False, indent=2))
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.command == "review":
        args.output.write_bytes(render_review_png(character))
    elif character.rule == "POKEMON-TRPG":
        payloads = render_pngs(character)
        args.output.write_bytes(payloads[0])
        for index, payload in enumerate(payloads[1:], 1):
            companion_output = args.output.with_name(f"{args.output.stem}-宝可梦-{index}{args.output.suffix}")
            companion_output.write_bytes(payload)
    else:
        args.output.write_bytes(render_png(character))
    print(args.output.resolve())


if __name__ == "__main__":
    main()
