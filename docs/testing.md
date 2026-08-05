[← CLI](cli.md) · [Back to README](../README.md) · [Security →](security.md)

# Testing

## Local quality gates

```bash
python -m ruff check src tests
python -m mypy src
python -m pytest -q
npm run typecheck
npm run test:node
npm run build
```

## Browser verification

Playwright covers Chromium, Firefox, and WebKit:

```bash
npx playwright install chromium
npm run test:browser -- --project=chromium
```

The CI workflow installs all configured browsers and records JSON results in
the ignored `test-results/` directory.

## Benchmarks

Set a font path to run the deterministic shaping smoke benchmark:

```bash
$env:SHIELDFONT_BENCHMARK_FONT = "dist/fonts/shieldfont.ttf"
npm run benchmark
```

## Regression principles

- Keep canonical ruleset fixtures shared across Python and TypeScript.
- Add negative tests for collisions, scope leaks, malformed fonts, and stale
  hashes.
- Do not commit generated distributions, browser reports, caches, or temporary
  artifacts.

## See Also

- [Architecture](architecture.md) - testable boundaries
- [Release](release.md) - release gates
- [Security](security.md) - security checks
