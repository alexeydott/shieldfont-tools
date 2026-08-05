[Back to README](../README.md) · [Architecture →](architecture.md)

# Getting Started

## Prerequisites

- Python 3.12 or newer
- Node.js 20 or newer
- Git with submodule support

## Install

```bash
git clone --recurse-submodules <repository-url>
cd ShieldFontTools
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
npm ci
```

## Initialize a project

```bash
shieldfont init --font .fonts/Source.ttf
```

Review the generated `shieldfont.yml`, add dictionaries, and run:

```bash
shieldfont build
shieldfont verify dist
```

The build publishes `dist/` atomically only after completed stages succeed.

To use the local web interface:

```bash
shieldfont serve --project-root .
```

Open `http://127.0.0.1:8765/` in a browser. The server is local-first and
delegates only explicitly listed ShieldFont operations. Select a project font
and dictionary from the input panel, prepare dictionaries, run
the build and verification workflow, then enter test text to compare the
original and ShieldFont output.

## Useful first commands

```bash
shieldfont dict validate dictionaries/default.csv
shieldfont font inspect .fonts/Source.ttf
shieldfont features generate --ruleset dist/ruleset.json
shieldfont css build --font dist/fonts/shieldfont.woff2
```

## See Also

- [Architecture](architecture.md) - module boundaries and data flow
- [Configuration](configuration.md) - `shieldfont.yml` reference
- [CLI](cli.md) - command reference
