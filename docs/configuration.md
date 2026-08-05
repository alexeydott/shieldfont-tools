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
| `layout` | Fire-then-revert and GSUB budgets |
| `codec` | Package formats and browser exposure flags |
| `verification` | Structural, shaping, codec, and browser levels |
| `license` | Source-license policy |

Provider credentials are not part of the project configuration.

## Security defaults

`codec.browserBuild` and `codec.embedMappings` default to `false`. Keep them
disabled unless the disclosure tradeoff is explicitly accepted.

## See Also

- [CLI](cli.md) - commands that consume configuration
- [Security](security.md) - threat model and disclosure rules
- [Getting Started](getting-started.md) - initialization
