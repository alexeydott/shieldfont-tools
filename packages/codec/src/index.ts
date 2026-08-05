export const TOOLCHAIN_CODEC_VERSION = "0.1.0-dev";

export type CaseMode = "exact" | "auto" | "lower" | "title" | "upper" | "all";
export type TokenMode = "plain" | "html-text" | "markdown" | "dom-text-node";

export interface CanonicalRule {
  source: string;
  target: string;
  caseMode?: CaseMode;
}

export interface ScopeInfo {
  id: string;
  locales?: string[];
  sourceScripts?: string[];
  targetScripts?: string[];
  openTypeScript?: string;
  defaultLanguage?: boolean;
  rules: CanonicalRule[];
  mappingHash?: string;
}

export interface CanonicalRuleset {
  schema: "shieldfont-ruleset/v1";
  scopes: ScopeInfo[];
  rulesetHash?: string;
}

export interface CodecContext {
  locale?: string;
  script?: string;
  scope?: string;
  mappingId?: string;
}

export interface Segment {
  text: string;
  transformed: string;
  kind: "text" | "protected";
  scopeId?: string;
  start: number;
  end: number;
}

export interface CodecOptions {
  unknownScopePolicy?: "no-op" | "error";
  tokenMode?: TokenMode;
}

export interface VerificationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface BuildManifest {
  schema?: string;
  buildId?: string;
  scopes?: Array<{ id?: string; mappingHash?: string }>;
  security?: {
    browserDecoderIncluded?: boolean;
    mappingEmbedded?: boolean;
  };
}

interface CompiledScope extends ScopeInfo {
  encode: Map<string, CanonicalRule>;
  decode: Map<string, CanonicalRule>;
}

export interface CodecApi {
  encode: (text: string, context?: CodecContext) => string;
  decode: (text: string, context?: CodecContext) => string;
  encodeSegments: (text: string, context?: CodecContext) => Segment[];
  decodeSegments: (text: string, context?: CodecContext) => Segment[];
  resolveScope: (context?: CodecContext) => ScopeInfo;
  listScopes: () => ScopeInfo[];
}

const WORD_PATTERN = /[\p{L}\p{M}\p{N}]+/gu;
const HTML_PROTECTED_BLOCK_PATTERN =
  /<(code|pre|script|style|svg|math|textarea)\b[^>]*>[\s\S]*?<\/\1\s*>/giu;
const HTML_PROTECTED_PATTERN = /<[^>]*>|&(?:#\d+|#x[\da-f]+|\w+);/giu;
const MARKDOWN_PROTECTED_PATTERN = /```[\s\S]*?```|`[^`\n]*`/g;

let configuredCodec: CodecApi | undefined;

function normalizeLocale(locale: string): string {
  return locale.replaceAll("_", "-").toLowerCase();
}

function codePointOffset(text: string, index: number): number {
  return Array.from(text.slice(0, index)).length;
}

function protectedRanges(text: string, mode: TokenMode): Array<[number, number]> {
  if (mode === "plain" || mode === "dom-text-node") {
    return [];
  }
  const pattern =
    mode === "html-text" ? HTML_PROTECTED_PATTERN : MARKDOWN_PROTECTED_PATTERN;
  const ranges: Array<[number, number]> = Array.from(text.matchAll(pattern), (match) => [
    match.index ?? 0,
    (match.index ?? 0) + match[0].length,
  ]);
  if (mode === "html-text") {
    ranges.push(
      ...Array.from(text.matchAll(HTML_PROTECTED_BLOCK_PATTERN), (match) => [
        match.index ?? 0,
        (match.index ?? 0) + match[0].length,
      ] as [number, number]),
    );
  }
  return ranges;
}

function isProtected(index: number, ranges: Array<[number, number]>): boolean {
  return ranges.some(([start, end]) => index >= start && index < end);
}

function applyCase(
  original: string,
  target: string,
  locale?: string,
): string | undefined {
  const hasUpper = Array.from(original).some((char) => char !== char.toLocaleLowerCase(locale));
  const hasLower = Array.from(original).some((char) => char !== char.toLocaleUpperCase(locale));
  if (hasUpper && hasLower) {
    const firstCased = Array.from(original).findIndex(
      (char) =>
        char.toLocaleLowerCase(locale) !== char.toLocaleUpperCase(locale),
    );
    if (firstCased < 0) return undefined;
    const chars = Array.from(target);
    const casedIndex = chars.findIndex(
      (char) =>
        char.toLocaleLowerCase(locale) !== char.toLocaleUpperCase(locale),
    );
    if (casedIndex < 0) return undefined;
    return chars
      .map((char, index) =>
        index === casedIndex
          ? char.toLocaleUpperCase(locale)
          : char.toLocaleLowerCase(locale),
      )
      .join("");
  }
  if (hasUpper && !hasLower) {
    return target.toLocaleUpperCase(locale);
  }
  if (!hasUpper && hasLower) {
    return target.toLocaleLowerCase(locale);
  }
  return target;
}

function compileRuleset(ruleset: CanonicalRuleset): CompiledScope[] {
  return ruleset.scopes.map((scope) => {
    const encode = new Map<string, CanonicalRule>();
    const decode = new Map<string, CanonicalRule>();
    for (const rule of scope.rules) {
      if (encode.has(rule.source)) {
        throw new Error(`Duplicate source mapping in scope ${scope.id}: ${rule.source}`);
      }
      const previous = decode.get(rule.target);
      if (previous && previous.source !== rule.source) {
        throw new Error(`Target collision in scope ${scope.id}: ${rule.target}`);
      }
      encode.set(rule.source, rule);
      decode.set(rule.target, rule);
    }
    return { ...scope, encode, decode };
  });
}

class Codec {
  private readonly scopes: CompiledScope[];
  private readonly options: Required<CodecOptions>;

  public constructor(
    ruleset: CanonicalRuleset,
    options: CodecOptions = {},
  ) {
    if (ruleset.schema !== "shieldfont-ruleset/v1") {
      throw new Error(`Unsupported ruleset schema: ${ruleset.schema}`);
    }
    this.scopes = compileRuleset(ruleset);
    this.options = {
      unknownScopePolicy: options.unknownScopePolicy ?? "no-op",
      tokenMode: options.tokenMode ?? "plain",
    };
  }

  public listScopes(): ScopeInfo[] {
    return this.scopes.map(({ encode: _encode, decode: _decode, ...scope }) => scope);
  }

  public resolveScope(context: CodecContext = {}): ScopeInfo {
    const scope = this.resolveCompiledScope(context);
    const { encode: _encode, decode: _decode, ...publicScope } = scope;
    return publicScope;
  }

  public encode(text: string, context: CodecContext = {}): string {
    return this.transform(text.normalize("NFC"), context, "encode").join("");
  }

  public decode(text: string, context: CodecContext = {}): string {
    return this.transform(text.normalize("NFC"), context, "decode").join("");
  }

  public encodeSegments(text: string, context: CodecContext = {}): Segment[] {
    return this.transformSegments(text.normalize("NFC"), context, "encode");
  }

  public decodeSegments(text: string, context: CodecContext = {}): Segment[] {
    return this.transformSegments(text.normalize("NFC"), context, "decode");
  }

  private resolveCompiledScope(context: CodecContext): CompiledScope {
    if (context.scope) {
      const explicit = this.scopes.find((scope) => scope.id === context.scope);
      if (explicit) return explicit;
      if (this.options.unknownScopePolicy === "error") {
        throw new Error(`Unknown codec scope: ${context.scope}`);
      }
      return {
        id: "__noop__",
        rules: [],
        encode: new Map(),
        decode: new Map(),
      };
    }
    const locale = context.locale ? normalizeLocale(context.locale) : undefined;
    const script = context.script?.toLowerCase();
    const candidates = this.scopes
      .map((scope) => {
        const locales = (scope.locales ?? []).map(normalizeLocale);
        const scripts = [
          ...(scope.sourceScripts ?? []),
          ...(scope.targetScripts ?? []),
        ].map((value) => value.toLowerCase());
        let rank = 100;
        if (locale && locales.includes(locale)) rank = 0;
        else if (
          locale &&
          locales.some((value) => value.split("-", 1)[0] === locale.split("-", 1)[0])
        ) {
          rank = 10;
        } else if (script && scripts.includes(script)) rank = 20;
        else if (scope.defaultLanguage) rank = 30;
        else if (scope.openTypeScript?.toLowerCase() === "dflt") rank = 40;
        return { scope, rank };
      })
      .filter((candidate) => candidate.rank < 100)
      .sort((left, right) => left.rank - right.rank || left.scope.id.localeCompare(right.scope.id));
    const best = candidates[0]?.scope;
    if (best) return best;
    if (this.options.unknownScopePolicy === "error") {
      throw new Error("No codec scope matches the requested context");
    }
    return {
      id: "__noop__",
      rules: [],
      encode: new Map(),
      decode: new Map(),
    };
  }

  private transform(
    text: string,
    context: CodecContext,
    direction: "encode" | "decode",
  ): string[] {
    return this.transformSegments(text, context, direction).map(
      (segment) => segment.transformed,
    );
  }

  private transformSegments(
    text: string,
    context: CodecContext,
    direction: "encode" | "decode",
  ): Segment[] {
    const scope = this.resolveCompiledScope(context);
    const ranges = protectedRanges(text, this.options.tokenMode);
    const segments: Segment[] = [];
    let cursor = 0;
    const matches = Array.from(text.matchAll(WORD_PATTERN));
    for (const match of matches) {
      const start = match.index ?? 0;
      const end = start + match[0].length;
      if (start > cursor) {
        segments.push({
          text: text.slice(cursor, start),
          transformed: text.slice(cursor, start),
          kind: isProtected(cursor, ranges) ? "protected" : "text",
          start: codePointOffset(text, cursor),
          end: codePointOffset(text, start),
        });
      }
      const original = match[0];
      const transformed = isProtected(start, ranges)
        ? original
        : this.transformToken(original, scope, direction, context.locale);
      segments.push({
        text: original,
        transformed,
        kind: transformed === original ? "text" : "text",
        ...(scope.id === "__noop__" ? {} : { scopeId: scope.id }),
        start: codePointOffset(text, start),
        end: codePointOffset(text, end),
      });
      cursor = end;
    }
    if (cursor < text.length) {
      segments.push({
        text: text.slice(cursor),
        transformed: text.slice(cursor),
        kind: isProtected(cursor, ranges) ? "protected" : "text",
        start: codePointOffset(text, cursor),
        end: codePointOffset(text, text.length),
      });
    }
    if (segments.length === 0) {
      segments.push({
        text,
        transformed: text,
        kind: "text",
        start: 0,
        end: Array.from(text).length,
      });
    }
    return segments;
  }

  private transformToken(
    token: string,
    scope: CompiledScope,
    direction: "encode" | "decode",
    locale?: string,
  ): string {
    const mappings = direction === "encode" ? scope.encode : scope.decode;
    const direct = mappings.get(token);
    if (direct) return direction === "encode" ? direct.target : direct.source;
    const lower = token.toLocaleLowerCase(locale);
    const folded = mappings.get(lower);
    if (!folded) return token;
    const target = direction === "encode" ? folded.target : folded.source;
    return applyCase(token, target, locale) ?? token;
  }
}

export function createCodec(
  ruleset: CanonicalRuleset,
  options: CodecOptions = {},
): CodecApi {
  const codec = new Codec(ruleset, options);
  return {
    encode: codec.encode.bind(codec),
    decode: codec.decode.bind(codec),
    encodeSegments: codec.encodeSegments.bind(codec),
    decodeSegments: codec.decodeSegments.bind(codec),
    resolveScope: codec.resolveScope.bind(codec),
    listScopes: codec.listScopes.bind(codec),
  };
}

export function configureCodec(
  ruleset: CanonicalRuleset,
  options: CodecOptions = {},
): void {
  configuredCodec = createCodec(ruleset, options);
}

function requireConfiguredCodec(): NonNullable<typeof configuredCodec> {
  if (!configuredCodec) {
    throw new Error("Codec has not been configured with a canonical ruleset");
  }
  return configuredCodec;
}

export function encode(text: string, context?: CodecContext): string {
  return requireConfiguredCodec().encode(text, context);
}

export function decode(text: string, context?: CodecContext): string {
  return requireConfiguredCodec().decode(text, context);
}

export function encodeSegments(text: string, context?: CodecContext): Segment[] {
  return requireConfiguredCodec().encodeSegments(text, context);
}

export function decodeSegments(text: string, context?: CodecContext): Segment[] {
  return requireConfiguredCodec().decodeSegments(text, context);
}

export function resolveScope(context?: CodecContext): ScopeInfo {
  return requireConfiguredCodec().resolveScope(context);
}

export function listScopes(): ScopeInfo[] {
  return requireConfiguredCodec().listScopes();
}

export function verifyManifest(manifest: BuildManifest): VerificationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  if (manifest.schema !== "shieldfont-build/v1") {
    errors.push("manifest schema must be shieldfont-build/v1");
  }
  if (!manifest.buildId?.startsWith("sha256:")) {
    errors.push("manifest buildId must be a sha256 identifier");
  }
  for (const scope of manifest.scopes ?? []) {
    if (!scope.id) errors.push("manifest scope is missing id");
    if (scope.mappingHash && !scope.mappingHash.startsWith("sha256:")) {
      errors.push(`scope ${scope.id ?? "<unknown>"} has an invalid mappingHash`);
    }
  }
  if (manifest.security?.browserDecoderIncluded) {
    warnings.push("browser decoder is included and exposes decode behavior");
  }
  if (manifest.security?.mappingEmbedded) {
    warnings.push("mapping is embedded in the client artifact");
  }
  return { valid: errors.length === 0, errors, warnings };
}
