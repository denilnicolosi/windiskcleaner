"""Turns a scan into recommendations: catalogue rules plus a few heuristics. No Qt here."""

from __future__ import annotations

import glob
import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from windiskcleaner import actions, winapp2
from windiskcleaner.rules import RULES, Action, Rule, Safety, question
from windiskcleaner.scanner import FileInfo, ScanResult, key, scan, under
from windiskcleaner.strings import pick

DAY = 86400
OLD_DAYS = 730
IDLE_PROJECT_DAYS = 180
IDLE_PROJECT_MIN = 50 << 20
ARCHIVE_MIN = 100 << 20
ORPHAN_MIN = 500 << 20

# Folder names that a build tool can recreate from the project's own files.
# Rebuildable folder -> files that must sit next to it for it to be a project's build output
# (glob patterns). () = the name alone is proof. Generic names like "build" or "bin" need a
# marker: without one they may be the user's own folders.
_JS = ("package.json",)
_PY = ("pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "Pipfile", "uv.lock")
_GRADLE = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")
_DOTNET = ("*.csproj", "*.fsproj", "*.vbproj", "*.sln")
MARKERS: dict[str, tuple[str, ...]] = {
    "node_modules": (), ".next": _JS, ".nuxt": _JS, ".svelte-kit": _JS, ".turbo": _JS,
    ".angular": ("angular.json",), ".parcel-cache": (), "dist": _JS + _PY,
    ".venv": (), "venv": _PY, ".tox": ("tox.ini",) + _PY, ".nox": ("noxfile.py",),
    ".pytest_cache": (), ".mypy_cache": (), ".ruff_cache": (), "__pycache__": (),
    "target": ("Cargo.toml", "pom.xml"),
    "build": _GRADLE + _JS + _PY + ("CMakeLists.txt", "pubspec.yaml", "meson.build"),
    ".gradle": _GRADLE, ".dart_tool": ("pubspec.yaml",), ".cxx": _GRADLE,
    "bin": _DOTNET, "obj": _DOTNET,
}
# ponytail: the scanner stops looking for names inside a matched folder, so a project kept
# inside a plain folder called "build" or "bin" (no marker) is not seen. Rare; pass the
# markers to the scanner if it shows up.
REGENERABLE = tuple(MARKERS)

VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".wav"}
VM_DISK = {".vmdk", ".vdi", ".vhd", ".iso", ".ova"}
PACKED = {".zip", ".rar", ".7z"}
INSTALLER = {".exe", ".msi", ".iso"}
# Broad kind of a file by extension, for the "File types" view.
KINDS: dict[str, set[str]] = {
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv", ".ts", ".mts"},
    "audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic",
              ".raw", ".cr2", ".nef", ".arw", ".dng", ".psd", ".svg"},
    "archive": {".zip", ".rar", ".7z", ".gz", ".tar", ".xz", ".bz2", ".zst", ".cab", ".tgz"},
    "disk": {".iso", ".vhdx", ".vhd", ".vmdk", ".vdi", ".img", ".ova", ".qcow2", ".wim"},
    "program": {".exe", ".dll", ".sys", ".msi", ".so", ".pyd", ".node", ".jar", ".apk"},
    "document": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".txt",
                 ".rtf", ".epub", ".md", ".csv"},
    "data": {".db", ".sqlite", ".mdb", ".accdb", ".ldb", ".pst", ".ost", ".bak", ".log",
             ".dat", ".bin", ".pak", ".gguf", ".safetensors", ".ckpt", ".pt", ".onnx"},
    "code": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".json",
             ".xml", ".html", ".css", ".pyc", ".class", ".map"},
}


def kind_of(ext: str) -> str:
    return next((k for k, exts in KINDS.items() if ext.lower() in exts), "other")
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


def is_build_output(path: str) -> bool:
    """The folder's name is a known build/dependency folder and its project file is beside it."""
    markers = MARKERS.get(os.path.basename(path).lower())
    if markers is None:
        return False
    parent = os.path.dirname(path)
    return not markers or any(glob.glob(os.path.join(glob.escape(parent), m)) for m in markers)


def _idle_projects(result: ScanResult, now: float) -> Recommendation | None:
    # ponytail: "idle" = nothing written inside the regenerable folder itself for 6 months.
    # Looking at the surrounding project's own files would be more exact.
    idle = [
        n for n in result.named
        if n.size >= IDLE_PROJECT_MIN and _in_user_docs(n.path)
        and (now - n.newest) / DAY > IDLE_PROJECT_DAYS and is_build_output(n.path)
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


def _appdata_nodes(result: ScanResult, levels: int):
    """Nodes of the scan tree up to `levels` below %LOCALAPPDATA% and %APPDATA%."""
    for var in ("LOCALAPPDATA", "APPDATA"):
        base = result.find(os.environ.get(var, "") or "\0")
        stack = [(base, 0)] if base else []
        while stack:
            node, depth = stack.pop()
            yield node
            if depth < levels:
                stack += [(child, depth + 1) for child in node.children]


def _subdirs(path: str) -> list[str]:
    """Names of the folders directly in `path`, read from disk: when the whole drive is
    scanned, the tree keeps only six levels and AppData sits at level four."""
    try:
        with os.scandir(path) as entries:
            return [e.name for e in entries if e.is_dir(follow_symlinks=False)]
    except OSError:
        return []


# Inside a Chromium-style profile (Electron apps, WebView2): caches only, never site data.
_APP_CACHES = ("Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
               "DawnWebGPUCache", "GrShaderCache", "GraphiteDawnCache", "ShaderCache",
               r"Service Worker\CacheStorage", r"Service Worker\ScriptCache",
               r"Crashpad\reports")


def _app_caches(result: ScanResult, covered: list[str]) -> Recommendation | None:
    """Web caches of Electron and WebView2 apps (Discord, WhatsApp, VS Code forks, new
    Outlook…), recognised by their layout rather than by name: a folder holding both
    "Code Cache" and "Cache" or "GPUCache"."""
    found = []
    for node in _appdata_nodes(result, 3):
        names = {name.lower() for name in _subdirs(node.path)}
        if "code cache" not in names or not names & {"cache", "gpucache"}:
            continue
        for sub in _APP_CACHES:
            path = os.path.join(node.path, sub)
            k = key(path)
            if os.path.isdir(path) and not any(c == k or under(k, c) or under(c, k)
                                               for c in covered):
                found.append(path)
    sizes = {p: measure(p, result) for p in found}
    found = [p for p in found if sizes[p]]
    if not found:
        return None
    found.sort(key=lambda p: -sizes[p])
    return Recommendation(
        "app_caches", "apps", Safety.SAFE, Action.DELETE,
        pick(("Caches of desktop apps (Electron, WebView2)",
              "Cache delle app desktop (Electron, WebView2)")),
        pick((
            "Many desktop apps are web pages in a frame (Discord, WhatsApp, Teams, Postman, "
            "VS Code forks…) and keep the same caches as a browser. Rebuilt at the next "
            "start; chats, logins and settings are not touched. Close those apps first: "
            "files in use are skipped.",
            "Molte app desktop sono pagine web in una cornice (Discord, WhatsApp, Teams, "
            "Postman, fork di VS Code…) e tengono le stesse cache di un browser. Si ricreano "
            "al prossimo avvio; chat, accessi e impostazioni non vengono toccati. Chiudi prima "
            "quelle app: i file in uso vengono saltati.",
        )),
        sum(sizes[p] for p in found), found, question=pick(question("app_caches")), expand=True,
    )


_SQUIRREL = re.compile(r"^app-(\d+(?:\.\d+)*)$", re.IGNORECASE)
_JETBRAINS = re.compile(r"^([A-Za-z]+?)(\d{4})\.(\d+)$")


def _old_versions(result: ScanResult) -> Recommendation | None:
    """Older side-by-side versions a program keeps after updating itself: Squirrel apps
    (`app-1.2.3` folders next to Update.exe) and JetBrains IDE folders of past years."""
    old = []
    for node in _appdata_nodes(result, 2):
        groups: dict[str, list[tuple[tuple[int, ...], str]]] = {}
        # Squirrel keeps Update.exe beside the versions; some apps a launcher named after
        # the folder (Gemini\Gemini.exe) instead.
        launcher = any(os.path.isfile(os.path.join(node.path, exe))
                       for exe in ("Update.exe", node.name + ".exe"))
        if launcher:
            for name in _subdirs(node.path):
                match = _SQUIRREL.match(name)
                if match:
                    version = tuple(int(n) for n in match[1].split("."))
                    groups.setdefault("squirrel", []).append(
                        (version, os.path.join(node.path, name)))
        if node.name.lower() == "jetbrains":
            for name in _subdirs(node.path):
                match = _JETBRAINS.match(name)
                if match:
                    version = (int(match[2]), int(match[3]))
                    groups.setdefault(match[1].lower(), []).append(
                        (version, os.path.join(node.path, name)))
        for versions in groups.values():
            versions.sort()
            old += [path for _v, path in versions[:-1]]  # the newest stays
    if not old:
        return None
    sizes = {p: measure(p, result) for p in old}
    old.sort(key=lambda p: -sizes[p])
    return Recommendation(
        "old_versions", "apps", Safety.CAUTION, Action.REVIEW,
        pick(("Old versions kept after updates", "Versioni vecchie tenute dopo gli aggiornamenti")),
        pick((
            "Some programs install each update next to the previous one (Squirrel apps such "
            "as Discord or Postman) or leave the settings of past IDE versions (JetBrains). "
            "The newest version is never proposed. Close the program first.",
            "Alcuni programmi installano ogni aggiornamento accanto al precedente (app "
            "Squirrel come Discord o Postman) o lasciano le impostazioni delle versioni "
            "passate dell'IDE (JetBrains). La versione più recente non viene mai proposta. "
            "Chiudi prima il programma.",
        )),
        sum(sizes.values()), old, question=pick(question("old_versions")),
    )


def _community(result: ScanResult, covered: list[str]) -> Recommendation | None:
    """Folders from an imported winapp2.ini: suggestions to check one by one."""
    root = key(result.root.path)
    windir = key(os.environ.get("WINDIR", r"C:\Windows"))
    found = []
    for _name, folder in winapp2.load():
        k = key(folder)
        if not under(k, root) or under(k, windir) or actions.is_protected(folder, ()):
            continue
        if any(c == k or under(k, c) or under(c, k) for c in covered):
            continue  # the catalogue already explains it, with a better text
        found.append(folder)
    sizes = {p: measure(p, result) for p in dict.fromkeys(found)}
    found = sorted((p for p in sizes if sizes[p]), key=lambda p: -sizes[p])
    if not found:
        return None
    return Recommendation(
        "winapp2", "apps", Safety.CAUTION, Action.REVIEW,
        pick(("Community cleaning rules (winapp2.ini)", "Regole della community (winapp2.ini)")),
        pick((
            "Folders that the winapp2.ini you imported describes as caches, logs or temporary "
            "files. Those rules are written by volunteers and not checked by WinDiskCleaner: look "
            "at each folder before deleting it, and close its program first.",
            "Cartelle che il winapp2.ini importato descrive come cache, log o file temporanei. "
            "Quelle regole sono scritte da volontari e non sono verificate da WinDiskCleaner: guarda "
            "ogni cartella prima di eliminarla e chiudi prima il suo programma.",
        )),
        sum(sizes[p] for p in found), found, question=pick(question("winapp2")),
    )


# Words that say nothing about which program a folder belongs to.
_FILLER = {"x64", "x86", "64bit", "32bit", "bit", "version", "for", "windows", "the", "and",
           "edition", "update", "setup", "installer", "portable", "beta", "preview"}


def _core(name: str) -> str:
    """Program name without versions, architecture and filler: "Postman x64 9.31.0" -> postman."""
    name = re.sub(r"\(.*?\)", " ", name.lower())
    words = [w for w in re.split(r"[^a-z0-9]+", name) if w and w not in _FILLER
             and not any(c.isdigit() for c in w)]
    return "".join(words)


def _belongs(folder: str, core: str) -> bool:
    n = _norm(folder)
    if len(n) < 4 or len(core) < 4:
        return False
    return n == core or core.startswith(n) and len(n) >= 5 or n.startswith(core)


def leftovers(program, installed: Iterable, exclude: Iterable[str] = ()) -> Recommendation | None:
    """Folders a removed program left in AppData, LocalLow and ProgramData (Revo-style).

    Only call it once the program is gone from `installed`: before that the folders are its
    live data. A folder that also fits a program still installed is never proposed.
    """
    core = _core(program.name)
    others = [_core(p.name) for p in installed if p.name != program.name]
    # Another version is still installed (PyCharm 2025.1 removed, 2025.2 kept): only
    # folders carrying the removed version's own number qualify.
    version = "".join(re.findall(r"\d+", program.name)) if core in others else ""
    publisher = _norm(program.publisher.split()[0]) if program.publisher.split() else ""
    profile = os.environ.get("USERPROFILE", "")
    bases = [os.environ.get(v, "") for v in ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA")]
    bases += [os.path.join(profile, "AppData", "LocalLow")] if profile else []
    bases = [b for b in bases if b and os.path.isdir(b)]
    found: list[str] = []

    # "Microsoft Teams classic" also matches a folder called "Teams".
    cores = {core, core[len(publisher):]} if publisher and core.startswith(publisher) else {core}

    def consider(path: str) -> None:
        name = os.path.basename(path)
        if not any(_belongs(name, c) for c in cores):
            return
        if any(_belongs(name, o) for o in others if o != core):
            return
        if core in others and (not version or "".join(re.findall(r"\d+", name)) != version):
            return
        found.append(path)

    def folders(path: str) -> list[os.DirEntry]:
        try:
            with os.scandir(path) as entries:
                return [e for e in entries if e.is_dir(follow_symlinks=False)
                        and not e.is_symlink()]
        except OSError:
            return []

    for base in bases:
        for entry in folders(base):
            if len(publisher) >= 4 and _norm(entry.name) == publisher != core:
                # e.g. %APPDATA%\JetBrains\PyCharm2025.1: look one level down
                for sub in folders(entry.path):
                    consider(sub.path)
                continue
            if entry.name.lower() not in NOT_ORPHANS:
                consider(entry.path)
    location = os.path.normpath(program.location) if program.location else ""
    # An InstallLocation that is a base folder (or holds one) would mean "everything".
    broad = [key(b) for b in bases + [profile] if b]
    if location and os.path.isdir(location) \
            and any(_belongs(os.path.basename(location), c) for c in cores) \
            and not any(key(location) == b or under(b, key(location)) for b in broad):
        found.append(location)
    keys = [key(p) for p in exclude]
    found = sorted({p for p in found if not actions.is_protected(p, keys)})
    if not found:
        return None
    sizes = {p: measure(p) for p in found}
    return Recommendation(
        "leftovers", "apps", Safety.CAUTION, Action.REVIEW,
        pick(("Leftovers of {name}", "Residui di {name}")).format(name=program.name),
        pick((
            "Folders with this program's name, still there after its uninstaller ran. "
            "They usually hold settings, caches and logs. Keep them if you plan to "
            "reinstall and want your settings back.",
            "Cartelle con il nome di questo programma, rimaste dopo la disinstallazione. Di "
            "solito contengono impostazioni, cache e log. Tienile se pensi di reinstallarlo "
            "e vuoi ritrovare le impostazioni.",
        )),
        sum(sizes.values()), sorted(found, key=lambda p: -sizes[p]),
        question=pick(question("leftovers")),
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
    recs += [_idle_projects(result, now), _orphans(result, programs, covered),
             _app_caches(result, covered), _old_versions(result), _community(result, covered)]
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
