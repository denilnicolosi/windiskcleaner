# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
