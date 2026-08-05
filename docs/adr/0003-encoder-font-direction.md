# ADR 0003: Keep encoder and font directions inverse

## Status

Accepted.

## Context

The encoder and font builder perform different operations. Confusing their
directions creates a mapping that encodes correctly but renders the decoy
instead of the source word.

## Decision

For a canonical pair `source -> target`, the codec writes `target` into the
document. The font maps the glyph sequence for `target` to a composite that
visually represents `source`. Decode uses the involutive canonical mapping and
does not reverse the font lookup contract.

## Consequences

The canonical ruleset must expose direction explicitly. Font, codec, and
verification fixtures must derive from the same pair IDs and reject mappings
that are not bijective when involution is required.

## Verification

`tests/fixtures/upstream/encoder_contract.json` records the codec output, font
input, visual output, case handling, NFC behavior, and digit-context cases.
