"""UI strings, English and Italian. Rule texts live next to each rule in rules.py."""

from __future__ import annotations

import os
import sys

LANG: str | None = None  # resolved on first use; tests may set it


def language() -> str:
    global LANG
    if LANG is None:
        LANG = os.environ.get("DISKDIET_LANG", "")
        if LANG not in ("en", "it"):
            LANG = "en"
            if sys.platform == "win32":
                import ctypes

                # primary language id 0x10 = Italian
                if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x10:
                    LANG = "it"
    return LANG


def pick(text: str | tuple[str, str]) -> str:
    """Choose from an (english, italian) pair; a plain string is language-neutral."""
    if isinstance(text, str):
        return text
    return text[1] if language() == "it" else text[0]


def tr(name: str, **kw) -> str:
    text = pick(S[name])
    return text.format(**kw) if kw else text


def fmt_size(n: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= scale:
            return f"{n / scale:.1f} {unit}"
    return f"{n} B"


S: dict[str, tuple[str, str]] = {
    # window
    "ui.scan": ("Scan", "Analizza"),
    "ui.cancel": ("Cancel", "Annulla"),
    "ui.folder": ("Choose folder…", "Scegli cartella…"),
    "ui.ready": ("Pick a drive and press Scan.", "Scegli un disco e premi Analizza."),
    "ui.scanning": ("Scanning… {n:,} files — {path}", "Analisi… {n:,} file — {path}"),
    "ui.cancelled": ("Scan cancelled.", "Analisi annullata."),
    "ui.failed": ("Operation failed: {err}", "Operazione fallita: {err}"),
    "ui.done": (
        "{size} in {files:,} files, {secs:.0f} s. {denied:,} items could not be read "
        "(run as administrator to include them).",
        "{size} in {files:,} file, {secs:.0f} s. {denied:,} elementi non leggibili "
        "(esegui come amministratore per includerli).",
    ),
    "ui.file": ("File", "File"),
    "ui.export_json": ("Export report as JSON…", "Esporta rapporto JSON…"),
    "ui.export_html": ("Export report as HTML…", "Esporta rapporto HTML…"),
    "ui.no_scan": ("Run a scan first.", "Esegui prima un'analisi."),
    # tabs
    "tab.overview": ("Overview", "Panoramica"),
    "tab.advice": ("Advice", "Consigli"),
    "tab.big": ("Largest files", "File grandi"),
    "tab.old": ("Old files", "File vecchi"),
    "tab.programs": ("Programs", "Programmi"),
    "tab.system": ("System", "Sistema"),
    "tab.archive": ("Archive", "Archivio"),
    "tab.dups": ("Duplicates", "Duplicati"),
    # overview
    "ui.up": ("⬆ Up", "⬆ Su"),
    "ui.files_here": ("(files in this folder)", "(file in questa cartella)"),
    "ui.unscanned": ("(not scanned / system reserved)", "(non analizzato / riservato)"),
    "ui.free": ("(free space)", "(spazio libero)"),
    "ui.other": ("(other)", "(altro)"),
    "col.name": ("Name", "Nome"),
    "col.size": ("Size", "Dimensione"),
    "col.share": ("Share", "Quota"),
    "col.files": ("Files", "File"),
    "col.modified": ("Modified", "Modificato"),
    "col.path": ("Path", "Percorso"),
    "col.publisher": ("Publisher", "Produttore"),
    "col.installed": ("Installed", "Installato"),
    "col.safety": ("Safety", "Sicurezza"),
    "col.action": ("Action", "Azione"),
    "col.kind": ("Kind", "Tipo"),
    # recommendations
    "cat.temp": ("Temporary files", "File temporanei"),
    "cat.browser": ("Browser caches", "Cache dei browser"),
    "cat.dev": ("Developer caches and tools", "Cache e strumenti di sviluppo"),
    "cat.apps": ("Application data", "Dati delle applicazioni"),
    "cat.projects": ("Idle projects", "Progetti fermi"),
    "cat.system": ("Windows system", "Sistema Windows"),
    "cat.archive": ("Move to another drive", "Da spostare su un altro disco"),
    "safety.safe": ("Safe", "Sicuro"),
    "safety.caution": ("Check first", "Verifica prima"),
    "safety.system": ("System", "Sistema"),
    "safety.archive": ("Archive", "Archivio"),
    "action.delete": ("Can be cleaned here", "Pulibile da qui"),
    "action.open": ("Review in Explorer", "Controlla in Esplora file"),
    "action.guide": ("Guided", "Guidata"),
    "rec.clean": ("Clean checked…", "Pulisci selezionati…"),
    "rec.all_safe": ("Clean everything safe…", "Pulisci tutto il sicuro…"),
    "rec.all_safe_tip": (
        "Ticks every item marked safe and shows what will be removed before doing anything.",
        "Seleziona tutte le voci sicure e mostra cosa verrà rimosso prima di fare qualsiasi "
        "cosa.",
    ),
    "rec.open": ("Open folder", "Apri cartella"),
    "rec.copy": ("Copy command", "Copia comando"),
    "rec.tool": ("Open Windows tool", "Apri strumento Windows"),
    "rec.command": ("Command (run in an administrator terminal):", "Comando (terminale amministratore):"),
    "rec.none_checked": ("Tick at least one item.", "Seleziona almeno una voce."),
    "rec.confirm_title": ("Confirm cleanup", "Conferma pulizia"),
    "rec.still_open": (
        "These programs are open:\n\n{apps}\n\nClose them first, or the files they are using "
        "will be skipped. Continue anyway?",
        "Questi programmi sono aperti:\n\n{apps}\n\nChiudili prima, altrimenti i file che "
        "stanno usando verranno saltati. Continuare comunque?",
    ),
    "rec.confirm": (
        "{n:,} items, about {size}, will be removed from:\n\n{titles}\n\n{how}\n\nContinue?",
        "{n:,} elementi, circa {size}, saranno rimossi da:\n\n{titles}\n\n{how}\n\nContinuare?",
    ),
    "rec.how_trash": (
        "They go to the Recycle Bin: space is freed when you empty it.",
        "Vanno nel Cestino: lo spazio si libera quando lo svuoti.",
    ),
    "rec.how_permanent": (
        "Temporary files are deleted permanently (not recoverable). "
        "Everything else goes to the Recycle Bin.",
        "I file temporanei sono eliminati definitivamente (non recuperabili). "
        "Il resto va nel Cestino.",
    ),
    "rec.result": (
        "Removed {n:,} items ({size}). Skipped {skipped:,} (in use or not permitted).\n"
        "Scan again to refresh the numbers.",
        "Rimossi {n:,} elementi ({size}). Saltati {skipped:,} (in uso o non permessi).\n"
        "Analizza di nuovo per aggiornare i numeri.",
    ),
    # files
    "file.open": ("Show in Explorer", "Mostra in Esplora file"),
    "file.trash": ("Move to Recycle Bin…", "Sposta nel Cestino…"),
    "file.trash_confirm": ("Move to the Recycle Bin?\n\n{path}", "Spostare nel Cestino?\n\n{path}"),
    # programs
    "prog.open": ("Open Windows “Installed apps”", "Apri “App installate” di Windows"),
    "prog.hint": (
        "Sizes are those declared by each installer and can be missing or low. "
        "Uninstall from Windows settings.",
        "Le dimensioni sono quelle dichiarate dagli installer e possono mancare o essere basse. "
        "Disinstalla dalle impostazioni di Windows.",
    ),
    # archive
    "arch.target": (
        "Suggested destination: drive {drive} ({free} free).",
        "Destinazione suggerita: disco {drive} ({free} liberi).",
    ),
    "arch.no_target": (
        "No other fixed drive found: use an external disk.",
        "Nessun altro disco fisso trovato: usa un disco esterno.",
    ),
    # vhdx
    "vhdx.title": ("Virtual disks (.vhdx)", "Dischi virtuali (.vhdx)"),
    "vhdx.hint": (
        "Virtual disks grow but never shrink on their own. Compacting returns the unused space.",
        "I dischi virtuali crescono ma non si riducono da soli. La compattazione recupera lo "
        "spazio inutilizzato.",
    ),
    "vhdx.compact": ("Compact selected…", "Compatta selezionato…"),
    "vhdx.other": (
        "Belongs to another product: not compacted by DiskDiet.",
        "Appartiene a un altro prodotto: DiskDiet non lo compatta.",
    ),
    "vhdx.docker_running": (
        "Docker Desktop is running. Quit it (tray icon → Quit) and try again.",
        "Docker Desktop è in esecuzione. Chiudilo (icona nella barra → Quit) e riprova.",
    ),
    "vhdx.confirm": (
        "Compact this virtual disk?\n\n{path}\n\nThis will:\n"
        "1. run “wsl --shutdown” (closes every running WSL distribution and container);\n"
        "2. ask for administrator rights (UAC prompt);\n"
        "3. run diskpart “compact vdisk” on the file.\n\n"
        "Data inside the disk is not deleted. It can take several minutes.",
        "Compattare questo disco virtuale?\n\n{path}\n\nVerrà eseguito:\n"
        "1. “wsl --shutdown” (chiude ogni distribuzione WSL e container attivo);\n"
        "2. richiesta di diritti di amministratore (finestra UAC);\n"
        "3. diskpart “compact vdisk” sul file.\n\n"
        "I dati nel disco non vengono eliminati. Può richiedere diversi minuti.",
    ),
    "vhdx.started": (
        "diskpart is running in its own window. Scan again when it closes.",
        "diskpart è in esecuzione nella sua finestra. Analizza di nuovo quando si chiude.",
    ),
    "kind.docker": ("Docker", "Docker"),
    "kind.wsl": ("WSL", "WSL"),
    "kind.other": ("Other", "Altro"),
    # duplicates
    "dup.find": ("Find duplicates", "Cerca duplicati"),
    "dup.hint": (
        "Compares files of 1 MB or more by content. Windows and program folders are excluded.",
        "Confronta per contenuto i file da 1 MB in su. Cartelle di Windows e dei programmi escluse.",
    ),
    "dup.progress": ("Comparing… group {i:,} of {n:,}", "Confronto… gruppo {i:,} di {n:,}"),
    "dup.summary": (
        "{groups:,} groups, {size} recoverable.",
        "{groups:,} gruppi, {size} recuperabili.",
    ),
    "dup.group": ("{n} copies × {size} — {wasted} recoverable", "{n} copie × {size} — {wasted} recuperabili"),
    "dup.trash": ("Move checked to Recycle Bin…", "Sposta selezionati nel Cestino…"),
    "dup.keep_one": (
        "Leave at least one copy unchecked in every group.",
        "Lascia almeno una copia non selezionata in ogni gruppo.",
    ),
    "dup.confirm": (
        "Move {n:,} files ({size}) to the Recycle Bin?",
        "Spostare {n:,} file ({size}) nel Cestino?",
    ),
}


# ---- added with settings, guided checks, the journal, commands and updates ------------
S.update({
    "ui.close": ("Close", "Chiudi"),
    "ui.settings": ("Settings", "Impostazioni"),
    "ui.admin": ("Administrator", "Amministratore"),
    "ui.run_admin": ("Restart as administrator", "Riavvia come amministratore"),
    "ui.run_admin_tip": (
        "Needed to read every folder, to run system commands and to delete protected "
        "leftovers. Windows will ask for confirmation.",
        "Serve per leggere tutte le cartelle, eseguire i comandi di sistema ed eliminare "
        "residui protetti. Windows chiederà conferma.",
    ),
    "tab.log": ("Deleted files", "File eliminati"),
    "col.when": ("When", "Quando"),
    "col.how": ("How", "Come"),
    "col.state": ("State", "Stato"),
    "action.review": ("Guided check", "Controllo guidato"),
    "file.protected": ("Protected: DiskDiet never deletes this", "Protetta: DiskDiet non la elimina mai"),
    "file.exclude": ("Never touch this (add to exclusions)", "Non toccare mai (aggiungi alle esclusioni)"),
    "file.trash_confirm": (
        "Move to the Recycle Bin?\n\n{path}\n{size}",
        "Spostare nel Cestino?\n\n{path}\n{size}",
    ),
    "rec.review": ("Guided check…", "Controllo guidato…"),
    "rec.result_bin": (
        "{size} are now in the Recycle Bin: the space is freed when you empty it. Until then "
        "you can restore them from the “Deleted files” tab.",
        "{size} sono ora nel Cestino: lo spazio si libera quando lo svuoti. Fino ad allora "
        "puoi ripristinarli dalla scheda “File eliminati”.",
    ),
    # commands and terminal
    "cmd.need_admin": (
        "This command needs administrator rights.\n\nRestart DiskDiet as administrator now? "
        "You will need to scan again.",
        "Questo comando richiede i diritti di amministratore.\n\nRiavviare DiskDiet come "
        "amministratore adesso? Dovrai ripetere l'analisi.",
    ),
    "cmd.bad_value": (
        "Use only letters, digits and . _ : / - (no spaces).",
        "Usa solo lettere, cifre e . _ : / - (senza spazi).",
    ),
    "cmd.confirm": (
        "This changes your system. Run it?\n\n{line}",
        "Questo comando modifica il sistema. Eseguirlo?\n\n{line}",
    ),
    "term.running": ("Running…", "In esecuzione…"),
    "term.stop": ("Stop", "Interrompi"),
    "term.exit": ("Finished with exit code {code}.", "Terminato con codice di uscita {code}."),
    "term.not_found": (
        "Command not found: the program is not installed or not on PATH.",
        "Comando non trovato: il programma non è installato o non è nel PATH.",
    ),
    # guided check
    "rev.delete": ("Delete (Recycle Bin)", "Elimina (Cestino)"),
    "rev.move": ("Move to {drive}", "Sposta su {drive}"),
    "rev.moving": ("Move", "Sposta"),
    "rev.keep": ("Keep", "Tieni"),
    "rev.back": ("Back", "Indietro"),
    "rev.keep_rest": ("Keep all the rest", "Tieni tutti i restanti"),
    "rev.execute": ("Do it", "Esegui"),
    "rev.change_dest": ("Change destination…", "Cambia destinazione…"),
    "rev.counter": ("Item {i} of {n}", "Elemento {i} di {n}"),
    "rev.detail": (
        "{size} — last modified {modified}\n{path}",
        "{size} — ultima modifica {modified}\n{path}",
    ),
    "rev.sum_delete": (
        "To the Recycle Bin: {n} items, {size}.",
        "Nel Cestino: {n} elementi, {size}.",
    ),
    "rev.sum_move": (
        "To move: {n} items, {size}, into {dest} (copied, verified, then removed here).",
        "Da spostare: {n} elementi, {size}, in {dest} (copiati, verificati, poi rimossi da qui).",
    ),
    "rev.sum_keep": ("Kept: {n} items.", "Tenuti: {n} elementi."),
    "rev.empty": ("Nothing left to check here.", "Non c'è più nulla da controllare qui."),
    # programs
    "prog.uninstall": ("Uninstall…", "Disinstalla…"),
    "prog.confirm": (
        "Start the uninstaller of “{name}”?\n\nIts own window will guide you.",
        "Avviare il programma di disinstallazione di “{name}”?\n\nLa sua finestra ti guiderà.",
    ),
    "prog.confirm_settings": (
        "“{name}” has no uninstaller of its own. Open Windows “Installed apps” to remove it?",
        "“{name}” non ha un proprio disinstallatore. Aprire “App installate” di Windows per "
        "rimuoverlo?",
    ),
    "prog.hint": (
        "Sizes are those declared by each installer and can be missing or low. "
        "Select a program and press Uninstall.",
        "Le dimensioni sono quelle dichiarate dagli installer e possono mancare o essere basse. "
        "Seleziona un programma e premi Disinstalla.",
    ),
    # journal and Recycle Bin
    "log.hint": (
        "Everything DiskDiet removed or moved. Items in the Recycle Bin and moved items can "
        "be put back where they were; temporary files were deleted for good.",
        "Tutto ciò che DiskDiet ha rimosso o spostato. Gli elementi nel Cestino e quelli "
        "spostati si possono rimettere dov'erano; i file temporanei sono eliminati per sempre.",
    ),
    "log.restore": ("Restore selected", "Ripristina selezionato"),
    "log.undo_last": ("Undo last cleanup", "Annulla ultima pulizia"),
    "log.undo_confirm": (
        "Put back everything the last cleanup sent to the Recycle Bin or moved to another "
        "drive? Items deleted for good cannot come back.",
        "Rimettere a posto tutto ciò che l'ultima pulizia ha mandato nel Cestino o spostato "
        "su un altro disco? Gli elementi eliminati definitivamente non possono tornare.",
    ),
    "log.undo_done": ("{n:,} items restored.", "{n:,} elementi ripristinati."),
    "log.undo_failed": ("{n:,} could not be restored (details below).",
                        "{n:,} non sono stati ripristinati (dettagli sotto)."),
    "log.restore_failed": ("Could not restore: {err}", "Impossibile ripristinare: {err}"),
    "log.restored": ("Restored:\n{path}", "Ripristinato:\n{path}"),
    "log.mode.trash": ("Recycle Bin", "Cestino"),
    "log.mode.permanent": ("Deleted for good", "Eliminato definitivamente"),
    "log.mode.moved": ("Moved to another drive", "Spostato su altro disco"),
    "log.state.removed": ("Removed", "Rimosso"),
    "log.state.restored": ("Restored", "Ripristinato"),
    "bin.open": ("Open Recycle Bin", "Apri Cestino"),
    "bin.empty": ("Empty Recycle Bin…", "Svuota Cestino…"),
    "bin.empty_now": ("Empty Recycle Bin now ({size})", "Svuota Cestino ora ({size})"),
    "bin.empty_confirm": (
        "Permanently delete everything in the Recycle Bin ({size})?\n\n"
        "This cannot be undone, and includes files you deleted outside DiskDiet.",
        "Eliminare definitivamente tutto il contenuto del Cestino ({size})?\n\n"
        "Non si può annullare, e include i file eliminati fuori da DiskDiet.",
    ),
    # closing summary
    "close.total": (
        "In this session DiskDiet removed {n:,} items: {size}.",
        "In questa sessione DiskDiet ha rimosso {n:,} elementi: {size}.",
    ),
    "close.trashed": (
        "{size} were MOVED TO THE RECYCLE BIN. That space is not free yet: empty the bin to "
        "free it for good, or restore the files from it if anything misbehaves.",
        "{size} sono stati SPOSTATI NEL CESTINO. Quello spazio non è ancora libero: svuota il "
        "Cestino per liberarlo definitivamente, oppure ripristina i file da lì in caso di anomalie.",
    ),
    "close.permanent": (
        "{size} of temporary files were deleted for good: already free.",
        "{size} di file temporanei sono stati eliminati definitivamente: già liberi.",
    ),
    "close.moved": ("{size} were moved to another drive.", "{size} sono stati spostati su un altro disco."),
    # settings
    "set.general": ("General", "Generale"),
    "set.exclusions": ("Exclusions", "Esclusioni"),
    "set.exclude_hint": (
        "DiskDiet never proposes, removes, moves or compresses these folders and files, "
        "nor anything inside them.",
        "DiskDiet non propone, rimuove, sposta né comprime mai queste cartelle e questi file, "
        "né ciò che contengono.",
    ),
    "set.exclude_folder": ("Add folder…", "Aggiungi cartella…"),
    "set.exclude_file": ("Add file…", "Aggiungi file…"),
    "set.exclude_remove": ("Remove", "Rimuovi"),
    "set.about": ("About", "Informazioni"),
    "set.theme": ("Theme", "Tema"),
    "set.theme.system": ("Same as Windows", "Come Windows"),
    "set.theme.light": ("Light", "Chiaro"),
    "set.theme.dark": ("Dark", "Scuro"),
    "set.language": ("Language", "Lingua"),
    "set.lang.auto": ("Same as Windows", "Come Windows"),
    "set.old_days": ("A file is “old” after (days)", "Un file è “vecchio” dopo (giorni)"),
    "set.dup_min": ("Smallest file compared for duplicates", "File più piccolo confrontato per i duplicati"),
    "set.check_updates": ("Check for updates at startup", "Cerca aggiornamenti all'avvio"),
    "set.privacy": (
        "The update check is DiskDiet's only network access: an anonymous request to GitHub. "
        "Nothing about you or your files is sent.",
        "La ricerca aggiornamenti è l'unico accesso alla rete di DiskDiet: una richiesta "
        "anonima a GitHub. Non viene inviato nulla su di te o sui tuoi file.",
    ),
    "about.credits": (
        "Free and open source, MIT License.<br>Source, issues and releases: "
        "<a href='{repo}'>{repo}</a><br><br>Built with Python, Qt for Python (PySide6, LGPL) "
        "and PyInstaller.<br>Thanks to everyone who contributes cleanup rules.",
        "Libero e open source, licenza MIT.<br>Sorgente, segnalazioni e versioni: "
        "<a href='{repo}'>{repo}</a><br><br>Realizzato con Python, Qt for Python (PySide6, LGPL) "
        "e PyInstaller.<br>Grazie a chi contribuisce con regole di pulizia.",
    ),
    "about.check": ("Check for updates", "Cerca aggiornamenti"),
    # updates
    "upd.checking": ("Checking…", "Controllo in corso…"),
    "upd.available": ("DiskDiet {version} is available.", "È disponibile DiskDiet {version}."),
    "upd.current": ("You have the latest version.", "Hai l'ultima versione."),
    "upd.none": ("No release has been published yet.", "Nessuna versione è stata ancora pubblicata."),
    "upd.failed": ("Update check failed: {err}", "Ricerca aggiornamenti non riuscita: {err}"),
    "upd.notes": ("What's new", "Novità"),
    "upd.install": ("Download and install", "Scarica e installa"),
    "upd.open_page": ("Open download page", "Apri pagina di download"),
    "upd.downloading": ("Downloading the update…", "Download dell'aggiornamento…"),
    "upd.confirm": (
        "Download DiskDiet {version} from GitHub, check its SHA-256, replace this exe and "
        "restart?",
        "Scaricare DiskDiet {version} da GitHub, verificarne lo SHA-256, sostituire questo exe "
        "e riavviare?",
    ),
    "dup.progress": ("Comparing… {pct}%", "Confronto… {pct}%"),
    "dup.hint": (
        "Compares files by content, in parallel. Windows and program folders are excluded.",
        "Confronta i file per contenuto, in parallelo. Cartelle di Windows e dei programmi escluse.",
    ),
})
S.update({
    "ui.removing": ("Removing {i:,} of {n:,} — {path}", "Rimozione {i:,} di {n:,} — {path}"),
    "rec.tool": ("Open program / Windows tool", "Apri programma / strumento Windows"),
    "cmd.restore_point": (
        "Create a restore point first (system files and registry; not your own files)",
        "Crea prima un punto di ripristino (file di sistema e registro; non i tuoi file)",
    ),
    "term.aborted": (
        "Stopped here: this step failed, so the following ones were not run.",
        "Interrotto qui: questo passaggio è fallito, quindi i successivi non sono stati eseguiti.",
    ),
    "about.open_data": ("Open the settings and log folder", "Apri la cartella di impostazioni e log"),
})
for _unused in ("action.open", "rec.copy", "rec.command"):
    S.pop(_unused, None)
