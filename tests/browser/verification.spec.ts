import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

async function getProjectContent(page: Page): Promise<string> {
  return page.locator("#project-editor").evaluate(
    (element) => element.getAttribute("data-content") || "",
  );
}

async function waitForProjectEditor(page: Page): Promise<void> {
  await expect.poll(() => page.evaluate(() => Boolean(
    (window as typeof window & { __shieldfontProjectEditor?: unknown })
      .__shieldfontProjectEditor,
  ))).toBe(true);
}

async function setProjectContent(
  page: Page,
  content: string,
): Promise<void> {
  await waitForProjectEditor(page);
  await expect(page.locator("#project-status")).toContainText(/Editing|Loaded/);
  await page.evaluate((value) => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: { setValue: (next: string) => void };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setValue(value);
  }, content);
  await expect.poll(() => getProjectContent(page)).toBe(content);
}

test("neutral text remains readable and fonts API is ready", async ({ page }) => {
  await page.setContent(`
    <main>
      <h1 id="neutral">Readable neutral text</h1>
      <p id="content" class="sf-shield">Encoded content placeholder</p>
    </main>
  `);

  await expect(page.locator("#neutral")).toBeVisible();
  await expect(page.locator("#neutral")).toHaveText("Readable neutral text");
  await expect(page.locator("#content")).toBeVisible();
  expect(await page.evaluate(() => document.fonts.status)).toBe("loaded");
});

test("browser page does not expose decoder mappings", async ({ page }) => {
  await page.setContent("<main>ShieldFont browser surface</main>");

  const exposed = await page.evaluate(() => {
    const candidate = window as typeof window & {
      shieldfont?: { mappings?: unknown };
      __SHIELDFONT_MAPPINGS__?: unknown;
    };
    return Boolean(candidate.shieldfont?.mappings || candidate.__SHIELDFONT_MAPPINGS__);
  });
  expect(exposed).toBe(false);
});

test("source font input restores selection and supports local upload", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("shieldfont.font.v1:path", ".fonts/segoeprb.ttf");
  });
  await page.goto("/");

  await expect(page.locator("#font-path")).toHaveValue(".fonts/segoeprb.ttf");
  await expect.poll(() => page.locator("#source-font-style").evaluate(
    (element) => element.textContent || "",
  )).toContain("/api/source-font?path=.fonts%2Fsegoeprb.ttf");
  await expect(page.locator("#choose-font-file")).toBeVisible();
  await page.locator("#font-path").selectOption(".fonts/segoeui.ttf");
  await expect.poll(() => page.evaluate(() =>
    localStorage.getItem("shieldfont.font.v1:path"),
  )).toBe(".fonts/segoeui.ttf");
  await expect.poll(() => page.locator("#source-font-style").evaluate(
    (element) => element.textContent || "",
  )).toContain("/api/source-font?path=.fonts%2Fsegoeui.ttf");
  await page.locator("#font-file").setInputFiles({
    name: "segoeprb.ttf",
    mimeType: "font/ttf",
    buffer: readFileSync(".fonts/segoeprb.ttf"),
  });

  await expect(page.locator("#font-path")).toHaveValue(".fonts/segoeprb.ttf");
  await expect.poll(() => page.evaluate(() =>
    localStorage.getItem("shieldfont.font.v1:path"),
  )).toBe(".fonts/segoeprb.ttf");
});

test("selected source font propagates to build and css-build actions", async ({ page }) => {
  const payloads: Record<string, Record<string, unknown>> = {};
  const actionOrder: string[] = [];
  await page.addInitScript(() => {
    localStorage.setItem("shieldfont.font.v1:path", ".fonts/segoeprb.ttf");
  });
  await page.route("**/api/action", async (route) => {
    const request = route.request();
    const payload = request.postDataJSON() as Record<string, unknown> | null;
    const action = payload?.action;
    if (action !== "build" && action !== "css-build") {
      await route.continue();
      return;
    }
    payloads[String(action)] = payload || {};
    actionOrder.push(String(action));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        action,
        process: { id: `font-${String(action)}`, status: "completed" },
        outputDir: "dist",
        artifacts: { css: "dist/shieldfont.css" },
      }),
    });
  });
  await page.goto("/");
  await expect(page.locator("#font-path")).toBeVisible();
  await expect(page.locator("#compare-text")).toBeEnabled();
  await page.locator("#compare-text").click();
  await expect.poll(() => payloads.build?.sourceFont).toBe(".fonts/segoeprb.ttf");
  await expect.poll(() => payloads["css-build"]?.sourceFont).toBe(".fonts/segoeprb.ttf");
  expect(actionOrder.slice(0, 2)).toEqual(["build", "css-build"]);
  actionOrder.length = 0;
  await page.locator("#font-path").selectOption(".fonts/segoeui.ttf");
  await expect.poll(() => payloads.build?.sourceFont).toBe(".fonts/segoeui.ttf");
  await expect.poll(() => payloads["css-build"]?.sourceFont).toBe(".fonts/segoeui.ttf");
  expect(actionOrder).toEqual(["build", "css-build"]);
});

test("dictionary editor restores client cache and supports default/import/export", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "shieldfont.dictionary.v1:dictionaries/default.csv",
      "source,target\ncached,entry\n",
    );
  });
  await page.goto("/");
  await expect(page.locator("#dictionary-editor")).toHaveValue(
    "source,target\ncached,entry\n",
  );

  await page.locator("#load-default-dictionary").click();
  await expect(page.locator("#dictionary-editor")).toHaveValue(/source,target/);
  await expect(page.locator("#dictionary-editor")).not.toHaveValue(
    "source,target\ncached,entry\n",
  );

  await page.locator("#dictionary-file").setInputFiles({
    name: "imported.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("source,target\nimported,entry\n"),
  });
  await expect(page.locator("#dictionary-editor")).toHaveValue(
    "source,target\nimported,entry\n",
  );

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download-dictionary").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("default.csv");
});

test("workflow action buttons are accepted and dictionary falls back to server", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#dictionary-editor")).toHaveValue(/source,target/);
  await expect(page.locator("#dictionary-status")).toContainText("Editing");
  await expect
    .poll(() =>
      page.evaluate(() =>
        localStorage.getItem("shieldfont.dictionary.v1:dictionaries/default.csv"),
      ),
    )
    .toMatch(/source,target/);

  const actionResponses: Array<{ action: string; status: number }> = [];
  page.on("response", (response) => {
    if (response.url().endsWith("/api/action") && response.request().method() === "POST") {
      const request = response.request().postDataJSON() as { action?: string };
      actionResponses.push({
        action: request.action || "",
        status: response.status(),
      });
    }
  });

  for (const button of await page.locator("[data-action]").all()) {
    await button.click();
  }

  await page.waitForTimeout(500);
  await expect.poll(() => actionResponses.length).toBeGreaterThan(0);
  expect(actionResponses.every((response) => response.status !== 400)).toBe(true);
});

test("dictionary uses cached content before requesting the server", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "shieldfont.dictionary.v1:dictionaries/default.csv",
      "source,target\noffline,cached\n",
    );
  });
  await page.route("**/api/action", async (route) => {
    const request = route.request().postDataJSON() as { action?: string };
    if (request.action === "dict-read") {
      await route.abort("failed");
      return;
    }
    await route.continue();
  });

  await page.goto("/");
  await expect(page.locator("#dictionary-editor")).toHaveValue(
    "source,target\noffline,cached\n",
  );
  await expect(page.locator("#dictionary-status")).toContainText("Loaded cached");
});

test("dictionary loads from the server when the cached value is empty", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("shieldfont.dictionary.v1:dictionaries/default.csv", "");
  });
  let dictionaryReads = 0;
  page.on("request", (request) => {
    if (
      request.url().endsWith("/api/action")
      && request.method() === "POST"
      && request.postDataJSON()?.action === "dict-read"
    ) {
      dictionaryReads += 1;
    }
  });

  await page.goto("/");

  await expect(page.locator("#dictionary-editor")).toHaveValue(/source,target/);
  expect(dictionaryReads).toBe(1);
  await expect(page.locator("#dictionary-status")).toContainText("Editing");
});

test("Refresh preserves current inputs and validates compact locales", async ({ page }) => {
  await page.goto("/");
  await expect.poll(() => page.locator("#font-path").inputValue()).not.toBe("");
  await expect.poll(() => page.locator("#default-dictionary-path").inputValue()).not.toBe("");
  const fontPath = await page.locator("#font-path").inputValue();
  const dictionaryPath = await page.locator("#default-dictionary-path").inputValue();
  await page.locator("#source-locale").fill("ru");
  await page.locator("#target-locale").fill("en");
  await page.locator("#dictionary-editor").fill("source,target\nkeep,value\n");

  await page.locator("#source-locale").fill("1");
  await expect(page.locator("#source-locale")).toHaveAttribute("aria-invalid", "true");
  expect(await page.locator("#source-locale").evaluate(
    (element) => (element as HTMLInputElement).validity.valid,
  )).toBe(false);
  await page.locator("#source-locale").fill("ru");
  await page.locator("#refresh-files").click();

  await expect(page.locator("#font-path")).toHaveValue(fontPath);
  await expect(page.locator("#default-dictionary-path")).toHaveValue(dictionaryPath);
  await expect(page.locator("#source-locale")).toHaveValue("ru");
  await expect(page.locator("#target-locale")).toHaveValue("en");
  await expect(page.locator("#dictionary-editor")).toHaveValue(
    "source,target\nkeep,value\n",
  );
});

test("project editor uses cache and supports YAML file import and export", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "shieldfont.project.v1:shieldfont.yml",
      "schema: shieldfont/v1\nproject:\n  id: cached\n",
    );
  });
  await page.goto("/");

  await expect.poll(() => getProjectContent(page)).toBe(
    "schema: shieldfont/v1\nproject:\n  id: cached\n",
  );
  await expect(page.locator("#project-status")).toContainText("Loaded cached");
  await expect(page.locator("#project-editor .view-line")).toHaveCount(4);
  await expect(page.locator("#project-code-editor")).toHaveCount(1);
  expect(await page.locator("#project-code-editor").evaluate((element) =>
    getComputedStyle(element).overflow,
  )).toBe("hidden");
  expect(await page.locator("#project-highlight").count()).toBe(0);

  await page.locator("#save-project-local").click();
  await expect(page.locator("#project-status")).toContainText("localStorage");

  await page.locator("#project-file").setInputFiles({
    name: "imported.yml",
    mimeType: "text/yaml",
    buffer: Buffer.from("schema: shieldfont/v1\nproject:\n  id: imported\n"),
  });
  await expect.poll(() => getProjectContent(page)).toBe(
    "schema: shieldfont/v1\nproject:\n  id: imported\n",
  );
  await expect(page.locator("#project-editor .view-line").filter({ hasText: "imported" }))
    .toHaveCount(1);

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download-project-file").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("imported.yml");
});

test("project editor hides native tooltip and reloads the server default", async ({ page }) => {
  const cachedContent = "schema: shieldfont/v1\nproject:\n  id: cached\n";
  const defaultContent = "schema: shieldfont/v1\nproject:\n  id: server-default\n";
  let defaultReads = 0;
  await page.addInitScript((content) => {
    localStorage.setItem("shieldfont.project.v1:shieldfont.yml", content);
  }, cachedContent);
  await page.route("**/api/action", async (route) => {
    const request = route.request().postDataJSON() as { action?: string; path?: string };
    if (request.action === "project-read" && request.path === "shieldfont.yml") {
      defaultReads += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ path: "shieldfont.yml", content: defaultContent }),
      });
      return;
    }
    await route.continue();
  });
  await page.goto("/");
  await expect(page.locator("#project-status")).toContainText("Loaded cached");
  await expect(page.locator("#project-editor")).not.toHaveAttribute("title");

  await page.locator("#load-default-project").click();
  await expect.poll(() => getProjectContent(page)).toBe(defaultContent);
  expect(defaultReads).toBe(1);
  await expect(page.locator("#project-status")).toContainText("Loaded default");
});

test("project editor provides YAML module editor features", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("#project-editor .line-numbers").first()).toBeVisible();
  await expect(page.locator("#project-editor .codicon[class*='folding-']").first()).toBeVisible();
  await expect(page.locator("#project-editor .view-lines")).toBeVisible();
  await expect(page.locator("#project-validation")).toContainText("YAML syntax valid");
});

test("project editor uses Monaco YAML", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("#project-editor .monaco-editor")).toBeVisible();
  await expect(page.locator("#project-editor .line-numbers").first()).toBeVisible();
  await expect(page.locator("#project-editor .codicon[class*='folding-']").first()).toBeVisible();
});

test("project editor starts as a focused editable text editor", async ({ page }) => {
  await page.goto("/");
  await waitForProjectEditor(page);

  await expect.poll(() => page.evaluate(() => ({
    activeTag: document.activeElement?.tagName,
    focused: document.querySelector("#project-editor .monaco-editor")
      ?.classList.contains("focused"),
    cursorVisible: getComputedStyle(
      document.querySelector("#project-editor .cursor") as Element,
    ).visibility,
  }))).toEqual({
    activeTag: "TEXTAREA",
    focused: true,
    cursorVisible: "visible",
  });

  const before = await getProjectContent(page);
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        getModel: () => {
          getLineCount: () => number;
          getLineMaxColumn: (lineNumber: number) => number;
        };
        setPosition: (position: { lineNumber: number; column: number }) => void;
        focus: () => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    const model = editor.getModel();
    const lineNumber = model.getLineCount();
    editor.setPosition({
      lineNumber,
      column: model.getLineMaxColumn(lineNumber),
    });
    editor.focus();
  });
  await page.keyboard.type("\n# editable");
  await expect.poll(() => getProjectContent(page)).toBe(`${before}\n# editable`);
});

test("project editor aligns gutter controls with YAML lines", async ({ page }) => {
  await page.goto("/");
  await waitForProjectEditor(page);
  await expect(page.locator("#project-status")).toContainText(/Editing|Loaded/);
  await expect(page.locator("#project-editor .codicon[class*='folding-']").first())
    .toBeVisible();

  const alignment = await page.evaluate(() => {
    const line = document.querySelector("#project-editor .view-line");
    const lineNumber = [...document.querySelectorAll("#project-editor .line-numbers")]
      .find((element) => element.textContent?.trim() === "1");
    const folding = document.querySelector("#project-editor .codicon[class*='folding-']");
    if (!line || !lineNumber || !folding) {
      throw new Error("Monaco YAML gutter controls are missing");
    }
    return {
      lineTop: line.getBoundingClientRect().top,
      lineNumberTop: lineNumber.getBoundingClientRect().top,
      foldingTop: folding.getBoundingClientRect().top,
    };
  });

  expect(Math.abs(alignment.lineNumberTop - alignment.lineTop)).toBeLessThan(1);
  expect(Math.abs(alignment.foldingTop - alignment.lineTop)).toBeLessThan(1);
});

test("project editor shows YAML breadcrumbs and clickable problems", async ({ page }) => {
  await page.goto("/");
  await setProjectContent(page, "schema: shieldfont/v1\nproject:\n  id: demo\n");
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        setPosition: (position: { lineNumber: number; column: number }) => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setPosition({ lineNumber: 3, column: 6 });
  });
  await expect(page.locator("#project-breadcrumbs")).toContainText("project");
  await expect(page.locator("#project-breadcrumbs")).toContainText("id");

  await setProjectContent(page, "project:\n  id: [broken\n");
  await expect(page.locator("#project-problems .project-problem").first()).toBeVisible();
  await page.evaluate(() => {
    const problem = document.querySelector("#project-problems .project-problem");
    if (!(problem instanceof HTMLButtonElement)) {
      throw new Error("Project problem action is missing");
    }
    problem.click();
  });
  await expect.poll(() => page.evaluate(() =>
    (window as typeof window & {
      __shieldfontProjectEditor?: {
        getPosition: () => { lineNumber: number; column: number };
      };
    }).__shieldfontProjectEditor?.getPosition().lineNumber,
  )).toBeGreaterThan(0);
});

test("Monaco resources are served locally with valid stylesheets", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/");

  await expect(page.locator("#project-editor .monaco-editor")).toBeVisible();
  expect(requests.some((url) => url.includes("/vendor/monaco-editor/"))).toBe(true);
  expect(requests.some((url) => url.endsWith("/app.bundle.js"))).toBe(true);
  expect(requests.length).toBeLessThan(200);
  expect(requests.some((url) => url.includes("cdn.jsdelivr.net") || url.includes("esm.sh")))
    .toBe(false);
  expect(requests.some((url) => url.includes("shieldfont.dev/schema/"))).toBe(false);
  const stylesheetContentType = await page.evaluate(async () => {
    const response = await fetch(
      "/vendor/monaco-editor/esm/vs/editor/browser/widget/media/editor.css",
    );
    return response.headers.get("content-type");
  });
  expect(stylesheetContentType).toContain("text/css");
  const schemaContentType = await page.evaluate(async () => {
    const response = await fetch("/api/config/schema");
    return response.headers.get("content-type");
  });
  expect(schemaContentType).toContain("application/json");
  const fontContentType = await page.evaluate(async () => {
    const response = await fetch(
      "/vendor/monaco-editor/esm/vs/base/browser/ui/codicons/codicon/codicon.ttf",
    );
    return response.headers.get("content-type");
  });
  expect(fontContentType).toContain("font/ttf");
});

test("page loading and operation progress indicators complete", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#app-loading")).toHaveAttribute("hidden", "", { timeout: 15000 });
  expect(await page.locator(".loading-spinner").evaluate((element) =>
    getComputedStyle(element).animationName,
  )).toContain("loading-spin");

  const buildActions = ["build", "verify", "font-inspect", "css-build"];
  await page.route("**/api/action", async (route) => {
    const request = route.request().postDataJSON() as { action?: string };
    if (buildActions.includes(request.action || "")) {
      await new Promise((resolve) => setTimeout(resolve, 350));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ok",
          action: request.action,
          process: { id: `progress-${request.action}`, status: "completed" },
          outputDir: "dist",
          artifacts: { css: "dist/shieldfont.css" },
        }),
      });
      return;
    }
    await route.continue();
  });
  for (const action of buildActions) {
    await page.locator(`[data-action="${action}"]`).click();
    await expect(page.locator("#operation-progress")).toBeVisible();
    await expect(page.locator("#operation-progress")).toBeHidden();
  }
});

test("Monaco Codicon font is loaded for editor controls", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#project-editor .codicon").first()).toBeVisible();

  const fontState = await page.evaluate(async () => {
    await document.fonts.ready;
    const icon = document.querySelector("#project-editor .codicon");
    if (!icon) throw new Error("Monaco Codicon element is missing");
    const computed = getComputedStyle(icon);
    return {
      family: computed.fontFamily,
      loaded: document.fonts.check('16px "codicon"'),
      fontStylesheet: Array.from(document.styleSheets).some((sheet) =>
        sheet.href?.includes("/codicon/codicon.css"),
      ),
    };
  });

  expect(fontState.family.toLowerCase()).toContain("codicon");
  expect(fontState.loaded).toBe(true);
  expect(fontState.fontStylesheet).toBe(true);
});

test("project editor reports YAML errors and folds nested sections", async ({ page }) => {
  await page.goto("/");

  await setProjectContent(page, "project:\n  id: [broken\n");
  await expect(page.locator("#project-validation")).toContainText("YAML syntax error");

  await setProjectContent(page, "project:\n  id: valid\n");
  await expect(page.locator("#project-validation")).toContainText("YAML syntax valid");

  const lineCount = await page.locator("#project-editor .view-line").count();
  const foldMarker = page.locator("#project-editor .codicon[class*='folding-']:visible").first();
  await expect(foldMarker).toBeVisible();
  await foldMarker.click();
  await expect.poll(() => page.locator("#project-editor .view-line").count())
    .toBeLessThan(lineCount);
});

test("project editor provides schema completion and hover hints", async ({ page }) => {
  await page.goto("/");
  await setProjectContent(page, "schema: shieldfont/v1\nfont:\n  \n");
  await expect.poll(() => page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        setPosition: (position: { lineNumber: number; column: number }) => void;
        trigger: (source: string, action: string, payload: unknown) => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setPosition({ lineNumber: 3, column: 3 });
    editor.trigger("browser-test", "editor.action.triggerSuggest", {});
    return Boolean(document.querySelector(".suggest-widget.visible"));
  })).toBe(true);
  await expect(page.locator(".suggest-widget")).toBeVisible();
  await expect.poll(() => page.locator(".suggest-widget").innerText())
    .toContain("family");

  await setProjectContent(page, "schema: shieldfont/v1\nfont:\n  family: ShieldFont\n");
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        setPosition: (position: { lineNumber: number; column: number }) => void;
        trigger: (source: string, action: string, payload: unknown) => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setPosition({ lineNumber: 3, column: 6 });
    editor.trigger("browser-test", "editor.action.showHover", {});
  });
  await expect(page.locator(".monaco-hover")).toContainText("Family");
  await expect(page.locator(".monaco-hover")).toContainText(
    "Affects the generated font asset family and filename.",
  );
  await expect(page.locator(".monaco-hover")).toContainText("Type: string");
  await expect(page.locator(".monaco-hover")).toContainText("Allowed values: any valid string.");
  await expect(page.locator(".monaco-hover")).not.toContainText("Source:");
});

test("project editor hover lists allowed values without schema source", async ({ page }) => {
  await page.goto("/");
  await setProjectContent(page, "schema: shieldfont/v1\nlayout:\n  boundaryMode: fire-then-revert\n");

  await setProjectContent(page, "schema: shieldfont/v1\nlayout:\n  boundaryMode: fire-then-revert\n");
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        setPosition: (position: { lineNumber: number; column: number }) => void;
        trigger: (source: string, action: string, payload: unknown) => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setPosition({ lineNumber: 3, column: 20 });
    editor.trigger("browser-test", "editor.action.showHover", {});
  });
  await expect(page.locator(".monaco-hover")).toContainText("Boundarymode");
  await expect(page.locator(".monaco-hover")).toContainText("Allowed values");
  await expect(page.locator(".monaco-hover")).toContainText("fire-then-revert");
  await expect(page.locator(".monaco-hover")).not.toContainText("Source:");
});

test("project editor describes root configuration sections", async ({ page }) => {
  await page.goto("/");
  await setProjectContent(page, "schema: shieldfont/v1\nproject:\n  id: shieldfont\n");
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        setPosition: (position: { lineNumber: number; column: number }) => void;
        trigger: (source: string, action: string, payload: unknown) => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setPosition({ lineNumber: 2, column: 2 });
    editor.trigger("browser-test", "editor.action.showHover", {});
  });
  await expect(page.locator(".monaco-hover")).toContainText(
    "Controls the project identity and output location.",
  );
  await expect(page.locator(".monaco-hover")).toContainText("Type: object.");
});

test("project editor preserves descriptions for referenced codec properties", async ({ page }) => {
  await page.goto("/");
  await setProjectContent(page, "schema: shieldfont/v1\ncodec:\n  packageName: demo-codec\n");
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        setPosition: (position: { lineNumber: number; column: number }) => void;
        trigger: (source: string, action: string, payload: unknown) => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setPosition({ lineNumber: 3, column: 8 });
    editor.trigger("browser-test", "editor.action.showHover", {});
  });
  await expect(page.locator(".monaco-hover")).toContainText(
    "Affects the package name written into generated codec metadata.",
  );
  await expect(page.locator(".monaco-hover")).not.toContainText(
    "Packagename configuration element.",
  );
});

test("project editor hover explains enumerated values", async ({ page }) => {
  await page.goto("/");
  await setProjectContent(page, "schema: shieldfont/v1\ncodec:\n  unknownScopePolicy: no-op\n");
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        setPosition: (position: { lineNumber: number; column: number }) => void;
        trigger: (source: string, action: string, payload: unknown) => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setPosition({ lineNumber: 3, column: 25 });
    editor.trigger("browser-test", "editor.action.showHover", {});
  });
  await expect(page.locator(".monaco-hover")).toContainText(
    "Leave text unchanged when the scope is unknown.",
  );
  await expect(page.locator(".monaco-hover")).toContainText(
    "Stop processing when the scope is unknown.",
  );
});

test("project editor offers typed values and guards numeric fields", async ({ page }) => {
  await page.goto("/");
  await setProjectContent(
    page,
    "schema: shieldfont/v1\ncodec:\n  unknownScopePolicy: \n",
  );
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        setPosition: (position: { lineNumber: number; column: number }) => void;
        trigger: (source: string, action: string, payload: unknown) => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setPosition({ lineNumber: 3, column: 25 });
    editor.trigger("browser-test", "editor.action.triggerSuggest", {});
  });
  await expect(page.locator(".suggest-widget")).toContainText("no-op");
  await expect(page.locator(".suggest-widget")).toContainText("error");

  await setProjectContent(
    page,
    "schema: shieldfont/v1\nproject:\n  sourceDateEpoch: 123\n",
  );
  const before = await getProjectContent(page);
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: {
        executeEdits: (
          source: string,
          edits: Array<{
            range: {
              startLineNumber: number;
              startColumn: number;
              endLineNumber: number;
              endColumn: number;
            };
            text: string;
          }>,
        ) => void;
      };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.executeEdits("browser-test", [{
      range: {
        startLineNumber: 3,
        startColumn: 22,
        endLineNumber: 3,
        endColumn: 25,
      },
      text: "abc",
    }]);
  });
  await expect.poll(() => getProjectContent(page)).toBe(before);
});

test("project editor preferences persist and control editor services", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#editor-completion")).toBeChecked();
  await expect(page.locator("#editor-hover")).toBeChecked();
  await expect(page.locator("#editor-validation")).toBeChecked();

  await page.locator("#editor-completion").uncheck();
  await page.locator("#editor-hover").uncheck();
  await page.locator("#editor-validation").uncheck();

  await expect(page.locator("#project-validation")).toContainText("disabled");
  await expect.poll(() => page.evaluate(() =>
    localStorage.getItem("shieldfont.project-editor.preferences.v1"),
  )).toBe(JSON.stringify({ completion: false, hover: false, validate: false }));

  await page.reload();
  await expect(page.locator("#editor-completion")).not.toBeChecked();
  await expect(page.locator("#editor-hover")).not.toBeChecked();
  await expect(page.locator("#editor-validation")).not.toBeChecked();
  await expect(page.locator("#project-validation")).toContainText("disabled");
});

test("project editor supports resize, scroll sync, persistence, and server round-trip", async ({ page }) => {
  await page.setViewportSize({ width: 1536, height: 1400 });
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()}`);
  });

  await page.goto("/");
  await expect(page.locator("#app-loading")).toHaveAttribute("hidden", "", {
    timeout: 15000,
  });
  await waitForProjectEditor(page);
  const editor = page.locator("#project-editor");
  const wrapper = page.locator("#project-code-editor");
  const dictionaryPanel = page.locator("#dictionary-preparation");
  const conversionPanel = page.locator("section[aria-labelledby='build-actions-heading']");
  const before = await editor.boundingBox();
  expect(before).not.toBeNull();
  expect(await wrapper.evaluate((element) => getComputedStyle(element).resize)).toBe("vertical");

  const resizeX = before!.x + before!.width - 4;
  const resizeY = before!.y + before!.height - 4;
  await page.mouse.move(resizeX, resizeY);
  await page.mouse.down();
  await page.mouse.move(resizeX, resizeY + 160);
  await page.mouse.up();

  const after = await editor.boundingBox();
  const wrapperBox = await wrapper.boundingBox();
  const dictionaryBox = await dictionaryPanel.boundingBox();
  const conversionBox = await conversionPanel.boundingBox();
  expect(after).not.toBeNull();
  expect(wrapperBox).not.toBeNull();
  expect(after!.height).toBeGreaterThan(before!.height);
  expect(wrapperBox!.height).toBeGreaterThan(before!.height);
  expect(dictionaryBox!.y).toBeGreaterThanOrEqual(wrapperBox!.y + wrapperBox!.height - 1);
  expect(conversionBox!.y).toBeGreaterThan(dictionaryBox!.y + dictionaryBox!.height - 1);
  expect(await page.evaluate(() => {
    const editor = document.querySelector("#project-editor");
    const monacoEditor = editor?.querySelector(".monaco-editor");
    if (!editor || !monacoEditor) throw new Error("Project editor module is missing");
    return {
      editorBoxSizing: getComputedStyle(editor).boxSizing,
      monacoEditorBoxSizing: getComputedStyle(monacoEditor).boxSizing,
      editorHeight: getComputedStyle(editor).height,
      monacoEditorHeight: getComputedStyle(monacoEditor).height,
      editorWidth: getComputedStyle(editor).width,
      monacoEditorWidth: getComputedStyle(monacoEditor).width,
    };
  })).toEqual({
    editorBoxSizing: "border-box",
    monacoEditorBoxSizing: "border-box",
    editorHeight: await page.locator("#project-editor").evaluate((element) =>
      getComputedStyle(element).height,
    ),
    monacoEditorHeight: await page.locator("#project-editor .monaco-editor").evaluate((element) =>
      getComputedStyle(element).height,
    ),
    editorWidth: await page.locator("#project-editor").evaluate((element) =>
      getComputedStyle(element).width,
    ),
    monacoEditorWidth: await page.locator("#project-editor .monaco-editor").evaluate((element) =>
      getComputedStyle(element).width,
    ),
  });

  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: { setScrollTop: (value: number) => void };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    editor.setScrollTop(100000);
  });
  await expect.poll(() => page.evaluate(() => {
    const editor = (window as typeof window & {
      __shieldfontProjectEditor?: { getScrollTop: () => number };
    }).__shieldfontProjectEditor;
    if (!editor) throw new Error("Project editor module is missing");
    return {
      scrollable: editor.getScrollTop() > 0,
      noTransform: getComputedStyle(document.querySelector("#project-editor")!).transform === "none",
    };
  })).toEqual({
    scrollable: true,
    noTransform: true,
  });

  const projectResponse = await page.request.post("/api/action", {
    data: { action: "project-read", path: "shieldfont.yml" },
  });
  expect(projectResponse.ok()).toBe(true);
  const projectPayload = await projectResponse.json() as { path: string; content: string };
  expect(projectPayload.path).toBe("shieldfont.yml");
  expect(projectPayload.content).toContain("schema: shieldfont/v1");

  await setProjectContent(page, `${projectPayload.content}\n# browser resize regression`);
  await page.locator("#save-project-local").click();
  await expect(page.locator("#project-status")).toContainText("localStorage");
  await page.reload();
  await expect.poll(() => getProjectContent(page)).toMatch(/browser resize regression/);

  const saveResponse = await page.request.post("/api/action", {
    data: {
      action: "project-save",
      path: projectPayload.path,
      content: projectPayload.content,
    },
  });
  expect(saveResponse.ok()).toBe(true);
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("complete GUI workflow covers every user-facing capability", async ({ page }) => {
  await page.setViewportSize({ width: 1536, height: 1400 });
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()}`);
  });

  await page.goto("/");
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: new URL(page.url()).origin,
  });

  await page.locator("#refresh-files").click();
  await expect(page.locator("#status")).not.toContainText("Error:");
  await expect(page.getByRole("button", { name: "Save parameters" })).toHaveCount(0);

  const fontOptions = page.locator("#font-path option");
  if (await fontOptions.count() > 0 && await fontOptions.first().getAttribute("value")) {
    await page.locator("#font-path").selectOption({ index: 0 });
  }
  const dictionaryOptions = page.locator("#default-dictionary-path option");
  if (await dictionaryOptions.count() > 0 && await dictionaryOptions.first().getAttribute("value")) {
    await page.locator("#default-dictionary-path").selectOption({ index: 0 });
    await expect(page.locator("#dictionary-editor")).toHaveValue(/source,target/);
  }

  await page.locator("#save-dictionary").click();
  await expect(page.locator("#dictionary-status")).toContainText("Saved");
  await page.locator("#load-default-dictionary").click();
  await expect(page.locator("#dictionary-editor")).toHaveValue(/source,target/);
  await page.locator("#dictionary-file").setInputFiles({
    name: "workflow.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("source,target\nworkflow,coverage\n"),
  });
  await expect(page.locator("#dictionary-editor")).toHaveValue(/workflow,coverage/);
  const dictionaryDownload = page.waitForEvent("download");
  await page.locator("#download-dictionary").click();
  expect((await dictionaryDownload).suggestedFilename()).toMatch(/\.csv$/);
  await page.locator("#load-default-dictionary").click();

  await page.locator("#save-project-file").click();
  await expect(page.locator("#project-status")).toContainText("Saved shieldfont.yml.");
  await page.locator("#project-file").setInputFiles({
    name: "workflow.yml",
    mimeType: "text/yaml",
    buffer: Buffer.from("schema: shieldfont/v1\nproject:\n  id: workflow\n"),
  });
  await expect.poll(() => getProjectContent(page)).toMatch(/id: workflow/);
  await page.locator("#save-project-local").click();
  await expect(page.locator("#project-status")).toContainText("localStorage");
  const projectDownload = page.waitForEvent("download");
  await page.locator("#download-project-file").click();
  expect((await projectDownload).suggestedFilename()).toBe("workflow.yml");
  await page.locator("#load-project-file").click();
  await expect(page.locator("#project-file")).toHaveAttribute("accept", ".yml,.yaml,text/yaml,text/x-yaml");

  await page.locator("#copy-llm-prompt").click();
  await expect(page.locator("#llm-prompt-status")).toContainText("copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    "source,target",
  );

  await page.locator("#compare-text").click();
  await expect(page.locator("#original-text")).not.toHaveText("");
  await expect(page.locator("#shieldfont-text")).not.toHaveText("");
  await expect(page.locator("#raw-output")).not.toHaveText("");

  await page.locator("#process-results").evaluate((element) => {
    (element as HTMLDetailsElement).open = true;
  });
  await page.locator("#refresh-processes").click();
  await page.locator("#refresh-results").click();
  await expect(page.locator("#processes")).not.toContainText("Error:");
  await expect(page.locator("#results")).not.toContainText("Error:");

  for (const action of [
    "dict-validate",
    "dict-normalize",
    "font-inspect",
    "css-build",
    "build",
    "verify",
  ]) {
    await page.locator(`[data-action="${action}"]`).click();
    await expect(page.locator("#action-status")).toHaveText(`${action} completed`, {
      timeout: 120_000,
    });
    await expect(page.locator("#result")).not.toContainText("Error:");
  }
  await expect(page.locator("#artifact-summary")).not.toHaveText("Build output paths will appear here.");

  await expect.poll(() => page.locator("#processes").textContent()).toContain("completed");
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("dictionary loading is independent from file inventory failures", async ({ page }) => {
  await page.route("**/api/files**", (route) => route.abort("failed"));
  await page.goto("/");
  await expect(page.locator("#dictionary-editor")).toHaveValue(/source,target/);
  await expect(page.locator("#dictionary-status")).not.toContainText("Error:");
});

test("web GUI loads status and scoped utilities", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "ShieldFont Toolchain" })).toBeVisible();
  await expect(page.locator("#status")).toContainText("Ready.");
  await expect(page.getByRole("button", { name: "Build", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Verify" })).toBeVisible();
  await expect(page.locator("#font-path")).toBeVisible();
  await expect(page.locator("#default-dictionary-path")).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh files" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save parameters" })).toHaveCount(0);
  await expect(page.locator("#css-options")).toBeVisible();
  expect(await page.locator("#css-options").getAttribute("open")).toBeNull();
  await page.locator("#css-options summary").click();
  await expect(page.locator("#css-output")).toBeVisible();
  await expect(page.locator("#config-result")).toHaveCount(0);
  await expect(page.locator("#css-asset-base")).toHaveValue("./fonts/");
  await expect(page.locator("#css-font-display")).toHaveValue("block");
  await expect(page.locator("#css-embed-font")).not.toBeChecked();
  const checkboxPositions = await page.evaluate(() => {
    const getLabelBox = (id: string) => {
      const input = document.getElementById(id);
      const label = input?.closest("label");
      const box = label?.getBoundingClientRect();
      return box ? { x: box.x, y: box.y } : null;
    };
    return {
      ttfFallback: getLabelBox("css-ttf-fallback"),
      embedFont: getLabelBox("css-embed-font"),
    };
  });
  expect(checkboxPositions.ttfFallback).not.toBeNull();
  expect(checkboxPositions.embedFont).not.toBeNull();
  expect(Math.abs(
    checkboxPositions.ttfFallback!.x - checkboxPositions.embedFont!.x,
  )).toBeLessThan(1);
  expect(checkboxPositions.embedFont!.y).toBeGreaterThan(
    checkboxPositions.ttfFallback!.y,
  );
  await expect(page.locator("#dictionary-preparation")).toBeVisible();
  await expect(page.locator("#project-editor-panel")).toBeVisible();
  await expect.poll(() => getProjectContent(page)).toMatch(/schema: shieldfont\/v1/);
  await expect(page.locator("#project-code-editor")).toBeVisible();
  await expect(page.locator("#project-editor .line-numbers").first()).toBeVisible();
  await expect(page.locator("#project-editor .codicon[class*='folding-']").first()).toBeVisible();
  await expect(page.locator("#load-project-file")).toHaveAttribute("title", /Load a project/);
  await expect(page.locator("#download-project-file")).toHaveAttribute("title", /Save the current project/);
  await expect(page.locator("#save-project-local")).toHaveAttribute("title", /localStorage/);
  await expect(page.locator("#dictionary-editor")).toBeVisible();
  await expect(page.locator("#dictionary-preparation")).toContainText(
    "UTF-8 CSV with the header source,target",
  );
  await expect(page.locator("#dictionary-editor")).toHaveValue(/source,target/);
  await expect(page.locator("#save-dictionary")).toBeVisible();
  await expect(page.locator("#load-default-dictionary")).toBeVisible();
  await expect(page.locator("#load-dictionary-file")).toBeVisible();
  await expect(page.locator("#download-dictionary")).toBeVisible();
  await expect(page.locator("#dictionary-file")).toHaveAttribute("accept", ".csv,text/csv");
  await expect(page.locator('[data-action="llm-extract"]')).toHaveCount(0);
  await expect(page.locator("#llm-provider")).toHaveCount(0);
  await expect(page.locator("#llm-model")).toHaveCount(0);
  await expect(page.locator("#llm-endpoint")).toHaveCount(0);
  await expect(page.locator("#save-llm-settings")).toHaveCount(0);
  await expect(page.locator("#llm-prompt-text")).toHaveCount(0);
  await expect(page.locator("#copy-llm-prompt")).toBeVisible();
  await expect(page.locator("#copy-llm-prompt")).toHaveAttribute(
    "title",
    /external chat/,
  );
  await expect(page.locator("body")).not.toContainText(
    "Copy the specialized LLM prompt into an external chat and save its CSV response in the editor above.",
  );
  await page.locator("#copy-llm-prompt").click();
  await expect(page.locator("#llm-settings")).toHaveCount(0);
  await expect(page.locator("#llm-prompt-output")).toHaveCount(0);
  await expect(page.locator("#llm-prompt-status")).toContainText(/[Pp]rompt/);
  await expect(page.locator("#shieldfont-css")).toHaveAttribute(
    "href",
    "/api/shieldfont.css",
  );
  await expect(page.locator("#original-text")).toHaveClass(/comparison-original/);
  await expect(page.locator("#shieldfont-text")).toHaveClass(/comparison-shield/);
  await expect(page.locator("#raw-output")).toHaveClass(/comparison-original/);
  await expect(page.locator("#raw-output")).toHaveText("");
  await page.locator("#compare-text").click();
  await expect(page.locator("#raw-output")).toHaveText(/Я помню тягостная вечность:/);
  const comparisonFonts = await page.evaluate(() => {
    const original = document.querySelector("#original-text");
    const raw = document.querySelector("#raw-output");
    if (!original || !raw) throw new Error("Comparison elements are missing");
    return {
      original: getComputedStyle(original).fontFamily,
      raw: getComputedStyle(raw).fontFamily,
    };
  });
  expect(comparisonFonts.original).toBe(comparisonFonts.raw);
  expect(comparisonFonts.raw).toContain("ShieldFont Original");
  await expect(page.locator("#corpus-path")).toHaveCount(0);
  await expect(page.locator("#test-text")).toBeVisible();
  await expect(page.locator("#test-text")).toHaveValue(/Я помню чудное мгновенье:/);
  const defaultLocale = await page.evaluate(
    () => (navigator.languages?.[0] || navigator.language || document.documentElement.lang || "en")
      .split("-")[0]
      .toLowerCase(),
  );
  await expect(page.locator("#source-locale")).toHaveValue(defaultLocale);
  await expect(page.locator("#target-locale")).toHaveValue(defaultLocale  );
  expect(await page.locator("#process-results").getAttribute("open")).toBeNull();
});

test("inputs form keeps controls compact and on one row", async ({ page }) => {
  await page.setViewportSize({ width: 1495, height: 900 });
  await page.goto("/");
  await expect(page.locator("#status")).toContainText("Ready.");

  const layout = await page.evaluate(() => {
    const elements = [
      "#font-path",
      "#choose-font-file",
      "#default-dictionary-path",
      "#refresh-files",
      "#output-format",
      "#source-locale",
      "#target-locale",
    ].map((selector) => {
      const element = document.querySelector(selector);
      if (!element) throw new Error(`Missing ${selector}`);
      const box = element.getBoundingClientRect();
      return {
        selector,
        top: box.top,
        height: box.height,
        width: box.width,
      };
    });
    const grid = document.querySelector(".field-grid");
    if (!grid) throw new Error("Missing input field grid");
    const gridStyle = getComputedStyle(grid);
    const itemBoxes = [
      document.querySelector(".font-field"),
      document.querySelector(".font-field + .field-action"),
      document.querySelector("#default-dictionary-path")?.closest("label"),
      document.querySelector("#default-dictionary-path")?.closest("label")?.nextElementSibling,
      document.querySelector("#output-format")?.closest("label"),
      document.querySelector("#source-locale")?.closest("label"),
      document.querySelector("#target-locale")?.closest("label"),
    ].map((element) => {
      if (!element) throw new Error("Missing input grid item");
      const box = element.getBoundingClientRect();
      return { left: box.left, right: box.right, top: box.top };
    });
    return {
      elements,
      gridGap: Number.parseFloat(gridStyle.columnGap),
      itemBoxes,
    };
  });
  const font = layout.itemBoxes[0];
  const choose = layout.itemBoxes[1];
  const dictionary = layout.itemBoxes[2];
  const refresh = layout.itemBoxes[3];
  const output = layout.itemBoxes[4];
  const source = layout.itemBoxes[5];
  const target = layout.itemBoxes[6];
  for (const [left, right] of [
    [font, choose],
    [choose, dictionary],
    [dictionary, refresh],
    [refresh, output],
    [output, source],
    [source, target],
  ]) {
    expect(left).toBeDefined();
    expect(right).toBeDefined();
    expect(right!.left - left!.right).toBeCloseTo(layout.gridGap, 1);
  }
  expect(Math.abs(layout.elements.find((item) => item.selector === "#font-path")!.top
    - layout.elements.find((item) => item.selector === "#choose-font-file")!.top))
    .toBeLessThan(1);
  expect(Math.abs(layout.elements.find((item) => item.selector === "#default-dictionary-path")!.top
    - layout.elements.find((item) => item.selector === "#refresh-files")!.top))
    .toBeLessThan(1);

  expect(layout.elements.find((item) => item.selector === "#default-dictionary-path")!.height)
    .toBeLessThan(80);
  expect(layout.elements.find((item) => item.selector === "#output-format")!.height)
    .toBeLessThan(80);
  expect(layout.elements.find((item) => item.selector === "#output-format")!.width)
    .toBeLessThan(120);
  const localeTops = layout.elements
    .filter((item) => item.selector.endsWith("locale"))
    .map((item) => item.top);
  expect(Math.abs(localeTops[0] - localeTops[1])).toBeLessThan(1);
});
