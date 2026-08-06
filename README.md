# ShieldFont Toolchain

ShieldFont Toolchain is an offline-first toolkit for building multilingual
TrueType fonts with deterministic OpenType substitutions. It combines font
normalization, CSV dictionary processing, GSUB feature generation, CSS/codec
output, verification, and a local web GUI.

## Purpose

Use it to create reproducible ShieldFont variants from a TrueType source font
and a generation profile. The standalone CLI supports profile-based builds,
typed command-line overrides, and a portable Windows executable.

## System requirements

- Python 3.12 or newer
- A TrueType source font with `glyf` outlines
- Node.js 20 or newer and npm for codec, web, and browser checks
- Windows 10/11 x64 for the prebuilt portable executable
- Chromium, Firefox, and WebKit only when running browser verification

## Quick start

```powershell
python -m pip install -e .
shieldfont init .
shieldfont-generate run shieldfont.yml --source .fonts\Source.ttf --postfix _shld
```

Build the portable Windows executable:

```powershell
python -m pip install -e ".[portable]"
.\scripts\build-portable.ps1
.\build\shieldfont-generate.exe run shieldfont.yml --help
```

## CLI reference

The portable `shieldfont-generate.exe` is intended for Windows x64 and
provides profile generation plus the local GUI server. Run these commands from
the repository root:

| Command | Description |
|---|---|
| `.\build\shieldfont-generate.exe --help` | List available commands and runnable examples. |
| `.\build\shieldfont-generate.exe run shieldfont.yml --source .fonts\segoepr.ttf --postfix _shld --output-dir dist --json` | Generate and publish ShieldFont artifacts, using a source font and a family suffix. |
| `.\build\shieldfont-generate.exe run shieldfont.yml --source .fonts\segoepr.ttf --family MyShieldFont --output-dir dist\custom` | Generate artifacts with an explicit output family name. |
| `.\build\shieldfont-generate.exe run shieldfont.yml --source .fonts\segoepr.ttf --dictionary dictionaries\default.csv --font-display swap` | Generate using a selected dictionary and CSS display policy. |
| `.\build\shieldfont-generate.exe serve --project-root . --fonts-dir .fonts --port 8765` | Start the local web GUI on port 8765. Open `http://127.0.0.1:8765/` in a browser. |

The full CLI, including dictionary, font, feature, CSS, verification, and
migration commands, is documented in [`docs/cli.md`](docs/cli.md).
Profile settings are documented in [`docs/configuration.md`](docs/configuration.md).
