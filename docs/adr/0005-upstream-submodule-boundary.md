# ADR 0005: Treat upstream ShieldFont as a read-only reference

## Status

Accepted.

## Context

`deps/shieldfont` provides valuable production behavior but is an independently
licensed and versioned project. Direct imports from private scripts would couple
the toolchain to a monolithic implementation and make builds depend on mutable
submodule internals.

## Decision

Pin the submodule commit and consume upstream only through documented package or
script contracts, explicit adapters, and synthetic black-box fixtures. Do not
modify the submodule without separate approval. Do not copy proprietary font
assets or complete generated mappings into this repository.

Record SHA-256 hashes for source files used to derive baseline observations.
When the submodule is intentionally upgraded, review behavior and update the
provenance and fixtures together.

## Consequences

Core builds remain offline and independent of upstream runtime code. Fixture
drift is visible as a failing provenance test. AGPL obligations remain explicit
for any future code copied or adapted from upstream.

## Verification

`tests/fixtures/upstream/provenance.json` binds the baseline to commit
`d6efb2d3972569628e870ff2767cd29412c245ee` and the reviewed script hashes.
