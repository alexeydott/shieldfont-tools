[← Configuration](configuration.md) · [Back to README](../README.md) · [Testing →](testing.md)

# CLI Reference

This project has two CLI entry points:

- `shieldfont` is the full Python CLI for initialization, font and dictionary
  operations, builds, verification, CSS, and migration.
- `shieldfont-generate.exe` is the standalone Windows x64 executable for
  profile-driven generation and the local GUI server.

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
`--project-version`, `--font-display`, `--embed-font/--no-embed-font`, and the
document-bound options listed below.
`--postfix` derives the generated family from the original source-font family
after normalization and appends the supplied suffix, for example
`--postfix _ru`. Use `--family` when an exact family name is required; do not
combine `--family` and `--postfix`.
`--strict/--non-strict` controls unknown profile-field validation. The command
uses the same atomic build pipeline as `shieldfont build` and performs no
network or LLM requests.

Document-bound builds also support:

- `--protection-profile compatibility|document-bound`
- `--mapping-contract shieldfont.mapping.v1|shieldfont.mapping.v2`
- `--mapping-seed`, `--document-nonce`, and `--tenant-id` private inputs
- repeatable `--inventory PATH` and `--reserve-aliases N`
- `--scan-public-artifacts/--no-scan-public-artifacts`
- `--gsub-optimization auto|format2|format3`

The CLI never prints raw seed, nonce, or tenant values. A document-bound build
requires reproducible TTF and WOFF2 output and one grouped JSON mapping contract
per scope. It emits canonical public/private/verification tiers under
`artifacts/`; publish only the reviewed public tier.

## Portable executable examples

Run the following commands from the repository root. Each example is
copy-pasteable in PowerShell:

```powershell
.\build\shieldfont-generate.exe --help
.\build\shieldfont-generate.exe run shieldfont.yml --source .fonts\segoepr.ttf --postfix _ru --output-dir build\ru --json
.\build\shieldfont-generate.exe serve --project-root . --fonts-dir .fonts --port 8765
```

| Example | Description |
|---|---|
| `.\build\shieldfont-generate.exe --help` | Show the available portable commands and their examples. |
| `.\build\shieldfont-generate.exe run shieldfont.yml --source .fonts\segoepr.ttf` | Run the profile with the repository's sample TrueType source font. |
| `.\build\shieldfont-generate.exe run shieldfont.yml --source .fonts\segoepr.ttf --postfix _ru --output-dir build\ru --json` | Override the source font and family suffix, publish to `build\ru`, and print JSON output. |
| `.\build\shieldfont-generate.exe run shieldfont.yml --source .fonts\segoepr.ttf --family MyShieldFont --output-dir build\custom` | Use an explicit generated family name. Do not combine `--family` with `--postfix`. |
| `.\build\shieldfont-generate.exe run shieldfont.yml --source .fonts\segoepr.ttf --dictionary dictionaries\ru-alpha.csv --font-display swap` | Select a dictionary and CSS `font-display` policy for the build. |
| `.\build\shieldfont-generate.exe serve --project-root . --fonts-dir .fonts --port 8765` | Start the local GUI, using `.fonts` for source-font selection, on port 8765. |

## Portable Windows executable

Build a single Windows x64 executable under `.\build`:

```powershell
python -m pip install -e ".[portable]"
.\scripts\build-portable.ps1
.\build\shieldfont-generate.exe run shieldfont.yml --help
```

The portable executable also hosts the local GUI without installing Python or
Node.js on the target machine:

```powershell
.\build\shieldfont-generate.exe serve --project-root . --port 8765
```

The bundled web assets and JavaScript dependencies are extracted to the
executable's local runtime directory when the server starts. The server binds
to localhost by default; use `--host` only when access from another interface
is intentional.

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
shieldfont serve --project-root . --fonts-dir custom-fonts
```

For a Windows debug launch with persistent logs:

```powershell
.\scripts\serve-debug.ps1
```

The debug script creates a minimal `shieldfont.yml` and standard project
directories when the configuration is missing. Add a font under `.fonts/` and
select it in the GUI before running conversion actions.

The default source-font directory is `.fonts/`; it is created automatically
when absent. Use `--fonts-dir` (or the compatibility alias `--fonts-root`) to
change this directory for the server session. Generated fonts under `dist/`
are never treated as source inputs.
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
