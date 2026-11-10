"""Catalogue of known space hogs. Data, not logic: see docs/RULES.md to add one.

A rule's paths may use %ENVIRONMENT% variables and glob wildcards. Texts are either a
plain string (language-neutral) or an (english, italian) pair.
"""

from __future__ import annotations

import glob
import os
import re
import stat
from dataclasses import dataclass
from enum import Enum

Text = str | tuple[str, str]


class Safety(Enum):
    SAFE = "safe"  # rebuilt automatically, nothing of the user's is lost
    CAUTION = "caution"  # re-download or reconfiguration needed: the user decides
    SYSTEM = "system"  # Windows itself: guidance only
    ARCHIVE = "archive"  # user data worth keeping, better on another drive


class Action(Enum):
    DELETE = "delete"  # WinDiskCleaner empties the folder / removes the file after confirmation
    REVIEW = "review"  # guided check: one question per item, then delete / move / keep
    GUIDE = "guide"  # WinDiskCleaner offers commands to run and/or opens a Windows tool


VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,99}")


@dataclass(frozen=True)
class Command:
    """A command the user can run with one click. Always an argument list, never a shell line."""

    label: Text
    argv: tuple[str, ...]  # "{value}" is replaced by what the user types for `ask`
    admin: bool = False  # needs an elevated WinDiskCleaner
    changes: bool = False  # modifies the system: confirmed before running
    ask: Text = ""  # prompt for {value}
    options_from: tuple[str, ...] = ()  # read-only command that lists the possible values
    options_pattern: str = ""  # regex with one group, tried on each line of its output

    def options(self, output: str) -> list[tuple[str, str]]:
        """(value, line shown to the user) for each value found in `options_from` output."""
        found = []
        for line in output.splitlines():
            match = re.search(self.options_pattern, line)
            if match and VALUE.fullmatch(match.group(1)):
                found.append((match.group(1), line.strip()))
        return found

    def build(self, value: str = "") -> list[str]:
        """Final argument list. Raises ValueError if the user's value is not a plain name."""
        if self.ask and not VALUE.fullmatch(value):
            raise ValueError(f"not a valid name: {value!r}")
        return [arg.replace("{value}", value) for arg in self.argv]


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    paths: tuple[str, ...]
    safety: Safety
    action: Action
    title: Text
    why: Text
    commands: tuple[Command, ...] = ()  # run only when the user clicks one
    tool: str = ""  # executable, shell: folder or ms-settings: URI; "a|b" = first that exists
    permanent: bool = False  # DELETE bypasses the Recycle Bin (temporary files only)
    process: str = ""  # executable to close first ("chrome.exe"): the UI warns if it runs

    def resolve(self) -> list[str]:
        """Existing paths this rule points at on this machine."""
        found: list[str] = []
        for pattern in self.paths:
            expanded = os.path.expandvars(pattern)
            if "%" in expanded:  # variable not defined here
                continue
            found.extend(p for p in glob.glob(expanded) if not through_link(p, expanded))
        return found


def through_link(path: str, pattern: str) -> bool:
    """True when a wildcard of `pattern` matched a junction or symlink. The folder would be
    found twice: on Italian Windows `%LOCALAPPDATA%\\*` also matches the legacy junction
    `Dati applicazioni`, which points back at %LOCALAPPDATA% itself."""
    parts = path.split(os.sep)
    for i, part in enumerate(pattern.split(os.sep)):
        if not re.search(r"[*?[]", part):
            continue
        sub = os.sep.join(parts[: i + 1])
        try:
            attrs = getattr(os.lstat(sub), "st_file_attributes", 0)
        except OSError:
            return True
        if attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT or os.path.islink(sub):
            return True
    return False


L, R, U, PD, W = "%LOCALAPPDATA%", "%APPDATA%", "%USERPROFILE%", "%PROGRAMDATA%", "%WINDIR%"
LL = r"%USERPROFILE%\AppData\LocalLow"

# Offered before every command that changes Windows itself. A restore point covers system
# files and the registry, not the user's own files: for those there is the Recycle Bin.
RESTORE_POINT = Command(
    ("Create a restore point now", "Crea un punto di ripristino adesso"),
    ("powershell", "-NoProfile", "-Command",
     "Checkpoint-Computer -Description 'WinDiskCleaner' -RestorePointType MODIFY_SETTINGS"),
    admin=True,
)

_BROWSER_WHY = (
    "Copies of web pages, scripts, compiled shaders and downloaded components kept to load "
    "sites faster. Rebuilt as you browse; logins, bookmarks and site data are not touched. "
    "Close the browser first.",
    "Copie di pagine, script, shader compilati e componenti scaricati tenute per caricare i "
    "siti più in fretta. Si ricreano navigando; accessi, preferiti e dati dei siti non vengono "
    "toccati. Chiudi prima il browser.",
)
_UPDATE_WHY = (
    "Installers of updates that are already installed, kept by the programs' updaters "
    "(Electron, Squirrel). A program downloads its next update again when needed.",
    "Installer di aggiornamenti già installati, tenuti dagli updater dei programmi "
    "(Electron, Squirrel). Il programma riscarica l'aggiornamento successivo quando serve.",
)
_PKG_WHY = (
    "Downloaded packages kept to speed up future installs. Installed environments keep "
    "working; packages are downloaded again when needed.",
    "Pacchetti scaricati tenuti per velocizzare le installazioni future. Gli ambienti già "
    "installati continuano a funzionare; i pacchetti si riscaricano quando servono.",
)


# Inside each profile of a Chromium "User Data" folder (also WebView2 and Electron apps).
# Never IndexedDB, Local Storage or Service Worker\Database: those are the sites' own data.
_PROFILE_CACHES = (
    "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache",
    r"Service Worker\CacheStorage", r"Service Worker\ScriptCache",
)
# Directly inside "User Data". Snapshots only serve a rollback to the previous version.
_SHARED_CACHES = (
    "GrShaderCache", "GraphiteDawnCache", "ShaderCache", "component_crx_cache",
    "extensions_crx_cache", "Snapshots", r"Crashpad\reports",
)


def _chromium(base: str) -> tuple[str, ...]:
    return (tuple(rf"{base}\*\{d}" for d in _PROFILE_CACHES)
            + tuple(rf"{base}\{d}" for d in _SHARED_CACHES))


def _browser(rule_id: str, name: str, base: str, process: str) -> Rule:
    return Rule(rule_id, "browser", _chromium(base), Safety.SAFE, Action.DELETE,
                f"{name} cache", _BROWSER_WHY, process=process)


RULES: tuple[Rule, ...] = (
    # ---- temporary files -------------------------------------------------------------
    Rule(
        "user_temp", "temp", ("%TEMP%",), Safety.SAFE, Action.DELETE,
        ("User temporary files", "File temporanei utente"),
        (
            "Scratch files left by programs. Files still in use are skipped.",
            "File di lavoro lasciati dai programmi. Quelli ancora in uso vengono saltati.",
        ),
        permanent=True,
    ),
    Rule(
        "windows_temp", "temp", (rf"{W}\Temp",), Safety.SAFE, Action.DELETE,
        ("Windows temporary files", "File temporanei di Windows"),
        (
            "Scratch files of installers and services. Most need administrator rights: "
            "what cannot be removed is skipped.",
            "File di lavoro di installer e servizi. Molti richiedono diritti di amministratore: "
            "ciò che non si può rimuovere viene saltato.",
        ),
        permanent=True,
    ),
    Rule(
        "crash_dumps", "temp",
        (rf"{L}\CrashDumps", rf"{U}\*.hprof", rf"{U}\*.dmp",
         rf"{L}\*\Crashpad\reports", rf"{R}\*\Crashpad\reports",
         rf"{L}\Microsoft\Windows\WER\ReportArchive", rf"{L}\Microsoft\Windows\WER\ReportQueue"),
        Safety.SAFE, Action.DELETE,
        ("Crash dumps", "Dump di crash"),
        (
            "Memory snapshots written when a program crashed. Only useful to its developers.",
            "Istantanee di memoria scritte quando un programma è andato in crash. "
            "Utili solo a chi lo sviluppa.",
        ),
    ),
    # ---- browsers --------------------------------------------------------------------
    _browser("chrome_cache", "Google Chrome", rf"{L}\Google\Chrome\User Data", "chrome.exe"),
    _browser("edge_cache", "Microsoft Edge", rf"{L}\Microsoft\Edge\User Data", "msedge.exe"),
    _browser("brave_cache", "Brave", rf"{L}\BraveSoftware\Brave-Browser\User Data", "brave.exe"),
    Rule(
        "firefox_cache", "browser", (rf"{L}\Mozilla\Firefox\Profiles\*\cache2",),
        Safety.SAFE, Action.DELETE, "Mozilla Firefox cache", _BROWSER_WHY, process="firefox.exe",
    ),
    Rule(
        # Opera splits its profile: settings and code caches in Roaming, page cache in Local.
        "opera_cache", "browser",
        _chromium(rf"{R}\Opera Software\*")
        + tuple(rf"{R}\Opera Software\*\{d}" for d in _PROFILE_CACHES)
        + tuple(rf"{L}\Opera Software\{p}\{d}"
                for p in ("*", r"*\Default") for d in ("Cache", "System Cache")),
        Safety.SAFE, Action.DELETE, "Opera cache", _BROWSER_WHY, process="opera.exe",
    ),
    # ---- developer caches: safe ------------------------------------------------------
    Rule("pip_cache", "dev", (rf"{L}\pip\cache",), Safety.SAFE, Action.DELETE,
         "pip cache", _PKG_WHY),
    Rule("uv_cache", "dev", (rf"{L}\uv\cache",), Safety.SAFE, Action.DELETE,
         "uv cache", _PKG_WHY),
    Rule("npm_cache", "dev", (rf"{L}\npm-cache\_cacache", rf"{R}\npm-cache\_cacache"),
         Safety.SAFE, Action.DELETE, "npm cache", _PKG_WHY),
    Rule("yarn_cache", "dev", (rf"{L}\Yarn\Cache",), Safety.SAFE, Action.DELETE,
         "Yarn cache", _PKG_WHY),
    Rule(
        "vscode_cache", "dev",
        tuple(rf"{R}\Code\{d}" for d in
              ("Cache", "Code Cache", "CachedData", "CachedExtensionVSIXs", "logs", "GPUCache",
               r"Service Worker\CacheStorage", r"Service Worker\ScriptCache"))
        + (rf"{L}\Microsoft\vscode-cpptools\ipch",),
        Safety.SAFE, Action.DELETE,
        ("VS Code caches", "Cache di VS Code"),
        (
            "Caches, logs, downloaded extension packages and the C/C++ IntelliSense cache. "
            "Settings and installed extensions are not touched. Close VS Code first.",
            "Cache, log, pacchetti di estensioni scaricati e cache IntelliSense C/C++. "
            "Impostazioni ed estensioni installate non vengono toccate. Chiudi prima VS Code.",
        ),
        process="Code.exe",
    ),
    Rule(
        "jetbrains_tmp", "dev", (rf"{L}\JetBrains\*\tmp",), Safety.SAFE, Action.DELETE,
        ("JetBrains IDE temporary files", "File temporanei degli IDE JetBrains"),
        (
            "Update patches and scratch files of PyCharm, IntelliJ and similar. Close the IDE first.",
            "Patch di aggiornamento e file di lavoro di PyCharm, IntelliJ e simili. "
            "Chiudi prima l'IDE.",
        ),
    ),
    Rule(
        "arduino_staging", "dev", (rf"{L}\Arduino15\staging",), Safety.SAFE, Action.DELETE,
        ("Arduino downloads", "Download di Arduino"),
        (
            "Archives of boards and toolchains that are already installed.",
            "Archivi di schede e toolchain già installate.",
        ),
    ),
    Rule(
        "ollama_updates", "dev", (rf"{L}\Ollama\updates_v2",), Safety.SAFE, Action.DELETE,
        ("Ollama update installers", "Installer di aggiornamento di Ollama"),
        (
            "Downloaded installers of Ollama updates. Models are not touched.",
            "Installer scaricati degli aggiornamenti di Ollama. I modelli non vengono toccati.",
        ),
    ),
    Rule(
        "rpi_imager_cache", "dev", (rf"{L}\Raspberry Pi\Imager\cache",),
        Safety.SAFE, Action.DELETE,
        ("Raspberry Pi Imager cache", "Cache di Raspberry Pi Imager"),
        ("Last downloaded OS image.", "Ultima immagine di sistema scaricata."),
    ),
    # ---- programs: safe --------------------------------------------------------------
    Rule(
        "app_update_leftovers", "apps",
        (rf"{L}\*-updater\installer.exe", rf"{L}\*-updater\pending", rf"{L}\*-updater\package.7z",
         rf"{L}\*\packages\*.nupkg", rf"{L}\Docker Desktop Installer\update-*.exe"),
        Safety.SAFE, Action.DELETE,
        ("Leftover update installers", "Installer di aggiornamento rimasti"),
        _UPDATE_WHY,
    ),
    Rule(
        "shader_caches", "apps",
        (rf"{LL}\NVIDIA\DXCache", rf"{LL}\NVIDIA\GLCache", rf"{L}\NVIDIA\DXCache",
         rf"{L}\NVIDIA\GLCache", rf"{R}\NVIDIA\ComputeCache", rf"{L}\D3DSCache",
         rf"{L}\AMD\DxCache", rf"{L}\AMD\DxcCache", rf"{L}\AMD\GLCache", rf"{L}\AMD\VkCache",
         rf"{LL}\Intel\ShaderCache"),
        Safety.SAFE, Action.DELETE,
        ("Graphics shader caches", "Cache degli shader grafici"),
        (
            "Shaders compiled by the graphics driver for games and 3D programs. Rebuilt "
            "automatically: the first launch of a game may stutter briefly. Files in use are "
            "skipped.",
            "Shader compilati dal driver grafico per giochi e programmi 3D. Si ricreano da soli: "
            "il primo avvio di un gioco può scattare per poco. I file in uso vengono saltati.",
        ),
    ),
    Rule(
        "google_earth_cache", "apps", (rf"{LL}\Google\GoogleEarth\Cache",),
        Safety.SAFE, Action.DELETE,
        ("Google Earth cache", "Cache di Google Earth"),
        (
            "Map tiles and imagery already viewed. Downloaded again as you explore; saved "
            "places are not touched. Close Google Earth first.",
            "Riquadri di mappa e immagini già viste. Si riscaricano esplorando; i luoghi salvati "
            "non vengono toccati. Chiudi prima Google Earth.",
        ),
        process="googleearth.exe",
    ),
    Rule(
        "teams_cache", "apps",
        _chromium(rf"{L}\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\EBWebView")
        + (rf"{L}\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\Logs",),
        Safety.SAFE, Action.DELETE,
        ("Microsoft Teams cache", "Cache di Microsoft Teams"),
        (
            "Web cache and logs of the new Teams. Rebuilt at the next start; chats, sign-in "
            "and custom backgrounds are not touched. Quit Teams first (tray icon → Quit).",
            "Cache web e log del nuovo Teams. Si ricreano al prossimo avvio; chat, accesso e "
            "sfondi personalizzati non vengono toccati. Chiudi prima Teams (icona nell'area "
            "di notifica → Esci).",
        ),
        process="ms-teams.exe",
    ),
    # ---- developer caches and tools: the user decides --------------------------------
    Rule(
        "gradle_caches", "dev", (rf"{U}\.gradle\caches", rf"{U}\.gradle\wrapper\dists"),
        Safety.CAUTION, Action.REVIEW,
        ("Gradle caches", "Cache di Gradle"),
        (
            "Dependencies and Gradle versions of Android/Java builds. Deleting is harmless but "
            "the next build downloads everything again. Old version folders can go first.",
            "Dipendenze e versioni di Gradle delle build Android/Java. Eliminarle non fa danni "
            "ma la build successiva riscarica tutto. Si possono togliere prima le versioni vecchie.",
        ),
    ),
    Rule(
        "android_avd", "dev", (rf"{U}\.android\avd",), Safety.CAUTION, Action.REVIEW,
        ("Android emulators", "Emulatori Android"),
        (
            "Virtual phones with their data. Remove the ones you no longer use from "
            "Android Studio → Device Manager.",
            "Telefoni virtuali con i loro dati. Rimuovi quelli che non usi più da "
            "Android Studio → Device Manager.",
        ),
    ),
    Rule(
        "android_sdk", "dev", (rf"{L}\Android\Sdk",), Safety.CAUTION, Action.REVIEW,
        ("Android SDK", "Android SDK"),
        (
            "Platforms and system images. Remove unused versions from Android Studio → SDK Manager.",
            "Piattaforme e immagini di sistema. Rimuovi le versioni non usate da "
            "Android Studio → SDK Manager.",
        ),
    ),
    Rule(
        "ollama_models", "dev", (rf"{U}\.ollama\models",), Safety.CAUTION, Action.GUIDE,
        ("Ollama models", "Modelli Ollama"),
        (
            "Downloaded AI models. List them with “ollama list” and remove the unused ones.",
            "Modelli AI scaricati. Elencali con “ollama list” e rimuovi quelli che non usi.",
        ),
        commands=(
            Command(("List models", "Elenca modelli"), ("ollama", "list")),
            Command(("Remove models…", "Rimuovi modelli…"), ("ollama", "rm", "{value}"),
                    changes=True, ask=("Models to remove", "Modelli da rimuovere"),
                    options_from=("ollama", "list"), options_pattern=r"^(?!NAME\s)(\S+)\s"),
        ),
    ),
    Rule(
        "lmstudio", "dev", (rf"{U}\.lmstudio",), Safety.CAUTION, Action.GUIDE,
        ("LM Studio models and runtimes", "Modelli e runtime di LM Studio"),
        (
            "Models and inference backends. Deleting the folders by hand confuses LM Studio: "
            "open it and remove models under My Models, runtimes under Settings → Runtime.",
            "Modelli e backend di inferenza. Eliminare le cartelle a mano confonde LM Studio: "
            "aprilo e rimuovi i modelli da My Models, i runtime da Settings → Runtime.",
        ),
        tool=r"%ProgramFiles%\LM Studio\LM Studio.exe|%LOCALAPPDATA%\Programs\LM Studio\LM Studio.exe",
    ),
    Rule(
        "vscode_extensions", "dev", (rf"{U}\.vscode\extensions",), Safety.CAUTION, Action.REVIEW,
        ("VS Code extensions", "Estensioni di VS Code"),
        (
            "Installed extensions, sometimes with several old versions side by side. "
            "Uninstall unused ones from VS Code.",
            "Estensioni installate, a volte con più versioni vecchie affiancate. "
            "Disinstalla da VS Code quelle che non usi.",
        ),
    ),
    Rule(
        "nvm_versions", "dev", (rf"{L}\nvm", rf"{R}\nvm"), Safety.CAUTION, Action.GUIDE,
        ("Node.js versions (nvm)", "Versioni di Node.js (nvm)"),
        (
            "Every installed Node.js version with its global packages. "
            "List with “nvm list” and remove the ones you do not need.",
            "Ogni versione di Node.js installata con i suoi pacchetti globali. "
            "Elenca con “nvm list” e rimuovi quelle che non servono.",
        ),
        commands=(
            Command(("List versions", "Elenca versioni"), ("nvm", "list")),
            Command(("Uninstall versions…", "Disinstalla versioni…"),
                    ("nvm", "uninstall", "{value}"), changes=True,
                    ask=("Versions to uninstall", "Versioni da disinstallare"),
                    options_from=("nvm", "list"), options_pattern=r"(\d+\.\d+\.\d+)"),
        ),
    ),
    Rule(
        "arduino_packages", "dev", (rf"{L}\Arduino15\packages",), Safety.CAUTION, Action.REVIEW,
        ("Arduino boards and toolchains", "Schede e toolchain Arduino"),
        (
            "Installed board support. Remove unused boards from the Arduino IDE Boards Manager.",
            "Supporto per le schede installate. Rimuovi quelle non usate dal Gestore schede "
            "dell'IDE Arduino.",
        ),
    ),
    Rule(
        "conda_pkgs", "dev", (rf"{U}\.conda\pkgs", rf"{U}\anaconda3\pkgs", rf"{U}\miniconda3\pkgs"),
        Safety.CAUTION, Action.GUIDE,
        ("Conda package cache", "Cache dei pacchetti Conda"),
        _PKG_WHY,
        commands=(
            Command(("Clean the package cache", "Pulisci la cache dei pacchetti"),
                    ("cmd", "/c", "conda", "clean", "--all", "--yes"), changes=True),
        ),
    ),
    Rule(
        "pub_cache", "dev", (rf"{L}\Pub\Cache",), Safety.CAUTION, Action.GUIDE,
        ("Dart / Flutter package cache", "Cache dei pacchetti Dart / Flutter"),
        (
            "Packages of every Dart and Flutter project. After the clean-up each project needs "
            "“flutter pub get” again, and globally activated tools are removed.",
            "Pacchetti di tutti i progetti Dart e Flutter. Dopo la pulizia ogni progetto richiede "
            "di nuovo “flutter pub get” e gli strumenti attivati globalmente vengono rimossi.",
        ),
        commands=(
            Command(("Clean the package cache", "Pulisci la cache dei pacchetti"),
                    ("cmd", "/c", "dart", "pub", "cache", "clean", "--force"), changes=True),
        ),
    ),
    Rule(
        "pnpm_store", "dev", (rf"{L}\pnpm\store",), Safety.CAUTION, Action.GUIDE,
        ("pnpm store", "Archivio di pnpm"),
        (
            "Packages shared by every pnpm project through hard links. Do not delete it by hand: "
            "“pnpm store prune” removes only the packages no project uses.",
            "Pacchetti condivisi da tutti i progetti pnpm tramite hard link. Non eliminarlo a "
            "mano: “pnpm store prune” rimuove solo i pacchetti che nessun progetto usa.",
        ),
        commands=(
            Command(("Remove unused packages", "Rimuovi i pacchetti inutilizzati"),
                    ("cmd", "/c", "pnpm", "store", "prune"), changes=True),
        ),
    ),
    Rule(
        "python_versions", "dev", (rf"{L}\Programs\Python\Python*",), Safety.CAUTION, Action.GUIDE,
        ("Python versions", "Versioni di Python"),
        (
            "Every Python installed for this user, with its packages. Keep the versions your "
            "projects use and uninstall the others from Installed apps: deleting the folder "
            "leaves the uninstaller and the py launcher pointing at nothing.",
            "Ogni Python installato per questo utente, con i suoi pacchetti. Tieni le versioni "
            "usate dai tuoi progetti e disinstalla le altre da App installate: eliminare la "
            "cartella lascia il programma di disinstallazione e il launcher py senza bersaglio.",
        ),
        commands=(Command(("List installed versions", "Elenca le versioni installate"),
                          ("py", "-0p")),),
        tool="ms-settings:appsfeatures",
    ),
    Rule(
        "azure_func_tools", "dev", (rf"{L}\AzureFunctionsTools\Releases",),
        Safety.CAUTION, Action.REVIEW,
        ("Azure Functions Core Tools versions", "Versioni di Azure Functions Core Tools"),
        (
            "Downloaded by Visual Studio, one folder per version. Versions your Functions "
            "projects do not target can go; Visual Studio downloads them again if needed.",
            "Scaricate da Visual Studio, una cartella per versione. Le versioni non usate dai "
            "tuoi progetti Functions si possono togliere; Visual Studio le riscarica se servono.",
        ),
    ),
    Rule(
        "docker_data", "dev", (rf"{L}\Docker\wsl",), Safety.CAUTION, Action.GUIDE,
        ("Docker images, containers and volumes", "Immagini, container e volumi Docker"),
        (
            "Everything Docker stores lives in one virtual disk. First remove unused data with "
            "the buttons below, then compact the disk from the System tab: the file does not "
            "shrink by itself.",
            "Tutto ciò che Docker conserva sta in un unico disco virtuale. Prima rimuovi i dati "
            "inutilizzati con i pulsanti qui sotto, poi compatta il disco dalla scheda Sistema: "
            "il file non si riduce da solo.",
        ),
        commands=(
            Command(("Show Docker disk usage", "Mostra lo spazio usato da Docker"),
                    ("docker", "system", "df")),
            Command(("Remove unused images and build cache",
                     "Rimuovi immagini e cache di build inutilizzate"),
                    ("docker", "system", "prune", "-a", "-f"), changes=True),
        ),
    ),
    Rule(
        "nvidia_ngx", "apps", (rf"{PD}\NVIDIA\NGX\models",), Safety.CAUTION, Action.REVIEW,
        ("NVIDIA AI models (Broadcast, DLSS)", "Modelli AI NVIDIA (Broadcast, DLSS)"),
        (
            "Models for NVIDIA Broadcast effects, often several versions. If you do not use "
            "Broadcast, uninstall it; otherwise old version folders can be removed.",
            "Modelli per gli effetti di NVIDIA Broadcast, spesso in più versioni. Se non usi "
            "Broadcast disinstallalo; altrimenti si possono rimuovere le cartelle delle versioni "
            "vecchie.",
        ),
    ),
    Rule(
        "nvidia_installers", "apps",
        (rf"{PD}\NVIDIA Corporation\NVIDIA app\UpdateFramework\ota-artifacts",
         rf"{PD}\NVIDIA Corporation\Downloader"),
        Safety.CAUTION, Action.REVIEW,
        ("NVIDIA driver installers", "Installer dei driver NVIDIA"),
        (
            "Downloaded driver packages kept after installation. Removing them needs "
            "administrator rights and only prevents reinstalling without a new download.",
            "Pacchetti driver scaricati e tenuti dopo l'installazione. Rimuoverli richiede "
            "diritti di amministratore e impedisce solo di reinstallare senza riscaricare.",
        ),
    ),
    Rule(
        "teams_classic", "apps", (rf"{L}\Microsoft\Teams", rf"{R}\Microsoft\Teams"),
        Safety.CAUTION, Action.REVIEW,
        ("Classic Microsoft Teams", "Microsoft Teams classico"),
        (
            "Program files and cache of the old Teams, retired by Microsoft in 2024. The new "
            "Teams keeps its data elsewhere. Uninstall “Microsoft Teams classic” from Installed "
            "apps first if it is still listed.",
            "File del programma e cache del vecchio Teams, ritirato da Microsoft nel 2024. Il "
            "nuovo Teams tiene i suoi dati altrove. Se “Microsoft Teams classic” è ancora tra "
            "le App installate, disinstallalo prima da lì.",
        ),
        process="Teams.exe",
    ),
    Rule(
        "clipchamp", "apps", (rf"{L}\Packages\Clipchamp.Clipchamp_*\LocalState\EBWebView",),
        Safety.CAUTION, Action.GUIDE,
        ("Clipchamp projects and media", "Progetti e media di Clipchamp"),
        (
            "Clipchamp stores imported media and projects in its web storage. Delete unneeded "
            "projects inside Clipchamp. Installed apps → Clipchamp → Advanced options → Reset "
            "empties everything, including projects not yet exported.",
            "Clipchamp conserva media importati e progetti nella sua memoria web. Elimina da "
            "Clipchamp i progetti che non servono. App installate → Clipchamp → Opzioni avanzate "
            "→ Reimposta svuota tutto, compresi i progetti non ancora esportati.",
        ),
        tool="ms-settings:appsfeatures",
    ),
    Rule(
        "telegram_cache", "apps",
        (rf"{R}\Telegram Desktop\tdata\user_data", rf"{R}\Telegram Desktop\tdata\user_data#*"),
        Safety.CAUTION, Action.GUIDE,
        ("Telegram media cache", "Cache dei media di Telegram"),
        (
            "Photos, videos and files Telegram downloaded while you scrolled. Clear it inside "
            "Telegram: Settings → Advanced → Manage local storage, where you can also cap its "
            "size. Deleting the folder by hand while Telegram runs can damage it.",
            "Foto, video e file scaricati da Telegram mentre scorri le chat. Svuotala da "
            "Telegram: Impostazioni → Avanzate → Gestisci memoria locale, dove puoi anche "
            "limitarne la dimensione. Eliminare la cartella a mano con Telegram aperto può "
            "danneggiarla.",
        ),
        tool=rf"{R}\Telegram Desktop\Telegram.exe",
    ),
    Rule(
        "whatsapp_storage", "apps",
        (rf"{L}\Packages\5319275A.WhatsAppDesktop_*\LocalCache",
         rf"{L}\Packages\5319275A.WhatsAppDesktop_*\LocalState\shared\transfers"),
        Safety.CAUTION, Action.GUIDE,
        ("WhatsApp media", "Media di WhatsApp"),
        (
            "Media and cache of WhatsApp Desktop. Free space inside WhatsApp: Settings → "
            "Storage, which lists the biggest chats and files. Deleting by hand can break "
            "the app.",
            "Media e cache di WhatsApp Desktop. Libera spazio da WhatsApp: Impostazioni → "
            "Spazio di archiviazione, che elenca le chat e i file più grandi. Eliminare a mano "
            "può rompere l'app.",
        ),
        tool="whatsapp:",
    ),
    Rule(
        "onedrive_local", "apps", (rf"{U}\OneDrive", rf"{U}\OneDrive - *"),
        Safety.CAUTION, Action.GUIDE,
        ("OneDrive files kept on this PC", "File di OneDrive tenuti su questo PC"),
        (
            "Files that are in OneDrive and also stored on this disk. Right-click a folder → "
            "“Free up space” keeps it in the cloud only (it downloads again when opened). "
            "Storage Sense can do this by itself for files not opened for some days.",
            "File che sono in OneDrive e anche salvati su questo disco. Tasto destro su una "
            "cartella → “Libera spazio” li tiene solo nel cloud (si riscaricano quando li "
            "apri). Sensore memoria può farlo da solo per i file non aperti da alcuni giorni.",
        ),
        tool="ms-settings:storagesense",
    ),
    # ---- Windows ---------------------------------------------------------------------
    Rule(
        "delivery_optimization", "system",
        (rf"{W}\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows"
         r"\DeliveryOptimization\Cache",),
        Safety.SYSTEM, Action.GUIDE,
        ("Delivery Optimization cache", "Cache di Ottimizzazione recapito"),
        (
            "Pieces of Windows and Store updates kept to share with other PCs. Windows trims "
            "it by itself; the command below empties it now.",
            "Parti di aggiornamenti di Windows e dello Store tenute per condividerle con altri "
            "PC. Windows la riduce da solo; il comando qui sotto la svuota subito.",
        ),
        commands=(
            Command(("Empty the cache", "Svuota la cache"),
                    ("powershell", "-NoProfile", "-Command",
                     "Delete-DeliveryOptimizationCache -Force"), admin=True, changes=True),
        ),
        tool="ms-settings:delivery-optimization",
    ),
    Rule(
        "reserved_storage", "system", (), Safety.SYSTEM, Action.GUIDE,
        ("Reserved storage", "Spazio di archiviazione riservato"),
        (
            "Windows keeps several GB aside so that updates always have room. Turning it off "
            "frees that space, but an update may then fail on a full disk.",
            "Windows tiene da parte alcuni GB perché gli aggiornamenti abbiano sempre spazio. "
            "Disattivarlo libera quello spazio, ma un aggiornamento potrebbe poi fallire con "
            "il disco pieno.",
        ),
        commands=(
            Command(("Show its state", "Mostra lo stato"),
                    ("DISM.exe", "/Online", "/Get-ReservedStorageState"), admin=True),
            Command(("Turn it off", "Disattivalo"),
                    ("DISM.exe", "/Online", "/Set-ReservedStorageState", "/State:Disabled"),
                    admin=True, changes=True),
            Command(("Turn it back on", "Riattivalo"),
                    ("DISM.exe", "/Online", "/Set-ReservedStorageState", "/State:Enabled"),
                    admin=True, changes=True),
        ),
    ),
    Rule(
        "hibernation", "system", (r"%SystemDrive%\hiberfil.sys",), Safety.SYSTEM, Action.GUIDE,
        ("Hibernation file (hiberfil.sys)", "File di ibernazione (hiberfil.sys)"),
        (
            "Holds memory contents for hibernation and Fast Startup. “powercfg /h off” deletes "
            "it (no more hibernation, slightly slower boot); “powercfg /h on” recreates it. "
            "“powercfg /h /type reduced” keeps Fast Startup with a smaller file.",
            "Contiene la memoria per l'ibernazione e l'Avvio rapido. “powercfg /h off” lo "
            "elimina (niente più ibernazione, avvio un po' più lento); “powercfg /h on” lo "
            "ricrea. “powercfg /h /type reduced” mantiene l'Avvio rapido con un file più piccolo.",
        ),
        commands=(
            Command(("Turn hibernation off (deletes the file)",
                     "Disattiva l'ibernazione (elimina il file)"),
                    ("powercfg", "/h", "off"), admin=True, changes=True),
            Command(("Shrink the file (keeps Fast Startup)", "Riduci il file (mantiene Avvio rapido)"),
                    ("powercfg", "/h", "/type", "reduced"), admin=True, changes=True),
            Command(("Turn hibernation back on", "Riattiva l'ibernazione"),
                    ("powercfg", "/h", "on"), admin=True, changes=True),
        ),
    ),
    Rule(
        "pagefile", "system", (r"%SystemDrive%\pagefile.sys",), Safety.SYSTEM, Action.GUIDE,
        ("Page file (pagefile.sys)", "File di paging (pagefile.sys)"),
        (
            "Virtual memory. Do not delete it: set a smaller fixed size or move it to another "
            "drive under Advanced → Virtual memory → Change, then restart. Windows recreates "
            "it at boot.",
            "Memoria virtuale. Non eliminarlo: imposta una dimensione fissa più piccola o "
            "spostalo su un altro disco in Avanzate → Memoria virtuale → Cambia, poi riavvia. "
            "Windows lo ricrea all'avvio.",
        ),
        tool="SystemPropertiesPerformance.exe",
    ),
    Rule(
        "winsxs", "system", (rf"{W}\WinSxS",), Safety.SYSTEM, Action.GUIDE,
        ("Windows component store (WinSxS)", "Archivio componenti di Windows (WinSxS)"),
        (
            "Never delete by hand. The clean-up removes superseded update files; the size shown "
            "is inflated because most files are shared with the rest of Windows.",
            "Mai eliminare a mano. La pulizia rimuove i file di aggiornamenti superati; la "
            "dimensione mostrata è gonfiata perché molti file sono condivisi con il resto di "
            "Windows.",
        ),
        commands=(
            Command(("Analyse (how much can be reclaimed)", "Analizza (quanto si può recuperare)"),
                    ("Dism.exe", "/Online", "/Cleanup-Image", "/AnalyzeComponentStore"), admin=True),
            Command(("Clean up superseded components", "Rimuovi i componenti superati"),
                    ("Dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"),
                    admin=True, changes=True),
        ),
    ),
    Rule(
        "windows_update", "system",
        (rf"{W}\SoftwareDistribution\Download", r"%SystemDrive%\Windows.old"),
        Safety.SYSTEM, Action.GUIDE,
        ("Windows Update leftovers", "Residui di Windows Update"),
        (
            "Downloaded updates and the previous Windows installation. Remove them with "
            "Disk Cleanup → “Clean up system files”.",
            "Aggiornamenti scaricati e installazione precedente di Windows. Rimuovili con "
            "Pulizia disco → “Pulizia file di sistema”.",
        ),
        tool="cleanmgr.exe",
    ),
    Rule(
        "recycle_bin", "system", (r"%SystemDrive%\$Recycle.Bin",), Safety.SYSTEM, Action.GUIDE,
        ("Recycle Bin", "Cestino"),
        (
            "Deleted files still take space until the bin is emptied.",
            "I file eliminati occupano spazio finché il Cestino non viene svuotato.",
        ),
        tool="shell:RecycleBinFolder",
    ),
    Rule(
        "restore_points", "system", (), Safety.SYSTEM, Action.GUIDE,
        ("System restore points", "Punti di ripristino"),
        (
            "Their size is not readable without administrator rights. Under Configure you can "
            "cap the space they use or delete old ones.",
            "La loro dimensione non è leggibile senza diritti di amministratore. In Configura "
            "puoi limitare lo spazio usato o eliminare quelli vecchi.",
        ),
        tool="SystemPropertiesProtection.exe",
        commands=(RESTORE_POINT,),
    ),
    Rule(
        "storage_sense", "system", (), Safety.SYSTEM, Action.GUIDE,
        ("Storage Sense", "Sensore memoria"),
        (
            "Windows can empty temporary files and the Recycle Bin on a schedule.",
            "Windows può svuotare file temporanei e Cestino in modo programmato.",
        ),
        tool="ms-settings:storagesense",
    ),
)


# The question the guided check asks for each item. Keyed by rule or heuristic id.
DEFAULT_QUESTION: Text = ("Do you still need this?", "Ti serve ancora?")
QUESTIONS: dict[str, Text] = {
    "gradle_caches": ("Do you still build projects that use this?",
                      "Compili ancora progetti che lo usano?"),
    "android_avd": ("Do you still use this emulator?", "Usi ancora questo emulatore?"),
    "android_sdk": ("Do you still develop for this part of the SDK?",
                    "Sviluppi ancora con questa parte dell'SDK?"),
    "vscode_extensions": ("Do you still use this extension (this version)?",
                          "Usi ancora questa estensione (questa versione)?"),
    "arduino_packages": ("Do you still program this family of boards?",
                         "Programmi ancora questa famiglia di schede?"),
    "nvidia_ngx": ("Do you use NVIDIA Broadcast or this effect?",
                   "Usi NVIDIA Broadcast o questo effetto?"),
    "nvidia_installers": ("Keep this driver installer for a reinstall without downloading?",
                          "Tenere questo installer per reinstallare senza riscaricare?"),
    "archive_twins": ("The extracted folder exists next to it. Keep the archive too?",
                      "La cartella estratta esiste accanto. Tenere anche l'archivio?"),
    "old_installers": ("The program is probably installed already. Keep the installer?",
                       "Il programma è probabilmente già installato. Tenere l'installer?"),
    "archive_videos": ("Does this need to stay on the system drive?",
                       "Deve restare sul disco di sistema?"),
    "archive_vms": ("Does this need to stay on the system drive?",
                    "Deve restare sul disco di sistema?"),
    "archive_old": ("Not modified for two years. Does it need to stay on the system drive?",
                    "Non modificato da due anni. Deve restare sul disco di sistema?"),
    "idle_projects": ("Untouched for six months and rebuildable. Keep it?",
                      "Non toccata da sei mesi e rigenerabile. Tenerla?"),
    "azure_func_tools": ("Do your Functions projects still target this version?",
                         "I tuoi progetti Functions usano ancora questa versione?"),
    "teams_classic": ("Classic Teams is retired. Remove this part of it?",
                      "Teams classico è ritirato. Rimuovere questa sua parte?"),
    "winapp2": ("The community rules call this a cache. Delete the folder?",
                "Le regole della community la indicano come cache. Eliminare la cartella?"),
    "old_versions": ("A newer version is installed. Remove this old one?",
                     "È installata una versione più recente. Rimuovere questa vecchia?"),
    "app_caches": ("Remove this cache? It is rebuilt at the next start.",
                   "Rimuovere questa cache? Si ricrea al prossimo avvio."),
    "leftovers": ("Left by the removed program. Delete it?",
                  "Lasciata dal programma rimosso. Eliminarla?"),
    "appdata_orphans": ("Do you recognise the program this folder belongs to?",
                        "Riconosci il programma a cui appartiene questa cartella?"),
}


def question(rec_id: str) -> Text:
    return QUESTIONS.get(rec_id, DEFAULT_QUESTION)


def watch_paths() -> list[str]:
    """Directories the scanner should size while it walks the disk."""
    return [p for rule in RULES for p in rule.resolve() if os.path.isdir(p)]
