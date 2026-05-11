# Releasing OpenForge

This document is for **maintainers** cutting a new release of the OpenForge
sign-off binaries (`openforge-drc`, `openforge-lvs`, `openforge-xrc`) and
the slim Docker image. End users should read the install instructions in
the project README.

The signoff release is driven by `.github/workflows/release-signoff.yml` and
fires on any tag matching `v*.*.*`.

---

## TL;DR

```bash
# 1. Pick the next version
NEW=v0.3.0

# 2. Bump versions in source
#    - Cargo.toml         workspace.package.version
#    - packages/*/pyproject.toml   project.version (each package)

# 3. Commit and tag
git commit -am "release: ${NEW}"
git tag ${NEW}
git push origin main --tags

# 4. Watch CI
gh run watch
```

When the workflow finishes, the release page at
`https://github.com/dyber-pqc/OpenForge/releases/tag/${NEW}` will have:

- `openforge-signoff-linux-x86_64.tar.gz`
- `openforge-signoff-macos-x86_64.tar.gz`
- `openforge-signoff-windows-x86_64.zip`
- `checksums.txt`
- Auto-generated release notes from the merged PRs / commits since the
  previous tag.

The Docker image will be available at:

- `ghcr.io/dyber-pqc/openforge:${NEW}`
- `ghcr.io/dyber-pqc/openforge:latest`

---

## Step-by-step

### 1. Pick a version number

We follow [SemVer](https://semver.org). For the public sign-off binaries
the rules are:

| Change                             | Bump  |
|------------------------------------|-------|
| Bug fixes, internal cleanup        | patch |
| New backwards-compatible features  | minor |
| CLI flag removed/renamed, output format change | major |

### 2. Bump versions in source

Edit each of the following so the embedded `--version` string matches the
tag (without the leading `v`):

```toml
# Cargo.toml
[workspace.package]
version = "0.3.0"
```

```toml
# packages/core/pyproject.toml, packages/cli/pyproject.toml, etc.
[project]
version = "0.3.0"
```

Run `cargo build --release -p openforge-drc -p openforge-lvs -p openforge-xrc`
locally and confirm `target/release/openforge-drc --version` prints the new
number.

### 3. Commit & tag

```bash
git add Cargo.toml packages/*/pyproject.toml
git commit -m "release: v0.3.0"
git tag v0.3.0 -m "OpenForge v0.3.0"
git push origin main
git push origin v0.3.0
```

Pushing the tag triggers `release-signoff.yml`. Pushing the branch first
(without the tag) is a good safety net so CI runs and fails *before* the
tag goes out.

### 4. Watch the workflow

```bash
gh run watch                 # auto-attach to the running workflow
gh run view --log-failed     # if anything red
```

Pipeline shape:

1. **build** (matrix: ubuntu-latest, macos-latest, windows-latest) — `cargo build --release`,
   strip, package as `.tar.gz` / `.zip`, upload artifact.
2. **smoke-test** (same matrix) — download archive, extract, run
   `--version` on each binary on its native runner. Fails the release if
   the binaries don't run.
3. **docker** — build `installer/Dockerfile.release` (multi-stage, slim)
   and push to GHCR as both `:${TAG}` and `:latest`.
4. **publish** — collect all archives, write a combined
   `checksums.txt`, create / update the GitHub Release with
   auto-generated notes.

### 5. Edit release notes (optional)

Once `publish` is green, open the release page and tweak the
auto-generated notes. The "What's Changed" section is filled from
`generate_release_notes: true` (squash-merge PR titles since the previous
tag); add a short prose summary at the top if there are headline items.

### 6. Verify install paths

Sanity-check both install scripts against the freshly cut release:

```bash
# Linux/macOS
curl -fsSL https://raw.githubusercontent.com/dyber-pqc/OpenForge/main/scripts/install.sh | bash

# Windows PowerShell
irm https://raw.githubusercontent.com/dyber-pqc/OpenForge/main/scripts/install.ps1 | iex
```

Both should download the new tag, verify checksums, and end with the
three `--version` lines printed.

### 7. Docker spot-check

```bash
docker pull ghcr.io/dyber-pqc/openforge:v0.3.0
docker run --rm ghcr.io/dyber-pqc/openforge:v0.3.0 openforge-drc --version
```

---

## Pre-release tags

Tags containing `-rc`, `-beta`, or `-alpha` (e.g. `v0.3.0-rc1`) are
automatically marked as **prerelease** on GitHub. The `:latest` Docker
tag still updates — bear that in mind if you ship rcs.

## Re-running a failed release

If the workflow fails partway:

1. Fix the underlying issue on `main`.
2. Delete the broken tag locally and on the remote:
   ```bash
   git tag -d v0.3.0
   git push origin :refs/tags/v0.3.0
   ```
3. Re-tag and push.

`softprops/action-gh-release@v2` recreates the release from scratch on a
fresh tag push. For partial recovery (e.g. only Docker failed) you can
also use the `workflow_dispatch` trigger and pass the tag manually.

## Permissions checklist

The workflow needs:

- `contents: write` — to create the GitHub Release (granted in workflow).
- `packages: write` — to push to GHCR (granted in workflow).
- `secrets.GITHUB_TOKEN` — automatic, no action required.

There are no third-party secrets for the signoff release. The broader
`release.yml` (PyPI, etc.) has its own secrets — see that workflow for
details.

## Coexistence with `release.yml`

The repo also has a broader `release.yml` that builds Python wheels,
MSIs, DMGs, conda packages, and publishes to PyPI on the same `v*` tag
pattern. Both workflows append to the same GitHub Release; there is no
conflict because they upload disjoint files. If you want to ship just
sign-off binaries (no full installers), trigger `release-signoff.yml`
manually via `workflow_dispatch` with the desired tag.
