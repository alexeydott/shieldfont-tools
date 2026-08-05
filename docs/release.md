[← Security](security.md) · [Back to README](../README.md)

# Release

## Release inputs

Use a pinned upstream submodule, explicit source font, canonical dictionaries,
and a reproducible configuration.

```bash
git submodule update --init --recursive
python -m ruff check src tests
python -m mypy src
python -m pytest -q
npm ci
npm run typecheck
npm run test:node
npm run build
shieldfont build
shieldfont verify dist
```

## Artifacts

A successful build publishes a manifest, ruleset, checksums, fonts, CSS,
codec outputs, and verification reports. `SHA256SUMS` uses stable relative
paths. A failed build leaves the previous successful `dist/` untouched.

## Reproducibility

Enable `project.reproducible`, pin tool versions, and set
`project.sourceDateEpoch` when the release requires byte-identical output.
Compare two independent builds before publication.

## Licensing and attribution

Review source-font license metadata and include upstream attribution required
by `deps/shieldfont/AGENTS.md`. Do not ship proprietary mappings or fonts in
fixtures or examples.

## See Also

- [Security](security.md) - release security gates
- [Testing](testing.md) - validation commands
- [Architecture](architecture.md) - artifact flow
