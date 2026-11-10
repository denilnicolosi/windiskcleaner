# Builds dist/DiskDiet.exe. Used locally and by both GitHub workflows.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

uv run pyinstaller --noconfirm --clean --onefile --windowed `
    --name DiskDiet `
    --icon assets/diskdiet.ico `
    --copy-metadata diskdiet `
    --exclude-module PySide6.QtNetwork `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtQuick `
    scripts/entry.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$exe = Get-Item dist/DiskDiet.exe
"{0}  {1:N1} MB" -f $exe.FullName, ($exe.Length / 1MB)
