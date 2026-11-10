# Adding a cleanup rule

A rule is one entry in `RULES` in [`src/diskdiet/rules.py`](../src/diskdiet/rules.py). No
other code changes are needed: the scanner sizes the folder, the advisor turns it into a
recommendation, the UI shows it.

```python
Rule(
    "poetry_cache",                         # unique id
    "dev",                                  # category: temp, browser, dev, apps, system
    (rf"{L}\pypoetry\Cache",),              # paths: %VARIABLES% and * wildcards allowed
    Safety.SAFE, Action.DELETE,
    "Poetry cache",                         # title: a string, or (english, italian)
    (
        "Downloaded packages kept to speed up installs. Downloaded again when needed.",
        "Pacchetti scaricati per velocizzare le installazioni. Si riscaricano quando servono.",
    ),
),
```

## Choosing safety and action

| If removing it… | Use |
|---|---|
| loses nothing: the program rebuilds it by itself | `Safety.SAFE`, `Action.DELETE` |
| costs a long re-download, a reconfiguration, or could hold user work | `Safety.CAUTION`, `Action.REVIEW` |
| should be done with the program's own command | `Safety.CAUTION`, `Action.GUIDE` + `commands=` |
| is Windows' own business | `Safety.SYSTEM`, `Action.GUIDE` + `commands=` and/or `tool=` |

When unsure, choose `CAUTION`. A `SAFE` rule must be safe on every machine, not just yours.

- `Action.DELETE` on a folder empties it and keeps the folder. On a file pattern
  (`%USERPROFILE%\*.hprof`) it removes the matching files.
- `Action.REVIEW` opens the guided check. For a catalogue rule it asks about each thing
  *inside* the rule's folders (each emulator, each extension…). Give it a question in
  `QUESTIONS` at the bottom of `rules.py`, in both languages; the buttons are always
  Delete / Keep, so phrase it so that either answer makes sense ("Do you still use this
  emulator?").
- `commands` are buttons. Each is a `Command`:

  ```python
  Command(("List models", "Elenca modelli"), ("ollama", "list")),
  Command(("Remove a model…", "Rimuovi un modello…"), ("ollama", "rm", "{value}"),
          changes=True, ask=("Model name", "Nome del modello")),
  ```

  `argv` is a tuple of arguments, never a shell line: no pipes, no `&&`. `changes=True`
  if it modifies anything (the user confirms first). `admin=True` if it needs an elevated
  prompt. `ask` prompts for `{value}`, which must be a plain name; a command with `ask`
  must be `changes=True`. Prefer offering a read-only command (list, analyse) next to a
  destructive one. Never add a command that deletes user data without saying so in its
  label. When the tool can list what `{value}` may be, add `options_from=` (a read-only
  command) and `options_pattern=` (a regex with one group, tried on each output line):
  the user then ticks items in a list instead of typing, and the command runs once per
  ticked item.
- `tool` is opened on request: an executable name, a `shell:` folder or an `ms-settings:`
  URI. For a program installed in different places write the candidates separated by
  `|` (see `lmstudio`). If a program has its own way of removing things and deleting its
  folders by hand breaks it, use `Action.GUIDE` with `tool=` rather than `REVIEW`.
- `permanent=True` (skip the Recycle Bin) is reserved for the `temp` category.
- Never point a rule inside `C:\Windows` (other than `Temp`) or `Program Files`:
  `actions.is_protected` would refuse to delete there anyway.

## The explanation

Say what the data is, what happens after removal, and what the user should do first
(“Close the browser first”). Two or three sentences, both languages.

## Checklist

- [ ] Verified on a real installation where the folder is and that the program recovers.
- [ ] `uv run pytest` passes (`test_catalogue_is_well_formed` checks every rule).
- [ ] Line added under *Unreleased* in `CHANGELOG.md`.
