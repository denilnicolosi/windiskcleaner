"""Entry point: the window, or a headless report with --report."""

from __future__ import annotations

import argparse
import json
import os
import sys

from diskdiet import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="diskdiet", description="Disk space analyzer.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--report", choices=("json", "html", "csv"), help="scan without a window")
    parser.add_argument("--root", default=os.environ.get("SystemDrive", "C:") + "\\")
    parser.add_argument("--out", help="report file (default: standard output)")
    args = parser.parse_args(argv)

    if not args.report:
        from diskdiet.ui.main_window import run

        return run()

    from diskdiet import advisor, report, rules, settings, system
    from diskdiet.scanner import scan

    result = scan(args.root, watch_paths=rules.watch_paths(), watch_names=advisor.REGENERABLE)
    programs = system.installed_programs()
    recs = advisor.build(result, programs=programs, exclude=settings.load()["exclude"])
    data = report.to_dict(result, recs, programs)
    if args.report == "csv":
        text = report.to_csv(result)
    else:
        text = json.dumps(data, indent=2) if args.report == "json" else report.to_html(data)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
