# OpenForge Installer Build Scripts

This directory contains the PyInstaller spec and per-platform build scripts
used to produce shippable installers of the OpenForge EDA desktop app.

## Layout

```
installer/
├── openforge.spec       # PyInstaller spec, shared by all platforms
├── build_windows.py     # Windows: NSIS or MSIX
├── build_macos.py       # macOS: codesigned, notarized .dmg
├── build_linux.py       # Linux: AppImage, Flatpak, Snap
└── README.md            # this file
```

## Common prerequisites

- Python 3.12 or newer
- `pip install pyinstaller`
- A working `uv sync` of the OpenForge workspace so that all desktop /
  core / crypto packages are importable
- The PySide6 wheel for the target platform

## Windows

```powershell
python installer\build_windows.py            # NSIS installer (default)
python installer\build_windows.py --msix     # MSIX package
```

Extra prerequisites:

- [NSIS](https://nsis.sourceforge.io/) — `makensis.exe` on PATH
- [EnVar plugin](https://nsis.sourceforge.io/EnVar_plug-in) for PATH editing
- (MSIX) Windows 10/11 SDK with `makeappx.exe` on PATH

The NSIS installer:

- installs to `C:\Program Files\OpenForge EDA\`
- adds Start Menu and Desktop shortcuts
- registers `.ofpr` (OpenForge project) files
- adds the install dir to the user's `PATH` so the `openforge` CLI works
- adds an Add/Remove Programs entry with a working uninstaller

Output: `installer/OpenForge-<version>-Setup.exe`

## macOS

```bash
python installer/build_macos.py
python installer/build_macos.py \
    --codesign "Developer ID Application: Your Name (TEAMID)" \
    --notarize my-notary-profile
```

Extra prerequisites:

- Xcode command line tools (`xcode-select --install`)
- [`create-dmg`](https://github.com/create-dmg/create-dmg) (preferred) or
  the built-in `hdiutil`
- (Notarization) An app-specific password stored as a `notarytool`
  keychain profile via `xcrun notarytool store-credentials`

Output: `dist/OpenForge-<version>.dmg`

## Linux

```bash
python installer/build_linux.py                # AppImage (default)
python installer/build_linux.py --flatpak
python installer/build_linux.py --snap
python installer/build_linux.py --all          # all three
```

Extra prerequisites:

- AppImage: `appimagetool` on PATH
  (https://github.com/AppImage/AppImageKit/releases)
- Flatpak: `flatpak-builder` and the `org.kde.Sdk//6.6` runtime
- Snap: `snapcraft` (`sudo snap install snapcraft --classic`)

Outputs:

- `dist/OpenForge-<version>-x86_64.AppImage`
- `dist/flatpak-build/` (Flatpak repo)
- `installer/snap/openforge_<version>_amd64.snap`

## Bumping the version

Update `APP_VERSION` in each `build_*.py` script and the
`CFBundleShortVersionString` in `openforge.spec`. They should match the
version reported by `openforge --version` from the CLI package.

## Troubleshooting

| Symptom                                          | Fix                                                                                              |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `ModuleNotFoundError` for an `openforge.*` name  | add it to `hiddenimports` in `openforge.spec`                                                    |
| Plugin Qt panels missing at runtime              | same — every dynamically-imported panel needs an explicit `hiddenimports` entry                  |
| `makensis` not found                             | install NSIS and ensure `makensis.exe` is on `PATH`                                              |
| macOS `.app` won't open ("damaged")              | the bundle isn't codesigned; run with `--codesign` or quarantine-strip with `xattr -cr`           |
| AppImage segfaults at startup                    | re-run with `--appimage-extract-and-run` to bypass FUSE, then check `~/.openforge/desktop.log`   |
| Flatpak build fails on missing runtime           | `flatpak install flathub org.kde.Platform//6.6 org.kde.Sdk//6.6`                                 |

## CI

GitHub Actions workflows in `.github/workflows/release.yml` invoke these
scripts on `windows-latest`, `macos-latest`, and `ubuntu-latest` runners
whenever a `v*` tag is pushed. Resulting artifacts are uploaded to the
GitHub release that the auto-updater queries.
