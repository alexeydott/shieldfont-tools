# A utilities kit for creating multilingual ShieldFont fonts.

## Todo:
1. INPUT NORMALIZATION
   Unicode NFC/NFD handling
   ccmp composition
   script/language detection

2. ENCODER
   private document nonce
   one-to-many alias selection
   phrase-level optional mappings
   case preservation

3. GSUB NORMALIZATION
   ccmp
   locl
   mark-aware processing

4. WORD RESTORATION
   multiple target ligatures > one source word glyph
   longest-first matching
   class-based boundary logic
   fire-then-revert

5. VISUAL POLYMORPHISM
   deterministic calt variants
   optional rand/GPOS/COLR profile

6. FONT QUALITY
   composites built from HarfBuzz-shaped runs
   exact GPOS offsets
   correct hmtx bounds
   GDEF LigatureCaretList
   mark/mkmk preservation

7. DELIVERY
   per-document mapping
   per-document subset WOFF2
   opaque family names
   post format 3
   no plaintext metadata

8. AUDIT
   mapping audit
   GSUB structural audit
   HarfBuzz round-trip
   Chrome/Firefox/Safari screenshot comparison
   substring-collision corpus
   NFC/NFD and combining-mark corpus