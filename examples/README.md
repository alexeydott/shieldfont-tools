# ShieldFont Toolchain examples

Run these commands from the repository root. Replace the source font path if
`.fonts\Source.ttf` is not available.

## 1. Compatibility profile

This is the original CSV-based `shieldfont/v1` workflow. It keeps the previous
artifact layout and does not create document-bound canonical tiers.

```powershell
python -m shieldfont.presentation.cli.main build examples\profiles\01-compatibility.yml
```

## 2. Document-bound profile

This uses a `shieldfont.mapping.v2` contract. Only groups referenced by
`examples\content\article.txt` are selected, and the public artifact tier
contains digests rather than the exact mapping.

```powershell
python -m shieldfont.presentation.cli.main build examples\profiles\02-document-bound.yml
```

Keep the seed, nonce, and tenant values private in real projects. They are
demo values here only. The profile demonstrates inventory-bound group
selection, digest-only public mapping metadata, private exact mapping storage,
and deterministic bundle/cache identity.

## 3. Document-bound profile with reserves

This demonstrates deterministic future-coverage reserves and an explicit GSUB
optimization request. The current implementation records the Format 2 estimate
and safely selects deterministic Format 3.

```powershell
shieldfont-generate run examples\profiles\03-document-bound-reserve.yml
```

The same options can be supplied as CLI overrides instead of editing the
profile:

```powershell
shieldfont-generate run examples\profiles\03-document-bound-reserve.yml `
  --protection-profile document-bound `
  --mapping-contract shieldfont.mapping.v2 `
  --mapping-seed demo-private-build-seed `
  --document-nonce demo-reserve-2026-08-06 `
  --tenant-id demo-private-tenant `
  --inventory ..\content\reserve.txt `
  --reserve-aliases 2 `
  --scan-public-artifacts `
  --gsub-optimization format2
```

The `format2` request is intentionally safe: the builder records the estimate
and uses deterministic Format 3 until a shaping-validation oracle approves a
Format 2 representation.

The generated document-bound bundle is under the configured output directory:

- `artifacts\public\` is the reviewed delivery tier.
- `artifacts\private\` contains the exact mapping and audit material.
- `artifacts\verification\` contains the privacy scan and security report.
- `artifacts\build-manifest.json` records roles, hashes, and cache identity.

To demonstrate automatic project initialization, run the server against an
empty directory:

```powershell
shieldfont-generate serve --project-root examples\empty-project --port 8777
```

The directory is populated with a default `shieldfont.yml`, directories,
`dictionaries\default.csv`, and `texts\demo.txt` before the GUI starts. Remove
the generated directory after the demonstration; it is not a source fixture.

These examples demonstrate cost-raising/provenance behavior only. ShieldFont is
not cryptographic protection, DRM, confidentiality, or an un-scrapeable
system.
