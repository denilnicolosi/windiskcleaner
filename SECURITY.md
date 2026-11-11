# Security

WinDiskCleaner removes files, so these problems are treated as security issues:

- a way to make it delete something outside the folder a rule points at, or inside the
  never-touch list (`actions.is_protected`);
- a rule marked *Safe* that loses user data or breaks a program;
- a way to make it run a command that is not in its catalogue, or to smuggle extra
  arguments through a value typed by the user;
- a way to make the updater install a file that is not a release of this repository.

Please report them privately through GitHub's **Report a vulnerability** button on the
Security tab of this repository, not in a public issue. Include the WinDiskCleaner version, the
rule or action involved and the steps to reproduce.

Only the latest release is supported.

## What WinDiskCleaner does not do

- It collects no data. Its only network access is the update check: anonymous requests
  to this repository's GitHub Releases, which can be disabled in Settings. A downloaded
  update is installed only if its SHA-256 matches the one published with the release.
- It does not ask for administrator rights by itself. The user can restart it elevated
  with a button; virtual disk compaction shows one UAC prompt after its confirmation.
- It never runs a command on its own: only when the user clicks its button.

## Checking a download

Release executables are built by GitHub Actions from the tagged commit. See
[docs/RELEASING.md](docs/RELEASING.md#verifying-a-download).
