"""Export of a scan as a plain dict (JSON) or a self-contained HTML page."""

from __future__ import annotations

from html import escape

from diskdiet import __version__
from diskdiet.strings import fmt_size


def to_dict(result, recs, programs=()) -> dict:
    top = sorted(result.root.children, key=lambda n: -n.size)
    return {
        "diskdiet": __version__,
        "root": result.root.path,
        "size": result.root.size,
        "files": result.root.files,
        "seconds": round(result.seconds, 1),
        "unreadable_items": result.denied,
        "folders": [{"path": n.path, "size": n.size, "files": n.files} for n in top],
        "recommendations": [
            {
                "id": r.id, "category": r.category, "safety": r.safety.value,
                "action": r.action.value, "title": r.title, "why": r.why, "size": r.size,
                "paths": r.paths, "commands": [" ".join(c.argv) for c in r.commands],
            }
            for r in recs
        ],
        "largest_files": [
            {"path": f.path, "size": f.size} for f in sorted(result.big_files, reverse=True)[:100]
        ],
        "programs": [{"name": p.name, "size": p.size} for p in programs],
    }


def _table(head: list[str], rows: list[list[str]]) -> str:
    cells = "".join(f"<th>{escape(h)}</th>" for h in head)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><tr>{cells}</tr>{body}</table>"


def to_html(data: dict) -> str:
    recs = [
        [r["title"], fmt_size(r["size"]), r["safety"], r["why"], "\n".join(r["commands"])]
        for r in data["recommendations"]
    ]
    folders = [[f["path"], fmt_size(f["size"])] for f in data["folders"]]
    files = [[f["path"], fmt_size(f["size"])] for f in data["largest_files"]]
    return (
        "<!doctype html><meta charset='utf-8'><title>DiskDiet report</title>"
        "<style>body{font-family:Segoe UI,sans-serif;margin:2em}"
        "table{border-collapse:collapse;margin-bottom:2em}"
        "td,th{border:1px solid #bbb;padding:4px 8px;text-align:left;vertical-align:top}</style>"
        f"<h1>DiskDiet — {escape(data['root'])}</h1>"
        f"<p>{fmt_size(data['size'])} in {data['files']:,} files.</p>"
        "<h2>Recommendations</h2>"
        + _table(["Item", "Size", "Safety", "Why", "Commands"], recs)
        + "<h2>Folders</h2>"
        + _table(["Path", "Size"], folders)
        + "<h2>Largest files</h2>"
        + _table(["Path", "Size"], files)
    )
