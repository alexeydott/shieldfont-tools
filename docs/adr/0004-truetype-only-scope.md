# ADR 0004: Limit version 1 to TrueType glyf outlines

## Status

Accepted.

## Context

The composite builder depends on quadratic TrueType outlines and `glyf` metrics.
Supporting CFF/CFF2 would require a separate outline backend and different
serialization and bounds behavior.

## Decision

Accept TTF and WOFF2 containers only when the decoded font contains `glyf`.
Variable TrueType input must be instanced to a static font before mutation.
Reject OTF/CFF, CFF2, collections, Type 1, bitmap-only fonts, and variable
outputs before changing the source.

## Consequences

The implementation has one required `GlyfCompositeBuilder`. Outputs are static
TTF and WOFF2 derived from the same TrueType font. Unsupported formats receive
stable exit code 11 diagnostics.

## Verification

`tests/fixtures/upstream/scope_contract.json` freezes accepted inputs, rejected
inputs, and output constraints.
