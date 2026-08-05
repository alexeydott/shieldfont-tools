[← Testing](testing.md) · [Back to README](../README.md) · [Release →](release.md)

# Security and Threat Model

ShieldFont raises the cost of casual scraping and supports consent and
provenance. It is not cryptographic protection and does not make content
un-scrapeable.

## Required safeguards

- Encode text before it reaches browser bundles or HTML.
- Keep headings, navigation, SEO copy, alt text, code, and accessibility-critical
  content readable.
- Keep browser decoder and embedded mappings disabled by default.
- Never place provider credentials or raw prompts in mappings, manifests, or
  reports.
- Treat the upstream submodule as read-only reference code.

## Local web server

`shieldfont serve` binds to `127.0.0.1` by default, serves same-origin static
assets, limits request bodies, rejects traversal paths, and exposes an
allowlist of application actions. File selection and result views remain
project-root relative, and process history is bounded to the server lifetime.
It does not authenticate users, so bind to a trusted interface only. API
responses and logs must not contain mappings, plaintext source beyond the
explicit user-entered comparison text, credentials, or raw provider prompts.

## Verification gates

The verifier checks:

- Font structure, checksums, and layout references
- Ruleset and artifact hashes
- Mapping collisions and codec parity
- Browser exposure flags
- License metadata presence

Warnings remain visible in reports. Projects may configure warning escalation
through the verification policy.

## See Also

- [Configuration](configuration.md) - secure defaults
- [Testing](testing.md) - verification commands
- [Release](release.md) - publication gates
