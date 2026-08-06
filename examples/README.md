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
demo values here only.

## 3. Document-bound profile with reserves

This demonstrates deterministic future-coverage reserves and an explicit GSUB
optimization request. The current implementation records the Format 2 estimate
and safely selects deterministic Format 3.

```powershell
shieldfont-generate run examples\profiles\03-document-bound-reserve.yml
```

The generated document-bound bundle is under the configured output directory:

- `artifacts\public\` is the reviewed delivery tier.
- `artifacts\private\` contains the exact mapping and audit material.
- `artifacts\verification\` contains the privacy scan and security report.
- `artifacts\build-manifest.json` records roles, hashes, and cache identity.

These examples demonstrate cost-raising/provenance behavior only. ShieldFont is
not cryptographic protection, DRM, confidentiality, or an un-scrapeable
system.
