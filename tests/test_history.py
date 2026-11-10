from diskdiet import history
from diskdiet.scanner import scan

MB = 1 << 20


def test_growth_points_at_the_folder_that_changed(tmp_path, make, monkeypatch):
    monkeypatch.setattr(history, "MIN_FOLDER", 1)
    monkeypatch.setattr(history, "MIN_CHANGE", 100)
    make("Local/App/cache/old.bin", 50)
    make("Local/Other/keep.bin", 10)
    first = history.save(scan(str(tmp_path)))
    make("Local/App/cache/new.bin", 500)  # the growth is here, not in Local or App
    make("Local/Fresh/data.bin", 300)  # a folder that did not exist before
    root = str(tmp_path)
    assert history.previous(root) == first
    second = history.save(scan(root))
    rows = history.growth(first, second)
    cache = str(tmp_path / "Local" / "App" / "cache")
    assert rows[0] == (cache, 50, 550)
    assert (str(tmp_path / "Local" / "Fresh"), 0, 300) in rows
    assert not any(path == str(tmp_path / "Local" / "App") for path, _a, _b in rows)


def test_history_keeps_the_last_scans_of_each_root(tmp_path, make, monkeypatch):
    monkeypatch.setattr(history, "KEEP", 2)
    make("a/x.bin", 1)
    make("b/y.bin", 1)
    for _ in range(3):
        history.save(scan(str(tmp_path / "a")))
    history.save(scan(str(tmp_path / "b")))
    roots = [e["root"] for e in history.load()]
    assert roots.count(str(tmp_path / "a")) == 2 and roots.count(str(tmp_path / "b")) == 1


def test_damaged_history_lines_are_skipped(tmp_path, make):
    make("a/x.bin", 1)
    history.save(scan(str(tmp_path / "a")))
    with open(history._file(), "a", encoding="utf-8") as f:
        f.write("{half a line")
    assert len(history.load()) == 1


def test_csv_lists_folders_and_files(tmp_path, make):
    import csv
    import io

    from diskdiet import report
    from diskdiet.scanner import MIN_TRACKED_FILE

    make("a/big.bin", MIN_TRACKED_FILE)
    make("a/b/small.txt", 5)
    text = report.to_csv(scan(str(tmp_path)))
    assert text.startswith("\ufeff")
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    kinds = {(r["kind"], r["path"]) for r in rows}
    assert ("folder", str(tmp_path / "a" / "b")) in kinds
    assert ("file", str(tmp_path / "a" / "big.bin")) in kinds
    root = next(r for r in rows if r["path"] == str(tmp_path))
    assert int(root["bytes"]) == MIN_TRACKED_FILE + 5
