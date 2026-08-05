import * as monaco from "/vendor/monaco-editor/esm/vs/editor/editor.main.js";
import "/vendor/monaco-editor/esm/vs/editor/contrib/folding/browser/folding.js";
import { configureMonacoYaml } from "/vendor/monaco-yaml/index.js";
import { parseDocument } from "/vendor/yaml/browser/index.js";

(() => {
  "use strict";

  const status = document.querySelector("#status");
  const actionStatus = document.querySelector("#action-status");
  const result = document.querySelector("#result");
  const llmPromptStatus = document.querySelector("#llm-prompt-status");
  const dictionaryEditor = document.querySelector("#dictionary-editor");
  const dictionaryStatus = document.querySelector("#dictionary-status");
  const dictionaryFile = document.querySelector("#dictionary-file");
  const fontFile = document.querySelector("#font-file");
  const fontStatus = document.querySelector("#font-status");
  const projectEditor = document.querySelector("#project-editor");
  const projectValidation = document.querySelector("#project-validation");
  const projectFile = document.querySelector("#project-file");
  const projectStatus = document.querySelector("#project-status");
  const projectBreadcrumbs = document.querySelector("#project-breadcrumbs");
  const projectProblems = document.querySelector("#project-problems");
  const appLoading = document.querySelector("#app-loading");
  const appLoadingMessage = document.querySelector("#app-loading-message");
  const appLoadingProgress = document.querySelector("#app-loading-progress");
  const appLoadingTrack = appLoadingProgress.parentElement;
  const operationProgress = document.querySelector("#operation-progress");
  const editorPreferenceInputs = {
    completion: document.querySelector("#editor-completion"),
    hover: document.querySelector("#editor-hover"),
    validate: document.querySelector("#editor-validation"),
  };
  const processes = document.querySelector("#processes");
  const results = document.querySelector("#results");
  const artifactSummary = document.querySelector("#artifact-summary");
  const compareButton = document.querySelector("#compare-text");
  const fileSelects = [...document.querySelectorAll("[data-file-kind]")];
  let monacoInstance;
  let projectEditorView;
  let monacoYaml;
  let projectSchema;
  let lastProjectEditorValue = "";
  let guardingNumericEdit = false;
  let projectCompletionDisposable;
  const editorPreferencesKey = "shieldfont.project-editor.preferences.v1";
  const fontPathKey = "shieldfont.font.v1:path";
  const editorPreferences = {
    completion: true,
    hover: true,
    validate: true,
  };

  function updateLoadingProgress(value, message) {
    const bounded = Math.max(0, Math.min(100, value));
    appLoadingProgress.style.width = `${bounded}%`;
    appLoadingTrack.setAttribute("aria-valuenow", String(bounded));
    if (message) appLoadingMessage.textContent = message;
  }

  function finishLoading() {
    updateLoadingProgress(100, "Console ready.");
    appLoading.setAttribute("aria-hidden", "true");
    appLoading.classList.add("is-complete");
    window.setTimeout(() => appLoading.setAttribute("hidden", ""), 300);
  }

  function setOperationProgress(active, label = "") {
    operationProgress.hidden = !active;
    operationProgress.setAttribute("aria-valuenow", active ? "50" : "0");
    if (label) actionStatus.textContent = label;
  }

  function loadEditorPreferences() {
    const stored = localStorage.getItem(editorPreferencesKey);
    if (stored !== null) {
      try {
        const parsed = JSON.parse(stored);
        Object.keys(editorPreferences).forEach((key) => {
          if (typeof parsed?.[key] === "boolean") editorPreferences[key] = parsed[key];
        });
      } catch (error) {
        console.warn("[FIX] Invalid editor preferences ignored", {
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }
    Object.entries(editorPreferenceInputs).forEach(([key, input]) => {
      input.checked = editorPreferences[key];
    });
  }

  function saveEditorPreferences() {
    localStorage.setItem(editorPreferencesKey, JSON.stringify(editorPreferences));
  }

  function schemaType(schema) {
    if (!schema) return "unknown";
    if (Array.isArray(schema.anyOf)) {
      return [...new Set(schema.anyOf.map(schemaType).filter((type) => type !== "unknown"))]
        .join(" or ");
    }
    if (Array.isArray(schema.type)) return schema.type.join(" or ");
    if (schema.type === "array") {
      const itemType = schemaType(schema.items);
      return itemType === "unknown" ? "array" : `array of ${itemType}`;
    }
    if (schema.type) return schema.type;
    if (schema.const !== undefined) return typeof schema.const;
    if (schema.enum?.length) return typeof schema.enum[0];
    return "value";
  }

  function schemaIncludesType(schema, type) {
    return schema?.type === type
      || (Array.isArray(schema?.type) && schema.type.includes(type))
      || schema?.anyOf?.some((variant) => schemaIncludesType(variant, type));
  }

  function resolveSchema(schema, root) {
    const reference = schema?.$ref;
    if (!reference?.startsWith("#/$defs/")) return schema;
    return root.$defs?.[reference.slice("#/$defs/".length)] || schema;
  }

  function meaningfulDescription(description) {
    return typeof description === "string"
      && description.trim().length > 0
      && !/configuration element\.\s*$/i.test(description.trim());
  }

  const enumValueDescriptions = {
    "source.requiredOutline": {
      glyf: "Use the TrueType `glyf` outline table.",
    },
    "source.allowedContainers": {
      ttf: "Emit an uncompressed TrueType font.",
      woff2: "Emit a compressed WOFF2 web font.",
    },
    "font.outputFormats": {
      ttf: "Generate a TrueType font artifact.",
      woff2: "Generate a compressed WOFF2 font artifact.",
    },
    "layout.boundaryMode": {
      "fire-then-revert": "Apply substitutions inside a boundary, then restore the boundary state.",
    },
    "layout.defaultScopePolicy": {
      fallback: "Use the configured fallback behavior when no scope matches.",
      error: "Stop processing when no scope matches.",
      "no-op": "Leave text unchanged when no scope matches.",
    },
    "mapping.mode": {
      directed: "Replace each source with its configured target only.",
      bidirectional: "Generate replacements in both directions for each pair.",
      involution: "Guarantee that applying the mapping twice restores the input.",
    },
    "mapping.duplicatePolicy": {
      error: "Reject duplicate source mappings.",
      "first-wins": "Keep the first mapping and ignore later duplicates.",
      "last-wins": "Replace the earlier mapping with the last duplicate.",
    },
    "mapping.targetCollisionPolicy": {
      error: "Reject mappings that target the same value.",
      warn: "Keep the mappings and report target collisions as warnings.",
    },
    "mapping.selfMapPolicy": {
      error: "Reject mappings whose source and target are identical.",
      keep: "Keep mappings whose source and target are identical.",
      "drop-with-warning": "Remove identical mappings and report a warning.",
    },
    "mapping.caseMode": {
      auto: "Choose case handling from the input and mapping data.",
      sensitive: "Treat uppercase and lowercase forms as distinct.",
      fold: "Match uppercase and lowercase forms together.",
    },
    "mapping.normalization": {
      NFC: "Normalize text using Unicode NFC.",
    },
    "css.fontDisplay": {
      auto: "Let the browser choose the font loading behavior.",
      block: "Hide text briefly while the font loads.",
      swap: "Show fallback text until the font loads.",
      fallback: "Use a short block period followed by fallback text.",
      optional: "Allow the browser to skip loading the font when appropriate.",
    },
    "css.fontSynthesis": {
      none: "Prevent synthetic bold and italic font faces.",
    },
    "codec.formats": {
      esm: "Generate an ECMAScript module package.",
      cjs: "Generate a CommonJS package.",
      iife: "Generate a browser-ready immediately invoked bundle.",
    },
    "codec.unknownScopePolicy": {
      "no-op": "Leave text unchanged when the scope is unknown.",
      error: "Stop processing when the scope is unknown.",
    },
    "verification.levels": {
      structural: "Check artifact structure and metadata.",
      shaping: "Check font shaping and substitution behavior.",
      codec: "Check codec output against the canonical mapping.",
      browser: "Check browser loading and rendering behavior.",
    },
    "verification.browsers": {
      chromium: "Run browser checks in Chromium.",
      firefox: "Run browser checks in Firefox.",
      webkit: "Run browser checks in WebKit.",
    },
    "verification.harfbuzz.implementation": {
      uharfbuzz: "Use the Python uharfbuzz implementation.",
      binary: "Use the HarfBuzz command-line binary.",
      both: "Run checks with both HarfBuzz implementations.",
    },
    "license.policy": {
      warn: "Report license issues as warnings.",
      error: "Fail validation when a license issue is found.",
      ignore: "Do not enforce license policy checks.",
    },
  };

  function enumValueDescription(path, value, title) {
    return enumValueDescriptions[path]?.[String(value)]
      || `Use the ${String(value)} option for ${title}.`;
  }

  function schemaAllowedValues(schema, type) {
    const values = schema?.enum?.length
      ? schema.enum
      : schema?.items?.enum?.length
        ? schema.items.enum
        : schema?.const !== undefined
          ? [schema.const]
          : null;
    if (values) return values.join(", ");
    const constraints = [];
    if (schema?.minimum !== undefined) constraints.push(`>= ${schema.minimum}`);
    if (schema?.exclusiveMinimum !== undefined) {
      constraints.push(`> ${schema.exclusiveMinimum}`);
    }
    if (schema?.maximum !== undefined) constraints.push(`<= ${schema.maximum}`);
    if (schema?.exclusiveMaximum !== undefined) {
      constraints.push(`< ${schema.exclusiveMaximum}`);
    }
    if (schema?.minLength !== undefined) constraints.push(`length >= ${schema.minLength}`);
    if (schema?.maxLength !== undefined) constraints.push(`length <= ${schema.maxLength}`);
    return constraints.length ? constraints.join(", ") : `any valid ${type}`;
  }

  function enrichEnumDescriptions(schema, path) {
    if (schema?.enum?.length) {
      schema.markdownEnumDescriptions = schema.enum.map((value) =>
        enumValueDescription(path, value, schema.title || path.split(".").pop() || "this setting"));
    }
    if (schema?.items?.enum?.length) {
      schema.items.markdownEnumDescriptions = schema.items.enum.map((value) =>
        enumValueDescription(path, value, schema.title || path.split(".").pop() || "this setting"));
    }
  }

  function enrichSchema(schema) {
    let normalizedDescriptions = 0;
    const seen = new Set();
    const visit = (node, root, path = [], seen = new Set()) => {
      if (!node || typeof node !== "object" || seen.has(node)) return;
      seen.add(node);
      Object.entries(node.properties || {}).forEach(([name, property]) => {
        const propertyPath = [...path, name];
        const resolved = resolveSchema(property, root);
        enrichEnumDescriptions(resolved, propertyPath.join("."));
        if (resolved) {
          const title = resolved.title || "Configuration element";
          const type = schemaType(resolved);
          const baseDescription = [
            property?.description,
            property?.markdownDescription,
            resolved.description,
            resolved.markdownDescription,
          ].find(meaningfulDescription)
            || property?.description
            || resolved.description
            || `${title} configuration element.`;
          const details = [
            `Type: ${type}.`,
            `Allowed values: ${schemaAllowedValues(resolved, type)}.`,
          ];
          const descriptionTarget = property && typeof property === "object"
            ? property
            : resolved;
          const enrichedDescription = [
            baseDescription,
            ...details.filter((detail) => !baseDescription.includes(detail.slice(0, -1))),
          ].join(" ");
          if (descriptionTarget.description !== enrichedDescription) {
            normalizedDescriptions += 1;
          }
          descriptionTarget.description = enrichedDescription;
          if (property?.$ref && !meaningfulDescription(resolved.description)) {
            resolved.description = enrichedDescription;
          }
        }
        visit(resolved, root, propertyPath, seen);
        visit(property?.items, root, [...propertyPath, "items"], seen);
        [["anyOf", property?.anyOf], ["oneOf", property?.oneOf], ["allOf", property?.allOf]]
          .forEach(([branch, variants]) => {
            if (!Array.isArray(variants)) return;
            variants.forEach((variant, variantIndex) => {
              visit(variant, root, [...propertyPath, branch, variantIndex], seen);
            });
          });
      });
      enrichEnumDescriptions(node, path.join("."));
      visit(node.items, root, [...path, "items"], seen);
      [node.anyOf, node.oneOf, node.allOf].forEach((variants, index) => {
        if (!Array.isArray(variants)) return;
        variants.forEach((variant, variantIndex) => {
          visit(variant, root, [...path, ["anyOf", "oneOf", "allOf"][index], variantIndex], seen);
        });
      });
    };
    visit(schema, schema, [], seen);
    Object.values(schema?.$defs || {}).forEach((definition) => visit(definition, schema, [], seen));
    console.info("[FIX] Schema descriptions normalized", { normalizedDescriptions });
    return schema;
  }

  async function updateEditorPreferences() {
    if (!monacoYaml) return;
    await monacoYaml.update({
      completion: editorPreferences.completion,
      hover: editorPreferences.hover,
      hoverSchemaSource: false,
      format: { enable: true },
      validate: editorPreferences.validate,
    });
    projectEditorView?.updateOptions({
      quickSuggestions: {
        other: editorPreferences.completion,
        comments: false,
        strings: editorPreferences.completion,
      },
      suggestOnTriggerCharacters: editorPreferences.completion,
      wordBasedSuggestions: editorPreferences.completion ? "matchingDocuments" : "off",
    });
    renderProjectValidation();
    console.info("[FIX] Project editor preferences updated", { ...editorPreferences });
  }

  async function changeEditorPreference(name, input) {
    const previous = editorPreferences[name];
    editorPreferences[name] = input.checked;
    saveEditorPreferences();
    try {
      await updateEditorPreferences();
    } catch (error) {
      editorPreferences[name] = previous;
      input.checked = previous;
      saveEditorPreferences();
      console.error("[FIX] Project editor preference update failed", {
        name,
        error: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }
  }

  const defaultLocale =
    (navigator.languages?.[0] || navigator.language || document.documentElement.lang || "en")
      .split("-")[0]
      .toLowerCase();
  const localeInputs = [
    document.querySelector("#source-locale"),
    document.querySelector("#target-locale"),
  ];
  function validLocale(value) {
    const normalized = value.trim().toLowerCase();
    if (!/^[a-z]{2,3}$/.test(normalized)) return false;
    try {
      return new Intl.Locale(normalized).language === normalized;
    } catch {
      return false;
    }
  }

  function validateLocaleInput(input) {
    const value = input.value.trim().toLowerCase();
    const valid = validLocale(value);
    input.value = value;
    input.setCustomValidity(valid ? "" : "Use a standard two- or three-letter language code.");
    input.setAttribute("aria-invalid", valid ? "false" : "true");
    return valid;
  }

  localeInputs.forEach((input) => {
    input.value = validLocale(defaultLocale) ? defaultLocale : "en";
    validateLocaleInput(input);
    input.addEventListener("input", () => validateLocaleInput(input));
    input.addEventListener("change", () => validateLocaleInput(input));
  });

  function selectedValue(selector) {
    return document.querySelector(selector).value || undefined;
  }

  function saveFontPath(path) {
    if (!path) return;
    localStorage.setItem(fontPathKey, path);
    console.info("[FIX] Source font selection persisted", { path });
  }

  function refreshSourceFont(path) {
    const style = document.querySelector("#source-font-style");
    if (!style) return;
    const selectedPath = path
      ? `?path=${encodeURIComponent(path)}&cacheBust=${Date.now()}`
      : "";
    style.textContent = `
      @font-face {
        font-family: "ShieldFont Original";
        src: url("/api/source-font${selectedPath}");
        font-display: swap;
      }
    `;
    console.info("[FIX] Source font stylesheet refreshed", { path: path || null });
  }

  function requestPayload(action) {
    localeInputs.forEach(validateLocaleInput);
    if (localeInputs.some((input) => !validLocale(input.value))) {
      throw new Error("Source and target locales must be standard language codes.");
    }
    const payload = {
      outputFormat: document.querySelector("#output-format").value,
      sourceLocale: document.querySelector("#source-locale").value,
      targetLocale: document.querySelector("#target-locale").value,
    };
    if (["font-inspect", "font-select"].includes(action)) {
      payload.path = selectedValue("#font-path");
      payload.font = selectedValue("#font-path");
    } else if (["build", "css-build"].includes(action)) {
      payload.sourceFont = selectedValue("#font-path");
    } else if (["dict-validate", "dict-normalize"].includes(action)) {
      payload.path = selectedValue("#default-dictionary-path");
    }
    if (action === "css-build") {
      payload.output = selectedValue("#css-output");
      payload.assetBaseUrl = selectedValue("#css-asset-base");
      payload.fontDisplay = selectedValue("#css-font-display");
      payload.includeTtfFallback = document.querySelector("#css-ttf-fallback").checked;
      payload.embedFont = document.querySelector("#css-embed-font").checked;
    }
    return Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== undefined));
  }

  async function getJson(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "Request failed");
    return payload;
  }

  function showError(target, error) {
    target.textContent = `Error: ${error.message}`;
  }

  function refreshShieldFontCss(path) {
    const stylesheet = document.querySelector("#shieldfont-css");
    const selectedPath = path ? `&path=${encodeURIComponent(path)}` : "";
    stylesheet.href = `/api/shieldfont.css?cacheBust=${Date.now()}${selectedPath}`;
  }

  function renderArtifactSummary(payload) {
    if (!artifactSummary) return;
    artifactSummary.textContent = JSON.stringify(
      {
        outputDir: payload.outputDir,
        artifacts: payload.artifacts || {},
        bundles: payload.bundles || {},
      },
      null,
      2,
    );
  }

  async function loadStatus() {
    try {
      const payload = await getJson("/api/status", { headers: { Accept: "application/json" } });
      status.textContent = `Ready. Project: ${payload.projectRoot}`;
      updateLoadingProgress(20, "Connected to the local server.");
    } catch (error) {
      showError(status, error);
      updateLoadingProgress(20, "Server status unavailable; continuing.");
    }
  }

  async function loadFiles() {
    try {
      const previousValues = Object.fromEntries(
        fileSelects.map((select) => [select.id, select.value]),
      );
      const [payload, config] = await Promise.all([
        getJson("/api/files", { headers: { Accept: "application/json" } }),
        getJson("/api/config", { headers: { Accept: "application/json" } }),
      ]);
      fileSelects.forEach((select) => {
        const kind = select.dataset.fileKind;
        select.replaceChildren();
        (payload.files || [])
          .filter((file) => file.kind === kind)
          .forEach((file) => {
            const option = document.createElement("option");
            option.value = file.path;
            option.textContent = file.path;
            select.append(option);
          });
        if (!select.options.length) {
          const option = document.createElement("option");
          option.textContent = "No matching files";
          option.value = "";
          select.append(option);
        }
      });
      const parameters = config.parameters || config;
      const fontPath = document.querySelector("#font-path");
      const storedFontPath = localStorage.getItem(fontPathKey);
      const configuredFontPath = parameters.source?.path;
      const preferredFontPath =
        previousValues["font-path"] || storedFontPath || configuredFontPath;
      if (preferredFontPath
        && [...fontPath.options].some((option) => option.value === preferredFontPath)) {
        fontPath.value = preferredFontPath;
      }
      if (fontPath.value) saveFontPath(fontPath.value);
      refreshSourceFont(fontPath.value);
      const dictionaryPath = document.querySelector("#default-dictionary-path");
      const configuredDictionaryPath =
        config.defaultDictionary || "dictionaries/default.csv";
      const preferredDictionaryPath =
        previousValues["default-dictionary-path"] || configuredDictionaryPath;
      if ([...dictionaryPath.options]
        .some((option) => option.value === preferredDictionaryPath)) {
        dictionaryPath.value = preferredDictionaryPath;
      }
      const css = parameters.css || {};
      const cssClasses = css.classes || {};
      const shieldFontText = document.querySelector("#shieldfont-text");
      if (cssClasses.shield) {
        shieldFontText.classList.remove("sf-shield");
        shieldFontText.classList.add(cssClasses.shield);
      }

      if (css.file) document.querySelector("#css-output").value = css.file;
      if (css.assetBaseUrl) document.querySelector("#css-asset-base").value = css.assetBaseUrl;
      if (css.fontDisplay) document.querySelector("#css-font-display").value = css.fontDisplay;
      document.querySelector("#css-embed-font").checked = css.embedFont === true;
      updateLoadingProgress(35, "Loaded project inputs and parameters.");
    } catch (error) {
      showError(status, error);
      updateLoadingProgress(35, "Some project inputs could not be loaded.");
      console.error("[FIX] Project data load failed", {
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  function dictionaryCacheKey(path) {
    return `shieldfont.dictionary.v1:${path}`;
  }

  function projectCacheKey(path) {
    return `shieldfont.project.v1:${path}`;
  }

  function projectValue() {
    return projectEditorView.getValue();
  }

  function setProjectValue(value) {
    projectEditorView.setValue(value);
    lastProjectEditorValue = value;
    projectEditorView.setScrollTop(0);
    projectEditorView.setScrollLeft(0);
  }

  function schemaForPath(path) {
    return path.reduce((schema, key) => {
      const property = schema?.properties?.[key];
      return resolveSchema(property, projectSchema);
    }, projectSchema);
  }

  function parseYamlKeyLine(line) {
    const match = line.match(/^(\s*)(?:-\s*)?([A-Za-z0-9_-]+):(?:\s*(.*))?$/);
    if (!match) return null;
    return {
      indent: match[1].length,
      key: match[2],
      value: match[3] || "",
    };
  }

  function yamlPathForLine(model, lineNumber) {
    const stack = [];
    for (let index = 1; index <= lineNumber; index += 1) {
      const parsed = parseYamlKeyLine(model.getLineContent(index));
      if (!parsed) continue;
      while (stack.length && stack.at(-1).indent >= parsed.indent) stack.pop();
      stack.push(parsed);
    }
    const current = stack.pop();
    return current ? [...stack.map((item) => item.key), current.key] : [];
  }

  function schemaForYamlLine(model, lineNumber) {
    const path = yamlPathForLine(model, lineNumber);
    return path.length ? schemaForPath(path) : null;
  }

  function renderProjectBreadcrumbs(path) {
    if (!projectBreadcrumbs) return;
    projectBreadcrumbs.replaceChildren();
    if (!path.length) {
      projectBreadcrumbs.hidden = true;
      return;
    }
    path.forEach((segment, index) => {
      if (index > 0) {
        const separator = document.createElement("span");
        separator.className = "project-breadcrumb-separator";
        separator.textContent = "›";
        separator.setAttribute("aria-hidden", "true");
        projectBreadcrumbs.append(separator);
      }
      const breadcrumb = document.createElement("span");
      breadcrumb.className = "project-breadcrumb";
      breadcrumb.textContent = segment;
      projectBreadcrumbs.append(breadcrumb);
    });
    projectBreadcrumbs.hidden = false;
  }

  function renderProjectProblems(markers) {
    if (!projectProblems) return;
    projectProblems.replaceChildren();
    markers
      .filter((marker) => marker.severity !== monacoInstance.MarkerSeverity.Hint)
      .forEach((marker) => {
        const problem = document.createElement("button");
        problem.className = "project-problem";
        problem.type = "button";
        problem.setAttribute("role", "listitem");
        const icon = document.createElement("span");
        icon.className = "codicon";
        icon.classList.add(
          marker.severity === monacoInstance.MarkerSeverity.Info
            ? "codicon-info"
            : marker.severity === monacoInstance.MarkerSeverity.Warning
              ? "codicon-warning"
              : "codicon-error",
        );
        const text = document.createElement("span");
        text.className = "project-problem-text";
        text.textContent = marker.message;
        problem.append(icon, text);
        problem.addEventListener("click", () => {
          projectEditorView.setPosition({
            lineNumber: marker.startLineNumber,
            column: marker.startColumn,
          });
          projectEditorView.revealLineInCenter(marker.startLineNumber);
          projectEditorView.focus();
        });
        projectProblems.append(problem);
      });
  }

  function numericLiteral(value) {
    return value === ""
      || /^[+-]?(?:\d+(?:\.\d*)?|\.\d*)(?:[eE][+-]?\d*)?$/.test(value);
  }

  function invalidNumericValue(model) {
    for (let lineNumber = 1; lineNumber <= model.getLineCount(); lineNumber += 1) {
      const parsed = parseYamlKeyLine(model.getLineContent(lineNumber));
      if (!parsed || !parsed.value.trim()) continue;
      const schema = schemaForYamlLine(model, lineNumber);
      const numericType = ["integer", "number"].find((type) => schemaIncludesType(schema, type));
      if (numericType) {
        const value = parsed.value.split(/\s+#/, 1)[0].trim();
        if (!numericLiteral(value)) return { lineNumber, value, type: numericType };
      }
    }
    return null;
  }

  function registerProjectCompletionProvider() {
    projectCompletionDisposable?.dispose();
    projectCompletionDisposable = monacoInstance.languages.registerCompletionItemProvider("yaml", {
      triggerCharacters: [":", " "],
      provideCompletionItems(model, position) {
        if (!editorPreferences.completion || model.uri.toString() !== "file:///shieldfont.yml") {
          return { suggestions: [] };
        }
        const schema = schemaForYamlLine(model, position.lineNumber);
        if (!schema) return { suggestions: [] };
        const values = schema.enum?.length
          ? schema.enum
          : schema.items?.enum?.length
            ? schema.items.enum
            : schema.type === "boolean"
              ? [true, false]
              : null;
        if (!values) return { suggestions: [] };
        const descriptions = schema.markdownEnumDescriptions
          || schema.items?.markdownEnumDescriptions
          || [];
        return {
          suggestions: values.map((value, index) => ({
            label: String(value),
            kind: monacoInstance.languages.CompletionItemKind.Value,
            insertText: String(value),
            documentation: descriptions[index] || `Allowed value: ${String(value)}.`,
          })),
        };
      },
    });
  }

  function projectMarkers() {
    const model = projectEditorView?.getModel();
    return model
      ? monacoInstance.editor.getModelMarkers({ resource: model.uri })
      : [];
  }

  function renderProjectValidation() {
    const model = projectEditorView?.getModel();
    if (!model) return;
    if (!editorPreferences.validate) {
      monacoInstance.editor.setModelMarkers(model, "shieldfont-yaml", []);
      renderProjectProblems([]);
      projectValidation.classList.remove("error", "valid");
      projectValidation.textContent = "YAML validation disabled.";
      return;
    }
    const yamlDiagnostics = parseDocument(projectValue()).errors;
    monacoInstance.editor.setModelMarkers(
      model,
      "shieldfont-yaml",
      yamlDiagnostics.map((error) => {
        const [start, end = start + 1] = error.pos || [0, 1];
        return {
          startLineNumber: model.getPositionAt(start).lineNumber,
          startColumn: model.getPositionAt(start).column,
          endLineNumber: model.getPositionAt(end).lineNumber,
          endColumn: model.getPositionAt(end).column,
          message: error.message,
          severity: monacoInstance.MarkerSeverity.Error,
        };
      }),
    );
    const diagnostics = projectMarkers();
    renderProjectProblems(diagnostics);
    projectValidation.classList.toggle("error", diagnostics.length > 0);
    projectValidation.classList.toggle("valid", diagnostics.length === 0);
    projectValidation.textContent = diagnostics.length === 0
      ? "YAML syntax valid."
      : `${diagnostics.length} YAML syntax error(s): ${diagnostics[0].message}`;
  }

  async function createProjectEditor() {
    updateLoadingProgress(45, "Loading the YAML editor schema.");
    projectSchema = enrichSchema(await getJson("/api/config/schema", {
      headers: { Accept: "application/json" },
    }));
    const workerUrl = (_moduleId, label) =>
      label === "yaml"
        ? "/api/monaco-worker/yaml"
        : "/vendor/monaco-editor/esm/vs/editor/editor.worker.js";
    globalThis.MonacoEnvironment = {
      getWorker(moduleId, label) {
        const url = workerUrl(moduleId, label);
        return new Worker(url, { type: "module" });
      },
      getWorkerUrl: workerUrl,
    };
    monacoInstance = monaco;
    monacoYaml = configureMonacoYaml(monacoInstance, {
      enableSchemaRequest: false,
      completion: editorPreferences.completion,
      hover: editorPreferences.hover,
      hoverSchemaSource: false,
      format: { enable: true },
      validate: editorPreferences.validate,
      schemas: [
        {
          fileMatch: ["**/shieldfont.yml"],
          uri: new URL("/api/config/schema", window.location.href).toString(),
          schema: projectSchema,
        },
      ],
    });
    registerProjectCompletionProvider();
    const model = monacoInstance.editor.createModel(
      "",
      "yaml",
      monacoInstance.Uri.parse("file:///shieldfont.yml"),
    );

    projectEditorView = monacoInstance.editor.create(projectEditor, {
      model,
      automaticLayout: true,
      fixedOverflowWidgets: true,
      folding: true,
      formatOnPaste: true,
      formatOnType: true,
      showFoldingControls: "always",
      foldingStrategy: "auto",
      lineNumbers: "on",
      minimap: { enabled: false },
      padding: { top: 8, bottom: 8 },
      quickSuggestions: {
        other: editorPreferences.completion,
        comments: false,
        strings: editorPreferences.completion,
      },
      renderLineHighlight: "line",
      scrollBeyondLastLine: false,
      smoothScrolling: true,
      suggestOnTriggerCharacters: editorPreferences.completion,
      tabSize: 2,
      theme: "vs-dark",
      wordBasedSuggestions: editorPreferences.completion ? "matchingDocuments" : "off",
      wordWrap: "off",
    });
    projectEditor.addEventListener("click", (event) => {
      const target = event.target instanceof Element
        ? event.target.closest(".codicon[class*='folding-']")
        : null;
      if (!target) return;
      event.preventDefault();
      event.stopPropagation();
      const overlay = target.parentElement;
      const top = Number.parseFloat(overlay?.style.top || "0");
      const lineHeight = projectEditorView.getTopForLineNumber(2)
        - projectEditorView.getTopForLineNumber(1);
      const lineNumber = Math.max(
        1,
        Math.floor((top + projectEditorView.getScrollTop()) / lineHeight) + 1,
      );
      projectEditorView.setPosition({ lineNumber, column: 1 });
      projectEditorView.trigger("folding-control", "editor.fold", {});
    }, true);
    projectEditorView.onDidChangeModelContent(() => {
      if (guardingNumericEdit) return;
      const invalid = invalidNumericValue(projectEditorView.getModel());
      if (invalid) {
        guardingNumericEdit = true;
        projectEditorView.setValue(lastProjectEditorValue);
        guardingNumericEdit = false;
        console.warn("[FIX] Numeric editor input rejected", invalid);
        return;
      }
      lastProjectEditorValue = projectValue();
      projectEditor.dataset.content = projectValue();
      renderProjectValidation();
    });
    projectEditorView.onDidChangeModelDecorations(renderProjectValidation);
    projectEditorView.onDidChangeCursorPosition(({ position }) => {
      renderProjectBreadcrumbs(yamlPathForLine(model, position.lineNumber));
    });
    projectEditorView.onDidScrollChange((event) => {
      if (event.scrollTopChanged) {
        projectEditor.dataset.scrollTop = String(event.scrollTop);
      }
    });
    window.__shieldfontProjectEditor = projectEditorView;
    projectEditor.dataset.content = "";
    projectEditor.dataset.scrollTop = "0";
    lastProjectEditorValue = "";
    renderProjectBreadcrumbs(
      yamlPathForLine(model, projectEditorView.getPosition()?.lineNumber || 1),
    );
    renderProjectValidation();
    console.info("[FIX] YAML module editor initialized", {
      module: "monaco-editor",
      parser: "yaml",
      lineNumbers: true,
      folding: true,
      validation: editorPreferences.validate,
    });
    updateLoadingProgress(75, "YAML editor ready.");
  }

  function applyProject(payload, { preferCache = true } = {}) {
    const path = payload.path || "shieldfont.yml";
    const cached = preferCache ? localStorage.getItem(projectCacheKey(path)) : null;
    setProjectValue(cached !== null ? cached : payload.content || "");
    projectEditorView.focus();
    projectEditor.dataset.path = path;
    projectStatus.textContent = cached !== null
      ? `Loaded cached ${path}.`
      : `Editing ${path}.`;
    console.info("[FIX] YAML editor focused for direct text editing", { path });
  }

  async function loadProject() {
    const path = "shieldfont.yml";
    const cached = localStorage.getItem(projectCacheKey(path));
    if (cached !== null) {
      applyProject({ path, content: cached });
      console.info("[FIX] Project YAML loaded from cache", {
        path,
        characters: cached.length,
      });
      updateLoadingProgress(90, "Restored the project configuration.");
      return;
    }
    const payload = await getJson("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ action: "project-read", path }),
    });
    applyProject(payload, { preferCache: false });
    localStorage.setItem(projectCacheKey(payload.path || path), payload.content || "");
    console.info("[FIX] Project YAML loaded from server", {
      path: payload.path || path,
      characters: (payload.content || "").length,
    });
    updateLoadingProgress(90, "Loaded the project configuration.");
  }

  async function loadDefaultProject() {
    const path = "shieldfont.yml";
    const payload = await getJson("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ action: "project-read", path }),
    });
    applyProject(payload, { preferCache: false });
    localStorage.setItem(projectCacheKey(payload.path || path), payload.content || "");
    projectStatus.textContent = `Loaded default ${payload.path || path} from server.`;
    console.info("[FIX] Default project YAML loaded from server", {
      path: payload.path || path,
      characters: (payload.content || "").length,
    });
  }

  function saveProjectLocal() {
    const path = projectEditor.dataset.path || "shieldfont.yml";
    const content = projectValue();
    localStorage.setItem(projectCacheKey(path), content);
    projectStatus.textContent = `Saved ${path} to localStorage.`;
    console.info("[FIX] Project YAML cached", {
      path,
      characters: content.length,
    });
  }

  async function saveProjectFile() {
    const path = projectEditor.dataset.path || "shieldfont.yml";
    const content = projectValue();
    const payload = await getJson("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        action: "project-save",
        path,
        content,
      }),
    });
    localStorage.setItem(projectCacheKey(payload.path || path), content);
    projectEditor.dataset.path = payload.path || path;
    projectStatus.textContent = `Saved ${payload.path || path}.`;
    console.info("[FIX] Project YAML saved", {
      path: payload.path || path,
      characters: content.length,
    });
  }

  async function importProjectFile() {
    const file = projectFile.files?.[0];
    if (!file) return;
    const content = await file.text();
    setProjectValue(content);
    const fileName = file.name.toLowerCase();
    projectEditor.dataset.path =
      fileName.endsWith(".yml") || fileName.endsWith(".yaml")
        ? file.name
        : "shieldfont.yml";
    projectStatus.textContent = `Loaded ${file.name}. Save to localStorage or the project file.`;
    projectFile.value = "";
    console.info("[FIX] Project YAML file imported", {
      name: file.name,
      characters: content.length,
    });
  }

  function downloadProjectFile() {
    const path = projectEditor.dataset.path || "shieldfont.yml";
    const filename = path.split(/[\\/]/).pop() || "shieldfont.yml";
    const content = projectValue();
    const blob = new Blob([content], { type: "text/yaml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename.endsWith(".yml") || filename.endsWith(".yaml")
      ? filename
      : `${filename}.yml`;
    link.click();
    URL.revokeObjectURL(url);
    projectStatus.textContent = `Downloaded ${link.download}.`;
    console.info("[FIX] Project YAML file exported", {
      name: link.download,
      characters: content.length,
    });
  }

  async function requestDictionary(path) {
    const payload = await getJson("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ action: "dict-read", ...(path ? { path } : {}) }),
    });
    return payload;
  }

  function applyDictionary(payload, { preferCache = true } = {}) {
    const path = payload.path || "dictionaries/default.csv";
    const cached = preferCache ? localStorage.getItem(dictionaryCacheKey(path)) : null;
    dictionaryEditor.value = cached !== null ? cached : payload.content ?? "";
    dictionaryEditor.dataset.path = path;
    dictionaryStatus.textContent = cached !== null
      ? `Loaded cached ${path}.`
      : `Editing ${path}.`;
  }

  async function uploadFontFile() {
    const file = fontFile.files?.[0];
    if (!file) return;
    compareButton.disabled = true;
    fontStatus.textContent = `Uploading ${file.name}...`;
    try {
      const response = await fetch(
        `/api/files/upload?name=${encodeURIComponent(file.name)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": file.type || "application/octet-stream",
            Accept: "application/json",
          },
          body: file,
        },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || "Font upload failed");
      await loadFiles();
      const fontPath = document.querySelector("#font-path");
      fontPath.value = payload.path;
      selectedFontReady = false;
      saveFontPath(payload.path);
      fontStatus.textContent = `Uploaded ${file.name} to ${payload.path}.`;
      compareButton.disabled = !await rebuildSelectedFont();
      console.info("[FIX] Source font uploaded", {
        name: file.name,
        path: payload.path,
        bytes: file.size,
      });
    } catch (error) {
      fontStatus.textContent = "Source font upload failed.";
      console.error("[FIX] Source font upload failed", {
        name: file.name,
        error: error instanceof Error ? error.message : String(error),
      });
      compareButton.disabled = true;
      throw error;
    } finally {
      fontFile.value = "";
    }
  }

  async function loadDictionary() {
    const path = selectedValue("#default-dictionary-path") || "dictionaries/default.csv";
    const cached = localStorage.getItem(dictionaryCacheKey(path));
    if (cached !== null && cached.trim().length > 0) {
      applyDictionary({ path, content: cached });
      console.info("[FIX] Dictionary loaded from cache", {
        path,
        characters: cached.length,
      });
      return;
    }
    if (cached !== null) {
      console.info("[FIX] Empty dictionary cache ignored", {
        path,
        characters: cached.length,
      });
    }
    const payload = await requestDictionary(path);
    applyDictionary(payload, { preferCache: false });
    localStorage.setItem(
      dictionaryCacheKey(payload.path || path),
      payload.content || "",
    );
    console.info("[FIX] Dictionary loaded from server", {
      path: payload.path || path,
      characters: (payload.content || "").length,
    });
  }

  async function loadDefaultDictionary() {
    const payload = await requestDictionary();
    applyDictionary(payload, { preferCache: false });
    localStorage.setItem(dictionaryCacheKey(payload.path), payload.content || "");
    const dictionaryPath = document.querySelector("#default-dictionary-path");
    if ([...dictionaryPath.options].some((option) => option.value === payload.path)) {
      dictionaryPath.value = payload.path;
    }
    console.info("[FIX] System dictionary loaded", { path: payload.path });
  }

  async function saveDictionary({ silent = false } = {}) {
    const path = dictionaryEditor.dataset.path
      || selectedValue("#default-dictionary-path")
      || "dictionaries/default.csv";
    const content = dictionaryEditor.value;
    localStorage.setItem(dictionaryCacheKey(path), content);
    const payload = await getJson("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        action: "dict-save",
        path,
        content,
      }),
    });
    dictionaryEditor.dataset.path = payload.path;
    if (!silent) dictionaryStatus.textContent = `Saved ${payload.path}.`;
    console.info("[FIX] Dictionary cached", { path: payload.path, characters: content.length });
    return payload;
  }

  async function importDictionaryFile() {
    const file = dictionaryFile.files?.[0];
    if (!file) return;
    dictionaryEditor.value = await file.text();
    dictionaryStatus.textContent = `Loaded ${file.name}. Save to persist it.`;
    dictionaryFile.value = "";
    console.info("[FIX] Dictionary file imported", {
      name: file.name,
      characters: dictionaryEditor.value.length,
    });
  }

  function downloadDictionary() {
    const path = dictionaryEditor.dataset.path || "dictionaries/default.csv";
    const filename = path.split(/[\\/]/).pop() || "dictionary.csv";
    const blob = new Blob([dictionaryEditor.value], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    dictionaryStatus.textContent = `Downloaded ${link.download}.`;
    console.info("[FIX] Dictionary file exported", {
      name: link.download,
      characters: dictionaryEditor.value.length,
    });
  }

  function renderProcesses(items) {
    processes.replaceChildren();
    (items || []).forEach((item) => {
      const article = document.createElement("article");
      article.className = "process";
      const title = document.createElement("strong");
      title.textContent = `${item.action} - ${item.status}`;
      const detail = document.createElement("span");
      detail.textContent = item.processId || item.id || "";
      article.append(title, detail);
      processes.append(article);
    });
    if (!processes.children.length) processes.textContent = "No processes recorded.";
  }

  async function loadProcesses() {
    try {
      const payload = await getJson("/api/processes", { headers: { Accept: "application/json" } });
      renderProcesses(payload.processes);
    } catch (error) {
      showError(processes, error);
    }
  }

  async function loadResults() {
    try {
      const payload = await getJson("/api/results", { headers: { Accept: "application/json" } });
      results.replaceChildren();
      (payload.results || []).forEach((item) => {
        const button = document.createElement("button");
        button.className = "secondary";
        button.textContent = `${item.path} (${item.size} bytes)`;
        button.addEventListener("click", async () => {
          try {
            const view = await getJson(`/api/results?path=${encodeURIComponent(item.path)}`, {
              headers: { Accept: "application/json" },
            });
            result.textContent = JSON.stringify(view.result || view.content || view, null, 2);
          } catch (error) {
            showError(result, error);
          }
        });
        results.append(button);
      });
      if (!results.children.length) results.textContent = "No results available.";
    } catch (error) {
      showError(results, error);
    }
  }

  async function setDefaultDictionary(path) {
    await getJson("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          action: "dict-default-set",
          path,
        }),
      });
    console.info("[FIX] Server default dictionary updated", { path });
    await loadDictionary();
  }

  function buildLlmPrompt() {
    return [
      "You are a linguistic analysis assistant that creates high-quality bidirectional word-replacement dictionaries.",
      "",
      "Read only the source text enclosed between the exact `{text}` and `{/text}` markers.",
      "",
      "Your task is to create a deterministic set of unique, grammatically compatible, semantically distinct word pairs suitable for reliable automated whole-word replacement.",
      "",
      "Each pair represents a bidirectional relationship:",
      "",
      "* if `A` is paired with `B`, then `B` is paired with `A`;",
      "* applying the replacement twice must restore the original word;",
      "* every word may participate in exactly one pair.",
      "",
      "The output CSV must contain each logical pair only once:",
      "",
      "source,target",
      "A,B",
      "",
      "Do not output the reverse row `B,A`. It will be generated automatically during later dictionary processing.",
      "",
      "## Internal processing pipeline",
      "",
      "Perform all stages below internally.",
      "",
      "Do not output intermediate candidates, annotations, explanations, scores, rejected entries, or diagnostic information.",
      "",
      "### Stage 1 — Normalize the source text",
      "",
      "1. Treat the input as UTF-8.",
      "2. Normalize extracted words to Unicode NFC.",
      "3. Extract only complete uninterrupted sequences of Unicode letters.",
      "4. Convert dictionary entries to lowercase.",
      "5. Do not create separate entries for lowercase, Capitalized, or ALL-CAPS forms.",
      "6. Preserve the original language and writing system.",
      "7. Do not translate words.",
      "",
      "### Stage 2 — Extract candidate words",
      "",
      "Extract only complete word forms that occur verbatim in the source text.",
      "",
      "Use actual surface forms from the text rather than replacing them with lemmas.",
      "",
      "Different inflected forms may be treated as separate candidates when they occur separately in the source text.",
      "",
      "Exclude:",
      "",
      "* punctuation;",
      "* whitespace;",
      "* markup;",
      "* HTML entities;",
      "* URLs;",
      "* email addresses;",
      "* code;",
      "* identifiers;",
      "* filenames;",
      "* numbers;",
      "* alphanumeric tokens;",
      "* words containing spaces;",
      "* words containing hyphens;",
      "* words containing apostrophes;",
      "* mixed-script words;",
      "* abbreviations;",
      "* initials;",
      "* proper names;",
      "* geographical names;",
      "* organization names;",
      "* product names;",
      "* protected technical terms;",
      "* malformed words;",
      "* obvious spelling errors;",
      "* words whose grammatical role cannot be determined reliably.",
      "",
      "### Stage 3 — Rank candidates by usefulness",
      "",
      "Prioritize words that are likely to provide useful coverage in the source text.",
      "",
      "Prefer:",
      "",
      "1. frequently occurring words;",
      "2. meaningful content words;",
      "3. nouns;",
      "4. verbs;",
      "5. adjectives;",
      "6. adverbs;",
      "7. grammatically unambiguous word forms;",
      "8. words for which a structurally compatible partner exists;",
      "9. words that occur in semantically important passages.",
      "",
      "Deprioritize or omit:",
      "",
      "* extremely rare words;",
      "* archaic words;",
      "* accidental forms;",
      "* highly polysemous words;",
      "* words that can belong to several parts of speech;",
      "* words whose interpretation changes strongly with context;",
      "* words for which no reliable partner exists.",
      "",
      "Normally exclude core function words, including:",
      "",
      "* conjunctions;",
      "* prepositions;",
      "* particles;",
      "* pronouns;",
      "* auxiliary verbs;",
      "* determiners;",
      "* other closed-class grammatical words.",
      "",
      "Include such a word only when its grammatical function is unambiguous and its replacement does not make the surrounding sentence structurally unnatural.",
      "",
      "### Stage 4 — Determine the morphosyntactic signature",
      "",
      "Determine the grammatical characteristics of every candidate from its use in the source context.",
      "",
      "Pair words only when all relevant grammatical properties are compatible.",
      "",
      "For nouns, consider:",
      "",
      "* part of speech;",
      "* grammatical gender;",
      "* number;",
      "* case;",
      "* animacy;",
      "* declension behavior.",
      "",
      "For adjectives and participles, consider:",
      "",
      "* part of speech;",
      "* full or short form;",
      "* gender;",
      "* number;",
      "* case;",
      "* degree of comparison;",
      "* tense and voice when applicable.",
      "",
      "For verbs, consider:",
      "",
      "* part of speech;",
      "* aspect;",
      "* tense;",
      "* person;",
      "* number;",
      "* gender when applicable;",
      "* mood;",
      "* transitivity;",
      "* reflexivity;",
      "* voice;",
      "* syntactic government;",
      "* argument structure.",
      "",
      "For adverbs, consider:",
      "",
      "* part of speech;",
      "* degree of comparison;",
      "* syntactic role;",
      "* relevant semantic usage class.",
      "",
      "Do not pair words merely because they belong to the same broad part of speech.",
      "",
      "### Stage 5 — Form candidate pairs",
      "",
      "Create pairs only between words with compatible morphosyntactic signatures.",
      "",
      "A valid pair must satisfy all of the following:",
      "",
      "1. Both words occur in the source text.",
      "2. Both values are complete standalone words.",
      "3. Both words use the same language and script.",
      "4. Both words have compatible grammatical forms.",
      "5. Replacing one word with the other should preserve the surrounding grammatical structure as much as possible.",
      "6. The words must represent clearly different concepts.",
      "7. The words should preferably belong to different semantic domains.",
      "8. Neither word may be a grammatical form of the other.",
      "9. Neither word may participate in any other pair.",
      "10. The replacement must not require a different preposition, case, complement type, or sentence construction.",
      "",
      "The preferred relationship is:",
      "",
      "* high grammatical compatibility;",
      "* low semantic similarity;",
      "* different concepts;",
      "* plausible local syntax after replacement.",
      "",
      "### Stage 6 — Apply semantic rejection rules",
      "",
      "Reject a candidate pair when any of the following is true:",
      "",
      "* the words are identical;",
      "* the words differ only by capitalization;",
      "* the words differ only by Unicode representation;",
      "* the words have the same lemma;",
      "* one word is an inflected form of the other;",
      "* one word is an obvious derivation of the other;",
      "* the words are synonyms;",
      "* the words are near-synonyms;",
      "* one word is a direct hypernym or hyponym of the other;",
      "* the words describe the same narrow concept;",
      "* the replacement preserves most of the original meaning;",
      "* the replacement clearly breaks grammar;",
      "* the words have incompatible syntactic behavior;",
      "* the words have incompatible verb valency;",
      "* the words require different grammatical government;",
      "* either word is too ambiguous to classify confidently.",
      "",
      "Antonyms are allowed but should not dominate the dictionary.",
      "",
      "Prefer grammatically compatible words from different semantic domains over simple synonym or antonym substitutions.",
      "",
      "When compatibility cannot be established confidently, omit the pair instead of guessing.",
      "",
      "### Stage 7 — Enforce pairing invariants",
      "",
      "The dictionary must consist exclusively of disjoint two-word pairs.",
      "",
      "For every output row `A,B`, enforce:",
      "",
      "* `A` is not equal to `B`;",
      "* `A` occurs in exactly one row;",
      "* `B` occurs in exactly one row;",
      "* `A` does not occur elsewhere as either source or target;",
      "* `B` does not occur elsewhere as either source or target;",
      "* the expanded dictionary can contain `A → B` and `B → A`;",
      "* applying the expanded dictionary twice restores both original words.",
      "",
      "Forbidden structures include:",
      "",
      "* identity mappings such as `A → A`;",
      "* one-way mappings;",
      "* many-to-one mappings;",
      "* one-to-many mappings;",
      "* chains such as `A → B` and `B → C`;",
      "* cycles longer than two;",
      "* repeated logical pairs;",
      "* reversed duplicate rows such as both `A,B` and `B,A`.",
      "",
      "### Stage 8 — Check token and character safety",
      "",
      "Prefer words composed only of ordinary alphabetic characters used by the detected language.",
      "",
      "Exclude words containing:",
      "",
      "* unsupported or unusual presentation characters;",
      "* invisible characters;",
      "* control characters;",
      "* emoji;",
      "* private-use characters;",
      "* characters from another script;",
      "* unsafe combining sequences;",
      "* internal punctuation.",
      "",
      "Do not split words into:",
      "",
      "* prefixes;",
      "* suffixes;",
      "* stems;",
      "* roots;",
      "* syllables;",
      "* substrings;",
      "* arbitrary fragments.",
      "",
      "Avoid one-letter words.",
      "",
      "Use two-letter words only when they are meaningful, grammatically unambiguous, and safe as standalone whole-word entries.",
      "",
      "### Stage 9 — Select the optimal non-conflicting subset",
      "",
      "From all valid candidate pairs, choose the strongest non-conflicting subset.",
      "",
      "Prioritize:",
      "",
      "1. higher frequency in the source text;",
      "2. greater coverage of meaningful content;",
      "3. grammatical compatibility;",
      "4. semantic distance;",
      "5. low ambiguity;",
      "6. diversity of concepts;",
      "7. reliable syntactic behavior;",
      "8. absence of competing pair assignments.",
      "",
      "Do not maximize the number of rows at the expense of quality.",
      "",
      "A smaller, consistent, unambiguous dictionary is preferable to a larger dictionary containing weak or conflicting pairs.",
      "",
      "### Stage 10 — Final validation",
      "",
      "Before producing the output, verify that:",
      "",
      "* every word occurs in the source text;",
      "* every field is non-empty;",
      "* every field contains exactly one complete word;",
      "* every word is Unicode NFC-normalized;",
      "* every word is lowercase;",
      "* every word uses the same language and script as its partner;",
      "* no word appears more than once anywhere in the CSV;",
      "* no pair is duplicated in either direction;",
      "* no identity mapping exists;",
      "* no many-to-one mapping exists;",
      "* no one-to-many mapping exists;",
      "* no replacement chain exists;",
      "* no cycle longer than two exists;",
      "* all pairs are grammatically compatible;",
      "* all pairs are semantically distinct;",
      "* both directions of every pair are valid;",
      "* applying the expanded bidirectional dictionary twice restores the original words.",
      "",
      "Remove every row that fails any validation rule.",
      "",
      "## Output format",
      "",
      "Return only UTF-8 RFC 4180 CSV data.",
      "",
      "Use this exact header:",
      "",
      "source,target",
      "",
      "Write exactly one logical bidirectional pair per line.",
      "",
      "Quote fields only when required by RFC 4180.",
      "",
      "Do not output reverse rows.",
      "",
      "Do not output:",
      "",
      "* Markdown fences;",
      "* explanations;",
      "* comments;",
      "* annotations;",
      "* scores;",
      "* metadata;",
      "* rejected candidates;",
      "* blank introductory lines;",
      "* summaries;",
      "* filenames;",
      "* download links;",
      "* any text before or after the CSV.",
      "",
      "If no valid pairs can be created, return only:",
      "",
      "source,target",
      "",
      "{text}",
      "",
      "{/text}",
      "",
      "Output only the validated CSV dictionary now.",
    ].join("\n");
  }

  async function copyLlmPrompt() {
    const prompt = buildLlmPrompt();
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(prompt);
      } else {
        const fallback = document.createElement("textarea");
        fallback.value = prompt;
        fallback.setAttribute("readonly", "");
        fallback.style.position = "fixed";
        fallback.style.opacity = "0";
        document.body.append(fallback);
        fallback.select();
        const copied = document.execCommand("copy");
        fallback.remove();
        if (!copied) throw new Error("Clipboard access is unavailable");
      }
      llmPromptStatus.textContent = "Specialized LLM prompt copied.";
      console.info("[FIX] LLM prompt copied", { characters: prompt.length });
    } catch (error) {
      llmPromptStatus.textContent = "Prompt generated, but clipboard copy failed.";
      console.error("[FIX] LLM prompt copy failed", {
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  async function runAction(action) {
    setOperationProgress(true, `Running ${action}...`);
    result.textContent = "";
    try {
      if (["dict-validate", "dict-normalize"].includes(action)) {
        await saveDictionary({ silent: true });
      }
      const payload = await getJson("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ action, ...requestPayload(action) }),
      });
      actionStatus.textContent = `${action} completed`;
      result.textContent = JSON.stringify(payload, null, 2);
      if (action === "build") {
        renderArtifactSummary(payload);
        refreshShieldFontCss();
      }
      if (action === "css-build") {
        const cssPath = payload.artifacts?.css || payload.artifacts?.path;
        refreshShieldFontCss(cssPath);
      }
      await loadProcesses();
      await loadResults();
      return true;
    } catch (error) {
      actionStatus.textContent = `${action} failed`;
      showError(result, error);
      console.error("[FIX] Web action failed", {
        action,
        error: error instanceof Error ? error.message : String(error),
      });
      await loadProcesses();
      await loadResults();
      return false;
    } finally {
      setOperationProgress(false);
    }
  }

  let selectedFontRebuild = Promise.resolve();
  let selectedFontReady = false;

  function rebuildSelectedFont() {
    selectedFontRebuild = selectedFontRebuild.then(async () => {
      if (!selectedValue("#font-path")) {
        selectedFontReady = false;
        return false;
      }
      console.info("[FIX] Rebuilding selected source font and CSS");
      if (!await runAction("build")) {
        selectedFontReady = false;
        return false;
      }
      selectedFontReady = await runAction("css-build");
      return selectedFontReady;
    });
    return selectedFontRebuild;
  }

  async function compareText() {
    if (!selectedFontReady && !await rebuildSelectedFont()) {
      showError(document.querySelector("#shieldfont-text"), new Error(
        "The selected source font could not be prepared for comparison.",
      ));
      return;
    }
    const text = document.querySelector("#test-text").value;
    setOperationProgress(true, "Running test-text...");
    try {
      const payload = await getJson("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ action: "test-text", text }),
      });
      document.querySelector("#original-text").textContent = text;
      document.querySelector("#shieldfont-text").textContent = payload.shieldFont || "";
      document.querySelector("#raw-output").textContent = payload.shieldFont || "";
    } catch (error) {
      showError(document.querySelector("#shieldfont-text"), error);
      showError(document.querySelector("#raw-output"), error);
    } finally {
      setOperationProgress(false);
    }
  }

  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => runAction(button.dataset.action));
  });
  document.querySelector("#refresh-files").addEventListener("click", () => {
    const previousFontPath = selectedValue("#font-path");
    const previousDictionaryPath = selectedValue("#default-dictionary-path");
    loadFiles().then(() => {
      const currentFontPath = selectedValue("#font-path");
      let fontReady = Promise.resolve();
      if (currentFontPath !== previousFontPath) {
        selectedFontReady = false;
        compareButton.disabled = true;
        if (currentFontPath) {
          fontReady = rebuildSelectedFont().then((ready) => {
            compareButton.disabled = !ready;
          });
        }
      }
      return fontReady.then(() => {
        const currentDictionaryPath = selectedValue("#default-dictionary-path");
        if (currentDictionaryPath !== previousDictionaryPath) return loadDictionary();
        return undefined;
      });
    }).catch((error) => {
      showError(dictionaryStatus, error);
      console.error("[FIX] File refresh failed", {
        error: error instanceof Error ? error.message : String(error),
      });
    });
  });
  document.querySelector("#font-path").addEventListener("change", (event) => {
    const path = event.target.value;
    saveFontPath(path);
    refreshSourceFont(path);
    fontStatus.textContent = path ? `Selected ${path}.` : "No source font selected.";
    if (path) {
      selectedFontReady = false;
      compareButton.disabled = true;
      rebuildSelectedFont().then((ready) => {
        compareButton.disabled = !ready;
      });
    }
  });
  document.querySelector("#choose-font-file").addEventListener("click", () => {
    fontFile.click();
  });
  fontFile.addEventListener("change", () => {
    uploadFontFile().catch(() => undefined);
  });
  document.querySelector("#default-dictionary-path").addEventListener("change", (event) => {
    const path = event.target.value;
    setDefaultDictionary(path).catch((error) => {
      showError(dictionaryStatus, error);
      console.error("[FIX] Default dictionary update failed", {
        path,
        error: error instanceof Error ? error.message : String(error),
      });
    });
  });
  document.querySelector("#save-dictionary").addEventListener("click", () => {
    saveDictionary().catch((error) => showError(dictionaryStatus, error));
  });
  document.querySelector("#load-default-dictionary").addEventListener("click", () => {
    loadDefaultDictionary().catch((error) => showError(dictionaryStatus, error));
  });
  document.querySelector("#load-dictionary-file").addEventListener("click", () => {
    dictionaryFile.click();
  });
  dictionaryFile.addEventListener("change", () => {
    importDictionaryFile().catch((error) => showError(dictionaryStatus, error));
  });
  document.querySelector("#load-project-file").addEventListener("click", () => {
    projectFile.click();
  });
  document.querySelector("#load-default-project").addEventListener("click", () => {
    loadDefaultProject().catch((error) => {
      showError(projectStatus, error);
      console.error("[FIX] Default project YAML load failed", {
        error: error instanceof Error ? error.message : String(error),
      });
    });
  });
  projectFile.addEventListener("change", () => {
    importProjectFile().catch((error) => showError(projectStatus, error));
  });
  document.querySelector("#download-project-file").addEventListener("click", downloadProjectFile);
  document.querySelector("#save-project-local").addEventListener("click", saveProjectLocal);
  document.querySelector("#save-project-file").addEventListener("click", () => {
    saveProjectFile().catch((error) => {
      showError(projectStatus, error);
      console.error("[FIX] Project YAML save failed", {
        error: error instanceof Error ? error.message : String(error),
      });
    });
  });
  document.querySelector("#download-dictionary").addEventListener("click", downloadDictionary);
  document.querySelector("#refresh-processes").addEventListener("click", loadProcesses);
  document.querySelector("#refresh-results").addEventListener("click", loadResults);
  document.querySelector("#copy-llm-prompt").addEventListener("click", copyLlmPrompt);
  compareButton.disabled = true;
  compareButton.addEventListener("click", compareText);
  Object.entries(editorPreferenceInputs).forEach(([name, input]) => {
    input.addEventListener("change", () => {
      changeEditorPreference(name, input).catch(() => undefined);
    });
  });
  loadEditorPreferences();
  const projectEditorReady = createProjectEditor();
  Promise.all([
    loadStatus(),
    loadFiles().then(async () => {
      if (!selectedValue("#font-path")) {
        throw new Error("No source font is available for comparison.");
      }
      compareButton.disabled = false;
      return loadDictionary();
    }).catch((error) => {
      showError(dictionaryStatus, error);
      console.error("[FIX] Dictionary load failed", {
        error: error instanceof Error ? error.message : String(error),
      });
    }),
    projectEditorReady.then(() => loadProject()).catch((error) => {
        showError(projectStatus, error);
        console.error("[FIX] Project YAML load failed", {
          error: error instanceof Error ? error.message : String(error),
        });
      }),
    loadProcesses(),
    loadResults(),
  ]).finally(finishLoading);
})();
