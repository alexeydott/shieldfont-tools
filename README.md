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

See [`docs/cli.md`](docs/cli.md) for commands and [`docs/configuration.md`](docs/configuration.md) for profile settings.
