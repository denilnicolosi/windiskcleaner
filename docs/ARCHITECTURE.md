# Architecture

```
            scanner.scan(root, watch_paths, watch_names)
                         │  ScanResult (size tree, files >= 1 MB, watched sizes)
        ┌────────────────┼──────────────────┬──────────────┐
        ▼                ▼                  ▼              ▼
 advisor.build     duplicates.find     vhdx.find     report.to_dict
 (rules.RULES +    (on request)
  heuristics)
        │  list[Recommendation]
        ▼
   ui/main_window ──(preview + confirmation)──► actions.delete / open / launch
```

## One pass over the disk

`scanner.scan` walks the tree once with `os.scandir` (on Windows the directory listing
already carries size, dates and attributes, so there is no extra call per file).

The walk has no threads, on purpose. A thread-pool version was measured on a 360 GB
drive: 105 s with one thread, 867 s with two, 586 s with six. Millions of very short
calls make Python threads fight over the interpreter lock. A faster scan would need
processes or native code (reading the NTFS file table directly is what the fastest
tools do, and needs administrator rights).

Processes do help: `scan(workers=N)` lets the parent walk the top three levels, hands the
folders below to worker processes and walks the top again with their results. On a 374 GB
drive (2.2 M files, 6 cores, SSD) that took 48 s with four processes against 80 s with
one; eight were no faster. The window uses it for whole drives only (starting the
processes costs about a second), and `--workers` does for the headless report.

- Folder nodes are kept down to `max_depth` (6) for the pie chart; deeper sizes are rolled
  up into their ancestor.
- `watch_paths` — the folders the rule catalogue cares about — get their size recorded even
  when they are deeper than that.
- `watch_names` — `node_modules`, `.venv`… — every occurrence is recorded (not nested ones).
- Every file of 1 MB or more is kept in `big_files`. The largest/old file tables, the
  archive heuristics, the duplicate finder and the virtual disk list all read that one
  list, so nothing scans the disk a second time.
- Junctions and symlinks are skipped; OneDrive placeholders that are not on disk are
  counted apart; unreadable items are counted and shown as "not scanned".

Sizes are logical sizes, like Explorer's "Size". Hard-linked files (most of WinSxS) are
counted once per name, so that folder looks bigger than the space it really takes.

## Recommendations

`advisor.build` produces one `Recommendation` per catalogue rule present on the machine,
plus heuristics that need the scan: archives extracted beside themselves, old installers,
large videos, virtual machines, large files untouched for two years, rebuildable folders
in idle projects, AppData folders with no matching installed program.

A recommendation has a safety level and an action:

| Safety | Action | UI behaviour |
|---|---|---|
| `SAFE` | `DELETE` | checkbox, preview, confirmation, `actions.delete` |
| `CAUTION` | `REVIEW` | guided check: a question per item, then one confirmation |
| `CAUTION` / `SYSTEM` | `GUIDE` | explanation, command buttons, open Windows tool |
| `ARCHIVE` | `REVIEW` | guided check with "move to another drive" |

The guided check (`ui/review_dialog.py`) only collects choices; nothing happens until the
summary page is confirmed. `advisor.review_items` decides what is asked about.

## The deletion path

`actions.delete(items, roots, permanent=False)`:

1. each item must be strictly inside one of `roots` (or be a root that is a file);
2. `is_protected` must be false (Windows except `Temp`, Program Files, drive roots, the
   profile folder itself, other users' profiles);
3. the exe's own unpacked runtime in `%TEMP%` is skipped;
4. Recycle Bin by default (`QFile.moveToTrash`), permanent only for temporary files;
5. failures and files in use are collected in the returned `Report`, never forced.

## Moving, logging, restoring

`actions.move` copies to `<drive>\WinDiskCleaner-Archive\<original path>`, compares size and
file count, and only then removes the original.

`journal.py` appends one line per removed item to `%LOCALAPPDATA%\WinDiskCleaner\deleted.jsonl`
(original path, size, mode, where it is now). For the Recycle Bin the location comes from
`QFile(path).moveToTrash()`: the *instance* method renames the `QFile` to its `$R…` path in
the bin, while the static one reports nothing. `actions.restore` moves the item back and
drops the matching `$I…` record so the bin shows no ghost. It refuses when the original
place is occupied or the item is gone.

## Commands

A `rules.Command` is an argument tuple. `ui/terminal.py` starts it with `QProcess`
(no shell) and streams the output. Commands marked `admin` need an elevated WinDiskCleaner,
because the output of a separately elevated process cannot be captured; the window
offers `actions.relaunch_elevated` instead.

## Updates

`updates.latest` reads the latest GitHub release; `download` accepts only URLs under this
repository's release downloads and checks the SHA-256 published beside the exe; `swap`
renames the running exe to `*.old` (Windows allows renaming, not deleting, a running
exe), puts the new one in place and starts it. `cleanup` removes the `.old` at the next
start. From a source checkout the button just opens the release page.

## Terminal output

Tools such as `ollama` redraw spinners and progress bars with escape sequences.
`terminal.plain` turns "go to column 1" and "erase line" into a carriage return and drops
every other sequence; `Terminal.write` then replaces the current line after a lone `\r`
instead of appending. A `Terminal` runs a queue of commands and stops at the first that
fails: that is how a restore point is created before a system command.

## Logging

`log.setup()` (called by the window, not by tests) writes `windiskcleaner.log` next to the
settings: 1 MB, two older files kept. See CLAUDE.md for what is recorded.

## Threads

The UI runs scans, duplicate searches and deletions in a `Worker(QThread)`, which calls a
plain function with `progress` and `cancelled` callbacks. The core knows nothing about Qt.

## Packaging

`scripts/build.ps1` runs PyInstaller `--onefile --windowed`. Only `PySide6-Essentials` is
a dependency: the pie chart is drawn with `QPainter` rather than QtCharts to keep the exe
small. A one-file exe unpacks itself into `%TEMP%` at each start; that is why
`actions.delete` protects `sys._MEIPASS`.

## Known limits

- Without administrator rights some system folders cannot be read; their space appears as
  "not scanned".
- "Old" is judged by modification date only.
- The idle-project and orphan-folder heuristics are approximate and therefore `CAUTION`.
- A virtual disk's really used space is not readable from outside, so the gain from
  compaction cannot be predicted.
- The journal has one line per removed item (a file or a top-level folder), not one per
  file inside a folder.
- Parallel hashing helps on SSDs; on a spinning disk it gains little.
- The self-update path has unit tests but has not been exercised against a real
  published release yet.
