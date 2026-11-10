"""Turns a scan into recommendations: catalogue rules plus a few heuristics. No Qt here."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from diskdiet import actions
from diskdiet.rules import RULES, Action, Rule, Safety, question
from diskdiet.scanner import FileInfo, ScanResult, key, scan, under
from diskdiet.strings import pick

DAY = 86400
OLD_DAYS = 730
IDLE_PROJECT_DAYS = 180
IDLE_PROJECT_MIN = 50 << 20
ARCHIVE_MIN = 100 << 20
ORPHAN_MIN = 500 << 20

# Folder names that a build tool can recreate from the project's own files.
REGENERABLE = ("node_modules", ".venv", "venv", "target", "build", ".gradle")

VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".wav"}
VM_DISK = {".vmdk", ".vdi", ".vhd", ".iso", ".ova"}
PACKED = {".zip", ".rar", ".7z"}
INSTALLER = {".exe", ".msi", ".iso"}
# AppData folders that are Windows' own or hold many unrelated programs.
NOT_ORPHANS = {"microsoft", "packages", "programs", "temp", "google", "windowsapps", "npm"}


@dataclass
class Recommendation:
    id: str
    category: str
    safety: Safety
    action: Action
    title: str
    why: str
    size: int
    paths: list[str] = field(default_factory=list)
    commands: tuple = ()
    tool: str = ""
    permanent: bool = False
    question: str = ""  # asked for each item by the guided check
    expand: bool = False  # the guided check looks at what is inside `paths`
    process: str = ""  # program to close first (rules.Rule.process)


def measure(path: str, result: ScanResult | None = None) -> int:
    """Size of a file or directory, reusing the scan when it already knows."""
    if result is not None:
        k = key(path)
        if k in result.watched:
            return result.watched[k]
        node = result.find(path)
        if node is not None:
            return node.size
    try:
        if not os.path.isdir(path):
            return os.lstat(path).st_size
    except OSError:
        return 0
    return scan(path, max_depth=0).root.size


def _from_rule(rule: Rule, result: ScanResult) -> Recommendation | None:
    root = key(result.root.path)
    paths = [p for p in rule.resolve() if under(key(p), root)]  # only what was scanned
    size = sum(measure(p, result) for p in paths)
    if rule.paths and not size:
        return None  # nothing of this kind on this machine
    return Recommendation(
        rule.id, rule.category, rule.safety, rule.action, pick(rule.title), pick(rule.why),
        size, paths, rule.commands, rule.tool, rule.permanent,
        question=pick(question(rule.id)), expand=True, process=rule.process,
    )


def _in_user_docs(path: str) -> bool:
    """Inside the user's profile but not in AppData or a dot-folder: the user's own files."""
    profile = key(os.environ.get("USERPROFILE", os.path.expanduser("~")))
    k = key(path)
    if not under(k, profile):
        return False
    first = k[len(profile) + 1 :].split(os.sep)[0]
    return first != "appdata" and not first.startswith(".")


def _group(rec_id: str, category: str, safety: Safety, title, why, files: list[FileInfo]):
    if not files:
        return None
    files.sort(reverse=True)
    return Recommendation(
        rec_id, category, safety, Action.REVIEW, pick(title), pick(why),
        sum(f.size for f in files), [f.path for f in files],
        question=pick(question(rec_id)),
    )


def _archive(result: ScanResult, now: float, old_days: int) -> list[Recommendation | None]:
    twins, installers, videos, vms, old = [], [], [], [], []
    for f in result.big_files:
        if not _in_user_docs(f.path):
            continue
        stem, ext = os.path.splitext(f.path)
        ext = ext.lower()
        age_days = (now - f.mtime) / DAY
        if ext in PACKED and os.path.isdir(stem):
            twins.append(f)
        elif ext in INSTALLER and "downloads" in key(f.path).split(os.sep) and age_days > 90:
            installers.append(f)
        elif f.size < ARCHIVE_MIN:
            continue
        elif ext in VM_DISK:
            vms.append(f)
        elif ext in VIDEO:
            videos.append(f)
        elif age_days > old_days:
            old.append(f)
    return [
        _group(
            "archive_twins", "archive", Safety.CAUTION,
            ("Archives already extracted next to them", "Archivi già estratti accanto"),
            (
                "A folder with the same name sits beside each of these archives, so the "
                "content is probably stored twice. Check, then delete one of the two.",
                "Accanto a ognuno di questi archivi c'è una cartella con lo stesso nome, quindi "
                "il contenuto è probabilmente salvato due volte. Verifica, poi elimina uno dei due.",
            ),
            twins,
        ),
        _group(
            "old_installers", "archive", Safety.CAUTION,
            ("Old installers in Downloads", "Vecchi installer in Download"),
            (
                "Setup files downloaded more than three months ago. The programs are already "
                "installed and newer versions are online.",
                "File di installazione scaricati più di tre mesi fa. I programmi sono già "
                "installati e in rete ci sono versioni più recenti.",
            ),
            installers,
        ),
        _group(
            "archive_videos", "archive", Safety.ARCHIVE,
            ("Large videos and recordings", "Video e registrazioni grandi"),
            (
                "Big media files rarely need the speed of the system drive.",
                "I file multimediali grandi raramente hanno bisogno della velocità del disco "
                "di sistema.",
            ),
            videos,
        ),
        _group(
            "archive_vms", "archive", Safety.ARCHIVE,
            ("Virtual machines and disk images", "Macchine virtuali e immagini disco"),
            (
                "Move the whole virtual machine folder, then reopen it from its new place.",
                "Sposta l'intera cartella della macchina virtuale, poi riaprila dalla nuova "
                "posizione.",
            ),
            vms,
        ),
        _group(
            "archive_old", "archive", Safety.ARCHIVE,
            ("Large files not modified for two years", "File grandi non modificati da due anni"),
            (
                "Based on the modification date: Windows refreshes the access date too often "
                "for it to be meaningful.",
                "In base alla data di modifica: Windows aggiorna la data di accesso troppo "
                "spesso perché sia significativa.",
            ),
            old,
        ),
    ]


def _idle_projects(result: ScanResult, now: float) -> Recommendation | None:
    # ponytail: "idle" = nothing written inside the regenerable folder itself for 6 months.
    # Looking at the surrounding project's own files would be more exact.
    idle = [
        n for n in result.named
        if n.size >= IDLE_PROJECT_MIN and _in_user_docs(n.path)
        and (now - n.newest) / DAY > IDLE_PROJECT_DAYS
    ]
    if not idle:
        return None
    idle.sort(key=lambda n: -n.size)
    return Recommendation(
        "idle_projects", "projects", Safety.CAUTION, Action.REVIEW,
        pick(("Rebuildable folders in idle projects", "Cartelle rigenerabili in progetti fermi")),
        pick((
            "Dependencies and build output (node_modules, .venv, build…) untouched for six "
            "months. The project's own tools recreate them: npm install, uv sync, a new build.",
            "Dipendenze e output di build (node_modules, .venv, build…) non toccati da sei mesi. "
            "Gli strumenti del progetto li ricreano: npm install, uv sync, una nuova build.",
        )),
        sum(n.size for n in idle), [n.path for n in idle],
        question=pick(question("idle_projects")),
    )


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _orphans(result: ScanResult, programs: Iterable, covered: list[str]) -> Recommendation | None:
    names = [f"{p.name} {p.publisher}" for p in programs]
    if not names:
        return None  # nothing to compare against: every folder would look orphaned
    # Microsoft Store apps are not in the Uninstall registry: their package folders name them.
    store = result.find(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages"))
    names += [child.name for child in store.children] if store else []
    haystack = "|".join(_norm(n) for n in names)
    tokens = {t for n in names for t in re.split(r"[^a-z0-9]+", n.lower()) if len(t) >= 4}
    found = []
    for var in ("LOCALAPPDATA", "APPDATA"):
        base = result.find(os.environ.get(var, ""))
        for child in base.children if base else ():
            n = _norm(child.name)
            if child.size < ORPHAN_MIN or len(n) < 3 or child.name.lower() in NOT_ORPHANS:
                continue
            k = key(child.path)
            if any(c == k or under(c, k) for c in covered):
                continue  # a catalogue rule already explains this folder
            if n in haystack or any(t in n for t in tokens):
                continue
            found.append(child)
    if not found:
        return None
    found.sort(key=lambda n: -n.size)
    return Recommendation(
        "appdata_orphans", "apps", Safety.CAUTION, Action.REVIEW,
        pick(("AppData folders with no matching program", "Cartelle AppData senza programma")),
        pick((
            "No installed program with a similar name was found. They may be leftovers of "
            "uninstalled software, or belong to portable tools: check before deleting.",
            "Non è stato trovato un programma installato con nome simile. Possono essere "
            "residui di software disinstallato o appartenere a strumenti portable: verifica "
            "prima di eliminare.",
        )),
        sum(n.size for n in found), [n.path for n in found],
        question=pick(question("appdata_orphans")),
    )


def build(
    result: ScanResult,
    *,
    rules: Iterable[Rule] = RULES,
    programs: Iterable = (),
    now: float | None = None,
    old_days: int = OLD_DAYS,
    exclude: Iterable[str] = (),
) -> list[Recommendation]:
    """All recommendations for a scan, biggest first. Nothing under `exclude` is proposed."""
    now = time.time() if now is None else now
    recs = [_from_rule(rule, result) for rule in rules]
    covered = [key(p) for r in recs if r for p in r.paths]
    recs += _archive(result, now, old_days)
    recs += [_idle_projects(result, now), _orphans(result, programs, covered)]
    keys = [key(p) for p in exclude]
    recs = [_without(r, keys, result) for r in recs if r]
    return sorted((r for r in recs if r), key=lambda r: -r.size)


def _without(rec: Recommendation, keys: list[str], result: ScanResult) -> Recommendation | None:
    """`rec` minus the paths the user excluded; None if nothing is left of it."""
    kept = [p for p in rec.paths if not actions.excluded_hit(key(p), keys)]
    if len(kept) == len(rec.paths):
        return rec
    if not kept:
        return None
    rec.paths, rec.size = kept, sum(measure(p, result) for p in kept)
    return rec


def review_items(rec: Recommendation, result: ScanResult | None = None) -> list[FileInfo]:
    """What the guided check asks about, biggest first: the items themselves, or for a
    catalogue folder (rec.expand) what it contains."""
    targets = actions.preview(rec.paths) if rec.expand else rec.paths
    items = []
    for path in targets:
        try:
            mtime = os.lstat(path).st_mtime
        except OSError:
            continue  # gone since the scan
        node = result.find(path) if result is not None else None
        if node is not None and node.newest:
            mtime = node.newest  # last write inside a folder, not the folder's own date
        items.append(FileInfo(measure(path, result), mtime, path))
    return sorted(items, reverse=True)
