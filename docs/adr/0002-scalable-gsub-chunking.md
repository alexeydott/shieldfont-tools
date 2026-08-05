# ADR 0002: Chunk large GSUB tables before compilation

## Status

Accepted.

## Context

Ligature and reversal mappings can exceed OpenType 16-bit subtable offsets.
Coverage lists ordered by glyph name can also fragment otherwise contiguous
glyph-ID ranges and overflow contextual coverage offsets.

## Decision

Estimate ligature record size and split `LigatureSubst` below a conservative
40 KiB budget. Preserve longest-first ordering across chunks for common
prefixes. Split reversal `MultipleSubst` mappings at no more than 1,500 entries
per subtable. Sort coverage glyphs by glyph ID, not glyph name. Keep bulk data
compatible with extension-offset promotion while allowing the serializer to
choose the final packing strategy.

## Consequences

Large mappings remain deterministic and serializable. Chunk boundaries are an
implementation detail and must not change matching precedence. Tests must cover
near-limit mappings and lookup-reference remapping.

## Verification

The constants and ordering rules are frozen in
`tests/fixtures/upstream/font_layout_contract.json`.
