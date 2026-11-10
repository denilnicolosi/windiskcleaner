# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
- Exclusions (Settings, or right-click a folder): DiskDiet never proposes, removes or moves
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
- Treemap view in the Overview (button next to the path): every subfolder as a box sized
  by its space, with its own subfolders inside; click to enter, right-click for actions.

### Changed

- Rebuildable project folders cover more tools (.next, .nuxt, .tox, .dart_tool, Rust
  `target`, .NET `bin`/`obj`, caches of pytest, mypy, ruff…) and generic names such as
  `build` or `bin` count only when the project file is beside them.
- The guided check shows the last write inside a folder, not the folder's own date.

### Fixed

- Rule wildcards no longer follow junctions such as `Dati applicazioni` on Italian
  Windows, which would have counted folders twice.
- Moving to another drive no longer fails when the archive path exceeds 260 characters.

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
