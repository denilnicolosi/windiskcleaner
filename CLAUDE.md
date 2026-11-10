# WinDiskCleaner — guide for coding agents

Portable Windows disk space analyzer with explained, safe cleanup. Python 3.11+, PySide6
(Essentials only), packaged as a one-file exe with PyInstaller. Windows only.

## Commands

```
uv sync                      # install
uv run python -m windiskcleaner    # run the window
uv run pytest                # tests (seconds; if they take minutes, something scans the real disk)
uv run ruff check            # lint
pwsh scripts/build.ps1       # dist/WinDiskCleaner.exe
uv run python scripts/make_icon.py        # assets/windiskcleaner.ico, after changing ui/icon.py
uv run python scripts/make_screenshot.py  # docs/screenshot.png (sample data, no real paths)
uv run python -m windiskcleaner --report json --root C:\ --out report.json   # headless, read-only
```

## Map

| File | Role |
|---|---|
| `src/windiskcleaner/scanner.py` | Walks a folder (one thread, on purpose): size tree, files >= 1 MB, watched paths/names. |
| `src/windiskcleaner/log.py` | Log file of operations and errors (`windiskcleaner.log`). |
| `src/windiskcleaner/rules.py` | Catalogue of known space hogs. **Data only.** |
| `src/windiskcleaner/advisor.py` | Scan + rules + heuristics -> `Recommendation` list. |
| `src/windiskcleaner/actions.py` | **The only module that deletes or launches anything.** |
| `src/windiskcleaner/journal.py` | Log of removed/moved items (`deleted.jsonl`). Records only. |
| `src/windiskcleaner/history.py` | Summaries of past scans (`history.jsonl`) and what grew since the last one. Records only. |
| `src/windiskcleaner/settings.py` | Preferences in `%LOCALAPPDATA%\WinDiskCleaner\settings.json`. |
| `src/windiskcleaner/updates.py` | Update check/download from GitHub Releases. **The only network code.** |
| `src/windiskcleaner/duplicates.py` | Duplicate finder (size -> 64 KB hash -> full hash), thread pool. |
| `src/windiskcleaner/vhdx.py` | Docker/WSL virtual disk compaction; the only elevation (UAC). |
| `src/windiskcleaner/compress.py` | NTFS compression: candidates, estimate, size on disk (read-only; `actions.compress` runs compact.exe). |
| `src/windiskcleaner/system.py` | Drives, installed programs (read-only). |
| `src/windiskcleaner/games.py` | Steam and Epic games with size and last played (read-only). |
| `src/windiskcleaner/winapp2.py` | Reads a user-imported winapp2.ini; its folders are only guided-check suggestions. |
| `src/windiskcleaner/report.py` | JSON / HTML export. |
| `src/windiskcleaner/strings.py` | UI strings `(english, italian)`, `tr()`, `fmt_size()`. |
| `src/windiskcleaner/ui/` | Qt: `main_window`, `tabs`, `more_tabs` (compress, what changed, file types, games), `pie`, `review_dialog` (guided check), `terminal` (runs commands), `settings_dialog`, `icon`, `widgets`. Thin: no decisions here. |

More in `docs/ARCHITECTURE.md`. Adding a rule: `docs/RULES.md`. Releasing: `docs/RELEASING.md`.

## Invariants — do not break

1. **Core is Qt-free.** Only `ui/` imports PySide6 at module level (`actions._qt_trash`
   imports it lazily). The core must stay testable and usable headless.
2. **Removal happens only in `actions.delete` and `actions.move`.** They re-check every
   item against the never-touch list (`actions.is_protected`) right before acting, and
   write every removed item to the journal. Never call `os.remove`/`shutil.rmtree`
   elsewhere in `src/` (exception: `updates.swap`/`cleanup` on WinDiskCleaner's own exe).
3. **Nothing is removed without a preview and an explicit confirmation in the UI.**
   Default is the Recycle Bin; `permanent=True` is for the `temp` category only.
4. **Commands run only on the user's click, only from the catalogue.** A `rules.Command`
   is an argument tuple started with `QProcess` (no shell, no string concatenation).
   User-typed values go through `Command.build`, which accepts plain names only.
   `changes=True` commands are confirmed first; `admin=True` ones require an elevated
   WinDiskCleaner (`actions.relaunch_elevated`, user-initiated). Never auto-run a command.
5. **No telemetry. The only network access is `updates.py`**: anonymous GETs to this
   repository's GitHub Releases, switchable off in Settings. `updates.download` must
   keep checking the URL prefix and the SHA-256. Tests never touch the network.
6. **Every rule and heuristic has a test.** Every user-visible string has both languages.
7. **Use the modification date, not the access date**, for "old" files: Windows refreshes
   access times constantly.
8. Rules only apply to paths inside the scanned root (keeps tests off the real disk).
9. Tests never write to the real `%LOCALAPPDATA%\WinDiskCleaner`: `conftest.py` points
   `WINDISKCLEANER_HOME` at a temporary folder. Keep that fixture autouse.
10. Do not name a method `finished` (or another Qt signal name) on a `QDialog` subclass:
    it shadows the signal and slots silently stop firing.
11. Terminal output goes through `terminal.plain()` (escape sequences out, redraws as
    carriage returns). Do not append raw process output to the widget.
12. Commands that change Windows itself (`admin=True` and `changes=True`) offer a restore
    point first (`rules.RESTORE_POINT`); keep that checkbox.
13. Do not make the scan multi-threaded: it was measured 5-8 times slower (numbers in
    `scanner.py`). Threads do help the duplicate finder, which reads large files.

## Working on this repo — safety for the agent itself

- **Never run a real cleanup on the developer's machine** (delete, move, Recycle Bin,
  emptying the bin, vhdx compaction, NTFS compression, cache purge, uninstall, `changes=True` commands,
  elevated restart, exe self-update) to "verify" a change, unless the user explicitly
  confirms that specific action in the conversation. Test destructive code on `tmp_path`
  only. One test sends a tiny file of its own to the real Recycle Bin and restores it.
- Scanning and `--report` are read-only and fine to run.
- Tests must not write large files: patch the thresholds in `advisor` instead.

## Reading what happened on the user's machine

Between sessions, look here before asking the user what went wrong:

| File (in `%LOCALAPPDATA%\WinDiskCleaner`) | Content |
|---|---|
| `windiskcleaner.log` (+ `.1`, `.2`) | Start/exit, scans (size, time, unreadable items), every delete/move with totals, each skipped item and why, commands run with exit code and the tail of their output, update checks, tracebacks of failed jobs and crashes. |
| `deleted.jsonl` | One JSON line per removed or moved item: original path, size, mode, where it is now, state. |
| `settings.json` | Current preferences. |
| `history.jsonl` | Folder sizes of the last scans of each root (for “What changed”). |

```
Select-String -Path "$env:LOCALAPPDATA\WinDiskCleaner\windiskcleaner.log" -Pattern 'ERROR|CRITICAL|WARNING' | Select-Object -Last 40
Get-Content "$env:LOCALAPPDATA\WinDiskCleaner\windiskcleaner.log" -Tail 80
```

Everything logs through `windiskcleaner.log.logger`. New operations that change the machine
must log their outcome; failures must log the reason. The files stay on the machine and
contain paths: read them, do not paste them into issues or commits.

## Conventions

- Ruff, line length 100 (prose-heavy files are exempt, see `pyproject.toml`).
- Simplifications with a known ceiling are marked with a `ponytail:` comment.
- Version lives only in `pyproject.toml`; `CHANGELOG.md` follows Keep a Changelog.
- Commit messages: imperative, one logical change each.
