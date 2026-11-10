# Releasing

A release is a git tag. GitHub Actions does the rest.

## Steps

1. Set the new version in `pyproject.toml` (the only place it lives).
2. In `CHANGELOG.md`, rename *Unreleased* to `## [X.Y.Z] - YYYY-MM-DD` and open a new empty
   *Unreleased* section.
3. `uv sync` (refreshes `uv.lock`), `uv run pytest`, `uv run ruff check`.
4. Commit: `Release X.Y.Z`.
5. Tag and push:

   ```
   git tag vX.Y.Z
   git push origin main vX.Y.Z
   ```

`.github/workflows/release.yml` then:

- fails if the tag does not match the version in `pyproject.toml`;
- runs lint and tests, builds `WinDiskCleaner-X.Y.Z.exe`;
- signs it, if signing is configured (below);
- writes `WinDiskCleaner-X.Y.Z.exe.sha256` and a GitHub build provenance attestation;
- publishes the GitHub Release with the notes taken from the `CHANGELOG.md` section.

If the workflow fails, fix the cause, delete the tag (`git push origin :vX.Y.Z`,
`git tag -d vX.Y.Z`) and tag again. Never reuse a version number that was published.

## Versioning

Semantic versioning. A new rule or heuristic is a minor version; a rule that turns out to
be unsafe is fixed in a patch release straight away.

## Verifying a download

```
gh attestation verify WinDiskCleaner-X.Y.Z.exe --repo <owner>/windiskcleaner
```

proves the file was built by this repository's workflow from the tagged commit.

## Code signing

Unsigned executables trigger Windows SmartScreen. A self-signed certificate does not help;
the certificate must come from a trusted authority.

The workflow is prepared for [SignPath Foundation](https://signpath.org/), which signs open
source projects for free. It is skipped until configured:

1. Publish the repository (public, OSI license, working release build).
2. Apply at <https://signpath.org/apply>. Approval is manual and can take days or weeks.
3. In SignPath: create the project and a signing policy, link the GitHub repository as a
   trusted build system, create an API token for CI.
4. In the GitHub repository settings add:
   - secret `SIGNPATH_API_TOKEN`
   - variables `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`,
     `SIGNPATH_SIGNING_POLICY_SLUG`
5. Check the inputs of the `signpath/github-action-submit-signing-request` step in
   `release.yml` against SignPath's current documentation, then release as usual.

Until then every release note states that the exe is not signed.
