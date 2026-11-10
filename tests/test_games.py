import json
import os

from diskdiet import games


def test_vdf_reads_nested_keys_and_escaped_paths():
    text = r'"libraryfolders" { "0" { "path"  "D:\\SteamLibrary" } }'  # as Steam writes it
    assert games.vdf(text) == {"libraryfolders": {"0": {"path": r"D:\SteamLibrary"}}}


def test_steam_games_from_every_library(tmp_path, make):
    steam, extra = tmp_path / "Steam", tmp_path / "Games2"
    lib = str(extra).replace("\\", "\\\\")
    make("Steam/steamapps/libraryfolders.vdf",
         content=f'"libraryfolders" {{ "0" {{ "path" "{lib}" }} }}'.encode())
    make("Steam/steamapps/appmanifest_10.acf", content=(
        b'"AppState" { "appid" "10" "name" "Old Game" "installdir" "OldGame" '
        b'"SizeOnDisk" "5000" "LastPlayed" "1600000000" }'))
    make("Games2/steamapps/appmanifest_20.acf", content=(
        b'"AppState" { "appid" "20" "name" "New Game" "installdir" "NewGame" '
        b'"SizeOnDisk" "9000" }'))
    found = sorted(games.steam_games(str(steam)), key=lambda g: g.app_id)
    assert [(g.name, g.size, g.last_played, g.app_id) for g in found] == [
        ("Old Game", 5000, 1600000000.0, "10"), ("New Game", 9000, 0.0, "20")]
    assert found[1].path == os.path.join(str(extra), "steamapps", "common", "NewGame")


def test_epic_games_from_manifests(tmp_path, make):
    make("Manifests/abc.item", content=json.dumps({
        "DisplayName": "Some Game", "InstallLocation": r"E:\Epic\SomeGame",
        "InstallSize": 1234, "AppName": "Fennel"}).encode())
    make("Manifests/broken.item", content=b"{not json")
    [game] = games.epic_games(str(tmp_path / "Manifests"))
    assert (game.name, game.launcher, game.size, game.app_id) == (
        "Some Game", "Epic", 1234, "Fennel")
