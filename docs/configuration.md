[← Architecture](architecture.md) · [Back to README](../README.md) · [CLI →](cli.md)

# Configuration

The configuration schema is `shieldfont/v1`. Unknown keys are rejected.

When a project is initialized, or the local web application starts with an
empty `dictionaries/` directory, it creates `dictionaries/default.csv` with
the built-in source/target pairs. Existing dictionary files are preserved.

## Minimal example

```yaml
schema: shieldfont/v1
source:
  path: .fonts/Source.ttf
scopes:
  - id: default
    dictionaries:
      - dictionaries/default.csv
```

## Important sections

| Section | Purpose |
|---|---|
| `project` | ID, version, output directory, reproducibility |
| `source` | Source path, allowed containers, variable-font instance |
| `font` | Family metadata and TTF/WOFF2 output formats |
| `scopes` | Locale/script scopes and dictionary files |
| `mapping` | Normalization, collision, and involution policies |
| `protection` | Versioned aliases, document subsets, bundle identity, privacy scan |
| `layout` | Fire-then-revert and GSUB budgets |
| `codec` | Package formats and browser exposure flags |
| `verification` | Structural, shaping, codec, and browser levels |
| `license` | Source-license policy |

Provider credentials are not part of the project configuration.

## Compatibility and document-bound profiles

The additive `protection` section defaults to `compatibility`, so existing
`shieldfont/v1` CSV projects keep their current build and artifact layout.

```yaml
protection:
  profile: compatibility
  mappingContract: shieldfont.mapping.v1
  inventory: []
  reserveAliases: 0
  reserve: []
  scanPublicArtifacts: false
```

Use `document-bound` with one `shieldfont.mapping.v2` JSON contract per scope:

```yaml
project:
  reproducible: true
  sourceDateEpoch: 0
font:
  outputFormats: [ttf, woff2]
layout:
  gsubOptimization: auto
protection:
  profile: document-bound
  mappingContract: shieldfont.mapping.v2
  seed: private-build-seed
  documentNonce: private-document-id
  tenantId: private-cache-partition
  inventory:
    - content/article.txt
  reserveAliases: 10
  reserve: []
  scanPublicArtifacts: true
```

Versioned contracts contain ordered grammar groups and alias lists. Selection
is deterministic for the seed, nonce, group, and source. Raw seed, nonce, and
tenant values are private inputs; manifests contain only bounded identifiers
or digests. Inventory files are read offline as UTF-8 and reduced to normalized
Unicode word counts. Empty inventory is valid and selects no groups unless a
reserve is configured.

Document-bound builds add `artifacts/`:

- `public/`: digest-only `mapping.json`, web fonts, and `shieldfont.css`
- `private/`: exact encoder mapping, reverse mapping audits, audit TTF, and ruleset
- `verification/`: privacy scan and honest security metadata
- `build-manifest.json`: role, schema, size, and SHA-256 for every artifact

Only `artifacts/public/` is eligible for publication. Its `mapping.json`
contains counts and digests only. The exact selected encoder mapping is
`artifacts/private/mapping.json`; keep it in restricted build storage and never
bundle it into browser runtime code.

`layout.gsubOptimization` accepts `auto`, `format2`, or `format3`. Format 2 is
estimated, but the builder currently selects deterministic Format 3 unless a
future shaping-validation oracle approves the class representation. The
fallback and both estimates are recorded in `manifest.json`.

## Security defaults

`codec.browserBuild` and `codec.embedMappings` default to `false`. Keep them
disabled unless the disclosure tradeoff is explicitly accepted.

## See Also

- [CLI](cli.md) - commands that consume configuration
- [Security](security.md) - threat model and disclosure rules
- [Getting Started](getting-started.md) - initialization
