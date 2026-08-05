import { build } from "esbuild";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(".");
const sourcePath = resolve(root, "src/shieldfont/presentation/web/static/app.js");
const outputPath = resolve(root, "src/shieldfont/presentation/web/static/app.bundle.js");
let source = await readFile(sourcePath, "utf8");

source = source
  .replaceAll(
    '"/vendor/monaco-editor/esm/vs/editor/editor.main.js"',
    '"monaco-editor/esm/vs/editor/editor.main.js"',
  )
  .replaceAll(
    '"/vendor/monaco-editor/esm/vs/editor/contrib/folding/browser/folding.js"',
    '"monaco-editor/esm/vs/editor/contrib/folding/browser/folding.js"',
  )
  .replaceAll('"/vendor/monaco-yaml/index.js"', '"monaco-yaml"')
  .replaceAll('"/vendor/yaml/browser/index.js"', '"yaml"');

await build({
  bundle: true,
  format: "esm",
  minify: true,
  platform: "browser",
  stdin: {
    contents: source,
    resolveDir: root,
    sourcefile: "app.js",
  },
  loader: { ".css": "empty" },
  outfile: outputPath,
  logLevel: "info",
});
