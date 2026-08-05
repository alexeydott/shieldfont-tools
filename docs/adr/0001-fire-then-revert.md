# ADR 0001: Use fire-then-revert for whole-word GSUB

## Status

Accepted.

## Context

OpenType GSUB cannot directly require the start or end of a shaping run. Gating a
word substitution on an explicit non-letter neighbor therefore fails at text-run
edges. Short targets can also appear inside larger words and must not remain
substituted there.

## Decision

Emit the word ligature unconditionally, then invoke an internal
`MultipleSubst` reversal when a substituted glyph has a letter-like neighbor.
The public `ccmp` sequence is ligature substitution, optional digit
substitution, letter-before reversion, and letter-after reversion. The reversal
lookup is internal and is called only by the contextual lookups.

Substituted word composites count as letter-like neighbors. Substituted digit
glyphs do not, so adjacent digit runs remain substituted.

## Consequences

Standalone words work at run edges, spaces, and punctuation. Matches inside
larger words revert to plain glyphs. New layout code must preserve lookup order
and remap every contextual lookup reference when existing GSUB lookups move.

## Verification

`tests/fixtures/upstream/font_layout_contract.json` records run-edge and
substring-collision observations from the pinned upstream implementation.
