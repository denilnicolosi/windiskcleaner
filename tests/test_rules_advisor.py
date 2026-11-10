import os
import time

import pytest

from diskdiet import actions, advisor, rules
from diskdiet.rules import Action, Safety
from diskdiet.scanner import scan
from diskdiet.strings import S
from diskdiet.system import Program

MB = 1 << 20


@pytest.fixture(autouse=True)
def small_thresholds(monkeypatch):
    """Real thresholds are hundreds of MB: tests must not write that much."""
    monkeypatch.setattr(advisor, "ARCHIVE_MIN", 2 * MB)
    monkeypatch.setattr(advisor, "IDLE_PROJECT_MIN", 1000)
    monkeypatch.setattr(advisor, "ORPHAN_MIN", 1000)


def test_catalogue_is_well_formed():
    ids = [r.id for r in rules.RULES]
    assert len(ids) == len(set(ids))
    for rule in rules.RULES:
        assert f"cat.{rule.category}" in S, rule.id
        for text in (rule.title, rule.why):
            assert text if isinstance(text, str) else all(text), rule.id
        if rule.action is Action.DELETE:
            assert rule.safety is Safety.SAFE and rule.paths, rule.id
        if rule.action is Action.GUIDE:
            assert rule.commands or rule.tool, rule.id
        if rule.permanent:
            assert rule.category == "temp", rule.id


def test_deletable_rules_never_point_at_protected_places():
    for rule in rules.RULES:
        if rule.action is Action.DELETE:
            for path in rule.resolve():
                for item in actions.preview([path]):
                    assert not actions.is_protected(item), (rule.id, item)


def test_rule_becomes_recommendation(tmp_path, make, monkeypatch):
    make("temp/a.tmp", 300)
    make("temp/sub/b.tmp", 200)
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    result = scan(str(tmp_path), watch_paths=rules.watch_paths())
    recs = {r.id: r for r in advisor.build(result)}
    temp = recs["user_temp"]
    assert (temp.size, temp.permanent, temp.action) == (500, True, Action.DELETE)
    assert temp.paths == [str(tmp_path / "temp")]


def test_rule_absent_on_this_machine_is_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nothing"))
    recs = {r.id for r in advisor.build(scan(str(tmp_path)))}
    assert "pip_cache" not in recs
    assert "storage_sense" in recs  # tool-only guidance is always offered


def test_archive_heuristics(tmp_path, make, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    now = time.time()
    old = now - 3 * 365 * advisor.DAY
    twin = make("Downloads/Photos.zip", MB)
    (tmp_path / "Downloads" / "Photos").mkdir()
    setup = make("Downloads/setup.exe", MB, mtime=old)
    video = make("Videos/clip.mp4", 2 * MB)
    stale = make("Documents/dataset.bin", 2 * MB, mtime=old)
    make("AppData/Local/thing/cache.bin", 2 * MB, mtime=old)  # not the user's own files
    recs = {r.id: r for r in advisor.build(scan(str(tmp_path)), now=now)}
    assert recs["archive_twins"].paths == [twin]
    assert recs["old_installers"].paths == [setup]
    assert recs["archive_videos"].paths == [video]
    assert recs["archive_old"].paths == [stale]


def test_idle_projects(tmp_path, make, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    now = time.time()
    make("code/old/node_modules/lib.js", 2000, mtime=now - 400 * advisor.DAY)
    make("code/live/node_modules/lib.js", 2000, mtime=now)
    result = scan(str(tmp_path), watch_names=advisor.REGENERABLE)
    recs = {r.id: r for r in advisor.build(result, now=now)}
    assert recs["idle_projects"].paths == [str(tmp_path / "code" / "old" / "node_modules")]


def test_orphans_need_no_matching_program(tmp_path, make, monkeypatch):
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    make("AppData/Local/Leftover/data.bin", advisor.ORPHAN_MIN)
    make("AppData/Local/Arduino15/data.bin", advisor.ORPHAN_MIN)
    make("AppData/Local/Packages/Chatty_abc123/settings.dat", 1)  # a Microsoft Store app
    make("AppData/Local/Chatty-Data/data.bin", advisor.ORPHAN_MIN)
    programs = [Program("Arduino IDE", "Arduino SA", 0, "")]
    recs = {r.id: r for r in advisor.build(scan(str(tmp_path)), programs=programs)}
    assert recs["appdata_orphans"].paths == [os.path.join(str(local), "Leftover")]


TEAMS = "Local/Packages/MSTeams_8wekyb3d8bbwe/LocalCache/Microsoft/MSTeams"


@pytest.mark.parametrize("rule_id, files", [
    ("app_update_leftovers", ["Local/foo-updater/installer.exe", "Local/foo-updater/pending/u.exe",
                              "Local/Bar/packages/Bar-1.0-full.nupkg"]),
    ("shader_caches", ["LocalLow/NVIDIA/DXCache/a.bin", "Roaming/NVIDIA/ComputeCache/b.bin"]),
    ("google_earth_cache", ["LocalLow/Google/GoogleEarth/Cache/tiles.dat"]),
    ("teams_cache", [f"{TEAMS}/EBWebView/WV2Profile_tfw/Cache/a", f"{TEAMS}/Logs/x.log"]),
    ("chrome_cache", ["Local/Google/Chrome/User Data/Default/Service Worker/CacheStorage/a",
                      "Local/Google/Chrome/User Data/component_crx_cache/b"]),
    ("opera_cache", ["Local/Opera Software/Opera Stable/Cache/a",
                     "Roaming/Opera Software/Opera Stable/Code Cache/b"]),
    ("crash_dumps", ["Roaming/Code/Crashpad/reports/a.dmp"]),
    ("vscode_cache", ["Local/Microsoft/vscode-cpptools/ipch/a.ipch"]),
    ("teams_classic", ["Roaming/Microsoft/Teams/Service Worker/a"]),
    ("clipchamp", ["Local/Packages/Clipchamp.Clipchamp_yxz26nhyzhsrt/LocalState/EBWebView/a"]),
    ("pub_cache", ["Local/Pub/Cache/hosted/a"]),
    ("pnpm_store", ["Local/pnpm/store/v3/a"]),
    ("python_versions", ["Local/Programs/Python/Python39/python.exe"]),
    ("azure_func_tools", ["Local/AzureFunctionsTools/Releases/4.0.0/func.exe"]),
])
def test_appdata_rules(rule_id, files, tmp_path, make, monkeypatch):
    profile = tmp_path / "me"
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("LOCALAPPDATA", str(profile / "AppData" / "Local"))
    monkeypatch.setenv("APPDATA", str(profile / "AppData" / "Roaming"))
    for rel in files:
        make(f"me/AppData/{rel}", 100)
    make(f"me/AppData/{TEAMS}/Backgrounds/mine.png", 7)  # the user's own: never a cache
    make("me/AppData/Local/Google/Chrome/User Data/Default/IndexedDB/site.db", 7)
    result = scan(str(tmp_path), watch_paths=rules.watch_paths())
    rec = {r.id: r for r in advisor.build(result)}[rule_id]
    assert rec.size == 100 * len(files)


@pytest.mark.skipif(os.name != "nt", reason="junctions")
def test_wildcards_do_not_follow_junctions(tmp_path, make):
    import _winapi

    make("Local/App/Cache/a.bin", 5)
    try:  # like "Dati applicazioni" -> %LOCALAPPDATA% on Italian Windows
        _winapi.CreateJunction(str(tmp_path / "Local"), str(tmp_path / "Local" / "Legacy"))
    except OSError:
        pytest.skip("cannot create junctions here")
    rule = rules.Rule("t", "temp", (rf"{tmp_path}\Local\*\*\Cache",), Safety.SAFE, Action.DELETE,
                      "t", "t")
    assert rule.resolve() == []  # Local\Legacy\App\Cache is Local\App\Cache seen again
    rule = rules.Rule("t", "temp", (rf"{tmp_path}\Local\*\Cache",), Safety.SAFE, Action.DELETE,
                      "t", "t")
    assert rule.resolve() == [str(tmp_path / "Local" / "App" / "Cache")]


def test_review_shows_last_write_inside_a_folder(tmp_path, make, monkeypatch):
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    old = time.time() - 900 * advisor.DAY
    make("AppData/Local/Leftover/data.bin", advisor.ORPHAN_MIN, mtime=old)
    result = scan(str(tmp_path))
    recs = {r.id: r for r in advisor.build(result, programs=[Program("X", "Y", 0, "")])}
    [item] = advisor.review_items(recs["appdata_orphans"], result)
    assert item.mtime == pytest.approx(old)


def test_new_rules_name_the_program_to_close():
    procs = {r.id: r.process for r in rules.RULES}
    assert procs["chrome_cache"] == "chrome.exe" and procs["teams_cache"] == "ms-teams.exe"


@pytest.mark.skipif(os.name != "nt", reason="tasklist")
def test_running_finds_this_process():
    import sys

    from diskdiet import system

    assert system.running(os.path.basename(sys.executable))
    assert not system.running("surely-not-running-diskdiet-test.exe")


def test_build_folders_need_their_project_file(tmp_path, make, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    old = time.time() - 400 * advisor.DAY
    make("code/rust/Cargo.toml", 1)
    make("code/rust/target/debug/app.exe", 2000, mtime=old)
    make("code/web/package.json", 1)
    make("code/web/.next/cache/x", 2000, mtime=old)
    make("code/net/App.csproj", 1)
    make("code/net/obj/x.dll", 2000, mtime=old)
    make("Documents/target/plan.docx", 2000, mtime=old)  # the user's own "target" folder
    make("Documents/bin/tool.exe", 2000, mtime=old)
    result = scan(str(tmp_path), watch_names=advisor.REGENERABLE)
    rec = {r.id: r for r in advisor.build(result)}["idle_projects"]
    code = tmp_path / "code"
    assert sorted(rec.paths) == sorted(
        str(p) for p in (code / "rust" / "target", code / "web" / ".next", code / "net" / "obj")
    )


def test_leftovers_of_a_removed_program(tmp_path, make, monkeypatch):
    tmp_path = tmp_path / "me" / "AppData"  # inside the (fake) profile, like the real ones
    for var, rel in (("LOCALAPPDATA", "Local"), ("APPDATA", "Roaming"),
                     ("PROGRAMDATA", "ProgramData")):
        monkeypatch.setenv(var, str(tmp_path / rel))
    monkeypatch.setenv("USERPROFILE", str(tmp_path.parent))
    make("me/AppData/Local/Postman/app-9.31.0/Postman.exe", 50)
    make("me/AppData/Roaming/Postman/config.json", 5)
    make("me/AppData/Roaming/PostgreSQL/pgpass.conf", 5)  # another program, still installed
    make("me/AppData/Roaming/JetBrains/PyCharm2025.1/options.xml", 5)
    make("me/AppData/Roaming/JetBrains/PyCharm2025.2/options.xml", 5)  # the version still installed
    make("me/AppData/ProgramData/Unrelated/x", 5)
    installed = [Program("PostgreSQL 16", "PostgreSQL", 0, ""),
                 Program("PyCharm 2025.2", "JetBrains s.r.o.", 0, "")]
    postman = Program("Postman x64 9.31.0", "Postman", 0, "", "",
                      str(tmp_path / "Local" / "Postman"))
    rec = advisor.leftovers(postman, installed)
    assert sorted(rec.paths) == sorted([str(tmp_path / "Local" / "Postman"),
                                        str(tmp_path / "Roaming" / "Postman")])
    old = Program("PyCharm 2025.1", "JetBrains s.r.o.", 0, "")
    rec = advisor.leftovers(old, installed)
    assert rec.paths == [str(tmp_path / "Roaming" / "JetBrains" / "PyCharm2025.1")]
    broad = Program("Tool", "Tool", 0, "", "", str(tmp_path / "Local"))  # bad InstallLocation
    assert advisor.leftovers(broad, installed) is None
