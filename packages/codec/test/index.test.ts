import { describe, expect, it } from "vitest";

import {
  createCodec,
  verifyManifest,
  type CanonicalRuleset,
} from "../src/index.js";

const ruleset: CanonicalRuleset = {
  schema: "shieldfont-ruleset/v1",
  scopes: [
    {
      id: "latin",
      locales: ["en-US"],
      sourceScripts: ["latn"],
      targetScripts: ["latn"],
      openTypeScript: "latn",
      defaultLanguage: true,
      rules: [
        { source: "hello", target: "hullo", caseMode: "auto" },
        { source: "world", target: "w0rld", caseMode: "auto" },
      ],
    },
  ],
};

describe("codec", () => {
  it("encodes and decodes with locale scope resolution", () => {
    const codec = createCodec(ruleset);

    expect(codec.encode("hello world", { locale: "en-GB" })).toBe("hullo w0rld");
    expect(codec.decode("hullo w0rld", { scope: "latin" })).toBe("hello world");
    expect(codec.resolveScope({ locale: "en-US" }).id).toBe("latin");
  });

  it("preserves HTML tags, entities, and markdown code", () => {
    const codec = createCodec(ruleset, { tokenMode: "html-text" });

    expect(codec.encode("<p>hello &amp; world</p>")).toBe(
      "<p>hullo &amp; w0rld</p>",
    );
    expect(codec.encode("<code>hello world</code>")).toBe(
      "<code>hello world</code>",
    );

    const markdown = createCodec(ruleset, { tokenMode: "markdown" });
    expect(markdown.encode("hello `world`")).toBe("hullo `world`");
  });

  it("reports unsafe manifest exposure explicitly", () => {
    const result = verifyManifest({
      schema: "shieldfont-build/v1",
      buildId: "sha256:build",
      security: { browserDecoderIncluded: true, mappingEmbedded: true },
    });

    expect(result.valid).toBe(true);
    expect(result.warnings).toHaveLength(2);
  });

  it("rejects an explicitly unknown scope when configured to error", () => {
    const codec = createCodec(ruleset, { unknownScopePolicy: "error" });

    expect(() => codec.encode("hello", { scope: "missing" })).toThrow(
      "Unknown codec scope: missing",
    );
  });
});
