# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-11-11

### Added

- Rules for leftover update installers (Electron `*-updater`, Squirrel `.nupkg`, Docker
  Desktop), graphics shader caches (NVIDIA, AMD, Intel, DirectX), Google Earth cache, new
  Teams cache, Opera cache.
- Browser caches now include service-worker caches, shader caches, downloaded components
  and crash reports; VS Code caches include the C/C++ IntelliSense cache; crash dumps include
  Crashpad reports of Electron apps and Windows Error Reporting.
- Guidance for classic Teams leftovers, Python versions, Azure Functions Core Tools
  versions, Clipchamp, Dart/Flutter pub cache and the pnpm store.
- Warning before cleaning when the program that owns the files is still open.
- Exclusions (Settings, or right-click a folder): WinDiskCleaner never proposes, removes or moves
  what is listed there, nor anything inside it.
- “Clean everything safe” ticks every safe item and opens the usual preview.
- “Undo last cleanup” in the Log tab puts back everything of the latest cleanup.
- Compress tab: transparent NTFS compression (XPRESS / LZX, like `compact.exe`) of
  programs, SDKs and other folders that are read but rarely written, with an estimate of
  the saving. Nothing is deleted; Decompress or the Log tab undoes it.
- “What changed” tab: compares each scan with the previous scan of the same folder and
  lists the folders where the space went (or came back).
- “Find leftovers” in the Programs tab: after an uninstall, looks in AppData, LocalLow and
  ProgramData for folders the program left behind and opens the guided check. Folders
  that also fit a program still installed are never proposed.
- “File types” tab: space by kind of file (video, images, programs…) and by extension.
- Filter box on the file and program tables: words, and sizes such as `>500mb`; the file
  tables now search every tracked file, not only the first 200 shown.
- Right-click a folder → “Scan this folder again” to refresh it without a full scan.
- Caches of Electron and WebView2 apps (WhatsApp, Discord, Postman, VS Code forks…),
  recognised by their folder layout; only caches, never the apps' own data.
- Old versions that self-updating programs keep beside the new one (Squirrel `app-*`
  folders, past JetBrains IDE versions); the newest is never proposed.
- Guidance for Telegram and WhatsApp media, OneDrive files kept on this PC (free up space,
  Storage Sense), the Delivery Optimization cache and Windows' reserved storage.
- Games tab (shown when Steam or Epic games are installed): size and last time played,
  uninstall through the launcher, open, compress.
- CSV export (File menu and `--report csv`): every folder and tracked file with size,
  file count and date, ready for Excel.
- Import a winapp2.ini (Settings → Exclusions): its whole-folder rules become suggestions
  for the guided check, never a one-click cleanup. WinDiskCleaner does not download it.
- After a cleanup, “Free now” permanently deletes from the Recycle Bin only what that cleanup
  put there, after asking.
- Treemap view in the Overview (button next to the path): every subfolder as a box sized
  by its space, with its own subfolders inside; click to enter, right-click for actions.

### Changed

- Scanning a whole drive uses up to four processes: about 1.6 times faster on an SSD
  (80 s to 48 s on a 374 GB drive). `--workers N` does the same for `--report`.
- Renamed from DiskDiet to WinDiskCleaner, because a Mac app already uses that name. The
  data folder `%LOCALAPPDATA%\DiskDiet` moves to `%LOCALAPPDATA%\WinDiskCleaner` at the first
  start. Version 0.1.0 cannot update itself to this one: download the new exe once.
- The uv cache is cleaned with uv's own commands: its folders are too big for the Recycle
  Bin. Squirrel `.nupkg` packages now go through the guided check.
- Reports say why an item could not go to the Recycle Bin, and the log keeps the first 25
  skipped items of an operation. The log of removed items is capped at 20,000 entries.
- Rebuildable project folders cover more tools (.next, .nuxt, .tox, .dart_tool, Rust
  `target`, .NET `bin`/`obj`, caches of pytest, mypy, ruff…) and generic names such as
  `build` or `bin` count only when the project file is beside them.
- The guided check shows the last write inside a folder, not the folder's own date.

### Fixed

- Rule wildcards no longer follow junctions such as `Dati applicazioni` on Italian
  Windows, which would have counted folders twice.
- Moving to another drive no longer fails when the archive path exceeds 260 characters.
- Uninstall, Find leftovers and the games' Uninstall no longer crash.
- A file with a date before 1970, or a damaged Steam, Epic or history file, no longer stops
  the end of a scan.
- An exclusion inside a folder spares only that item instead of hiding the whole advice.
- Find leftovers no longer proposes folders of an installed program named after its
  publisher; winapp2 entries without RECURSE no longer propose the whole folder.
- “What changed” survives a change of settings instead of comparing a scan with itself.
- Cancel now stops clean-ups and compression; closing the window waits for them. Only one
  operation runs at a time.
- “Undo last cleanup” rewrites the log once, not once per item, and shows progress.
- A compression that saves nothing is reported as such and not recorded.
- Duplicates that could not be removed stay in the list.
- Going up in the Overview while a folder is being removed no longer breaks the totals.
- Every table and list fits its columns to their content, header included: no more
  resizing by hand. One column (path or name) takes the remaining width; text that does not
  fit shows whole in a tooltip.
- Every date is shown as DD-MM-YYYY (with the time where there is one), also in the CSV
  export. The JSON report and the program's own files keep ISO dates.
- Windows replaced after a change of language, settings or exclusions are released instead
  of keeping a whole scan in memory.

## [0.1.0] - 2026-11-10

### Added

- Disk scan with clickable, labelled pie chart and folder drill-down; right-click a
  folder to open it or send it to the Recycle Bin.
- Advice from a catalogue of known space hogs: temporary files, browser caches, pip / uv /
  npm / Yarn caches, VS Code and JetBrains leftovers, Gradle, Android SDK and emulators,
  Ollama, LM Studio, Docker, NVIDIA, Arduino.
- Safe cleanup with preview and confirmation, to the Recycle Bin (temporary files are
  deleted permanently).
- Guided check for everything that needs a decision: one question per item, then one
  confirmation.
- Windows items (hibernation file, page file, WinSxS, Windows Update leftovers, Recycle
  Bin, restore points, Storage Sense) and tool caches (Docker, Ollama, nvm, conda) with
  buttons that run the official commands in a built-in terminal.
- Restart as administrator button.
- Largest files and old files (by modification date).
- Installed programs by size, with Uninstall.
- Archive candidates that can be moved to another drive (copy, verify, remove): large
  videos, virtual machines, old
  installers, archives already extracted, large files untouched for two years.
- Rebuildable folders in idle projects and AppData folders with no matching program.
- Duplicate finder by content, hashed in parallel.
- Log of deleted and moved files with Restore; summary on exit of what is waiting in the
  Recycle Bin.
- Settings: theme, language, thresholds. Update check against GitHub Releases with
  download, SHA-256 verification and in-place replacement of the exe.
- Application icon.
- Progress bar for scans, duplicate search and clean-ups.
- Restore point offered before commands that change Windows.
- Log file of operations and errors.
- Guided compaction of Docker and WSL virtual disks.
- JSON and HTML report, also headless with `--report`.
- English and Italian interface.
