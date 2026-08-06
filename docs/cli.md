[← Configuration](configuration.md) · [Back to README](../README.md) · [Testing →](testing.md)

# CLI Reference

The executable is `shieldfont`.

The standalone `shieldfont-generate` executable builds artifacts from a YAML
profile and lets explicit command-line values override the profile:

```powershell
shieldfont-generate run shieldfont.yml `
  --source .fonts/Source.ttf `
  --dictionary dictionaries/ru-alpha.csv `
  --output-dir dist/ru `
  --family ShieldFontRu `
  --font-display swap `
  --json
```

The profile is loaded first, then supplied overrides take precedence. Relative
override paths are resolved from the profile directory. Supported overrides are
`--output-dir`, `--source`, `--dictionary`, `--family`, `--postfix`, `--project-id`,
`--project-version`, `--font-display`, and `--embed-font/--no-embed-font`.
`--postfix` derives the generated family from the original source-font family
after normalization and appends the supplied suffix, for example
`--postfix _ru`. Use `--family` when an exact family name is required; do not
combine `--family` and `--postfix`.
`--strict/--non-strict` controls unknown profile-field validation. The command
uses the same atomic build pipeline as `shieldfont build` and performs no
network or LLM requests.

## Portable Windows executable

Build a single Windows x64 executable under `.\build`:

```powershell
python -m pip install -e ".[portable]"
.\scripts\build-portable.ps1
.\build\shieldfont-generate.exe run shieldfont.yml --help
```

The script requires a 64-bit Windows Python interpreter. PyInstaller work and
specification files are placed under ignored `build\.pyinstaller-*` directories
and removed after a successful build. Use `-KeepWork` to retain them for
diagnostics after a successful build.

| Command | Purpose |
|---|---|
| `init` | Create a project configuration |
| `build` | Build and atomically publish artifacts |
| `verify` | Verify a font or build directory |
| `dict validate` | Validate a CSV dictionary |
| `dict normalize` | Write canonical dictionary artifacts |
| `dict merge` | Merge dictionary layers |
| `dict from-text` | Generate reviewable LLM candidates |
| `dict review` | Apply candidate review decisions |
| `font inspect` | Inspect source font structure |
| `font normalize` | Instance and normalize a font |
| `features generate` | Generate deterministic FEA artifacts |
| `css build` | Generate WOFF2-first CSS |
| `serve` | Serve the local GUI and scoped application actions |
| `migrate legacy-project` | Convert a flat legacy JSON project |

## Verification

```bash
shieldfont verify dist --output-dir dist/reports
shieldfont verify dist/fonts/shieldfont.ttf --positive-sample "A"
```

Verification reports never include source text or provider credentials.

## Local web GUI

Start the offline-first GUI from a project root:

```bash
shieldfont serve --project-root . --host 127.0.0.1 --port 8765
```

Source font selection can be restricted to another project-relative directory:

```bash
shieldfont serve --project-root . --fonts-root custom-fonts
```

For a Windows debug launch with persistent logs:

```powershell
.\scripts\serve-debug.ps1
```

The debug script creates a minimal `shieldfont.yml` and standard project
directories when the configuration is missing. Add a font under `.fonts/` and
select it in the GUI before running conversion actions.

The default source-font directory is `.fonts/`; it is created automatically
when absent. The `--fonts-root` option changes this directory for the server
session, and generated fonts under `dist/` are never treated as source inputs.
The demo corpus is available at `texts/demo.txt` and is preloaded in the GUI's
test-text comparison field for keyword extraction workflows.
When initializing from a source font, `--postfix` controls the suffix appended
to its family name; the default is `_shld`.

The interface exposes only build, verify, font inspection, dictionary
validation, normalization, LLM candidate extraction, and CSS
generation. It also provides project-relative input selection, bounded process
history, result summaries, and original-vs-ShieldFont test-text comparison.
Use `--static-root` to serve a reviewed alternative asset directory. The server
is intended for localhost or a trusted private network; it does not provide
authentication.

## Logging

Use `--log-format text|json`, `--quiet`, `--verbose`, or `--trace`. Stable
machine-readable error codes are emitted for failed stages.

## See Also

- [Testing](testing.md) - local and CI checks
- [Configuration](configuration.md) - command inputs
- [Security](security.md) - safe operational defaults
