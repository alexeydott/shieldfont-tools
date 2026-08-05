[← Getting Started](getting-started.md) · [Back to README](../README.md) · [Configuration →](configuration.md)

# Architecture

ShieldFont Toolchain uses Explicit Architecture:

```text
presentation -> application -> domain
                       \-> infrastructure adapters
packages/codec -> generated canonical contracts
```

## Boundaries

| Layer | Responsibility |
|---|---|
| `domain/` | Rules, scopes, policies, manifests, errors, verification contracts |
| `application/` | Build, dictionary, font, CSS, migration, verification use cases |
| `infrastructure/` | fontTools, HarfBuzz, SQLite, filesystem, provider adapters |
| `presentation/` | Thin Typer CLI and structured output |
| `packages/codec/` | Public TypeScript codec consuming generated contracts |

The canonical normalized ruleset is shared by dictionary validation, font
features, shaping, and the codec. The core build is offline and deterministic
when reproducible mode is enabled.

## Upstream boundary

`deps/shieldfont` is a pinned, read-only submodule. New code must use stable
contracts and adapters rather than importing upstream private implementation
details.

## Build flow

1. Load and validate `shieldfont/v1` configuration.
2. Inspect and normalize a TrueType `glyf` source font.
3. Normalize dictionaries and construct one canonical ruleset.
4. Generate glyphs, GSUB features, CSS, and codec artifacts.
5. Verify structure, layout references, hashes, shaping, and security metadata.
6. Publish the staged output atomically.

## See Also

- [Configuration](configuration.md) - input contract
- [Testing](testing.md) - quality gates
- [Release](release.md) - reproducible publication
