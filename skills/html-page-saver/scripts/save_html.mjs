#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import process from "node:process";
import crypto from "node:crypto";

const CHALLENGE_PATTERN_SOURCE =
  "just a moment|checking your browser|performing security verification|verify you are human|enable javascript and cookies to continue|please wait|\\u8bf7\\u7a0d\\u5019|\\u5b89\\u5168\\u9a8c\\u8bc1|\\u60a8\\u662f\\u673a\\u5668\\u4eba|\\u9a8c\\u8bc1[\\s\\S]{0,40}\\u4eba\\u7c7b|\\u6b63\\u5728\\u7b49\\u5f85[\\s\\S]{0,80}\\u54cd\\u5e94";

function usage() {
  console.log(`Usage:
  node save_html.mjs <url> --output <file.html>
  node save_html.mjs --url-list <urls.txt> --output-dir <directory>

Options:
  --url-list <file>           one URL per line; blank lines and # comments ignored
  --output-dir <directory>    output directory for URL-list mode
  --output-template <name>    list filename template (default: {index}-{slug}.html)
                              placeholders: {index}, {host}, {path}, {slug}
  --fail-fast                 stop URL-list mode after the first failure
  --mode raw|rendered          raw server response or browser-rendered DOM
  --javascript keep|strip     retain or remove script elements
  --css keep|strip            retain or remove inline/external CSS elements
  --wait <milliseconds>       extra wait after rendered navigation (default: 1000)
  --cloudflare auto|off       wait for an observed browser challenge to clear
  --challenge-timeout <sec>   maximum Cloudflare challenge wait (default: 90)
  --headed                    show the browser for user interaction
  --session <name>             named Playwright CLI session
  --keep-session               leave the rendered browser session open
  --help                      show this help

Examples:
  node save_html.mjs https://example.com --output page.html
  node save_html.mjs https://example.com --output page.html --mode rendered --javascript strip --css keep
  node save_html.mjs --url-list urls.txt --output-dir snapshots --mode rendered
`);
}

function parseArgs(argv) {
  const options = {
    urlList: undefined,
    outputDir: undefined,
    outputTemplate: undefined,
    failFast: false,
    mode: "raw",
    javascript: "keep",
    css: "keep",
    wait: 1000,
    cloudflare: "off",
    challengeTimeout: 90,
    headed: false,
    keepSession: false,
    session: `html-save-${crypto.randomUUID().slice(0, 8)}`,
  };
  const positional = [];

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") {
      usage();
      process.exit(0);
    }
    if (!arg.startsWith("--")) {
      positional.push(arg);
      continue;
    }

    const [key, inlineValue] = arg.split("=", 2);
    if (key === "--headed") {
      if (inlineValue !== undefined) {
        throw new Error("--headed does not take a value");
      }
      options.headed = true;
      continue;
    }
    if (key === "--keep-session") {
      if (inlineValue !== undefined) {
        throw new Error("--keep-session does not take a value");
      }
      options.keepSession = true;
      continue;
    }
    if (key === "--fail-fast") {
      if (inlineValue !== undefined) {
        throw new Error("--fail-fast does not take a value");
      }
      options.failFast = true;
      continue;
    }
    const value = inlineValue ?? argv[++i];
    if (value === undefined) {
      throw new Error(`Missing value for ${key}`);
    }

    if (key === "--url-list") options.urlList = value;
    else if (key === "--output-dir") options.outputDir = value;
    else if (key === "--output-template") options.outputTemplate = value;
    else if (key === "--mode") options.mode = value;
    else if (key === "--javascript") options.javascript = value;
    else if (key === "--css") options.css = value;
    else if (key === "--wait") options.wait = Number(value);
    else if (key === "--cloudflare") options.cloudflare = value;
    else if (key === "--challenge-timeout") options.challengeTimeout = Number(value);
    else if (key === "--session") options.session = value;
    else if (key === "--output") options.output = value;
    else throw new Error(`Unknown option: ${key}`);
  }

  if (positional.length > 1) {
    throw new Error("Only one URL may be provided");
  }
  if (options.urlList && positional.length > 0) {
    throw new Error("Use either a positional URL or --url-list, not both");
  }
  if (options.urlList) {
    if (!options.outputDir) throw new Error("--output-dir is required with --url-list");
    if (options.output) throw new Error("--output cannot be used with --url-list");
    if (options.outputTemplate === undefined) {
      options.outputTemplate = "{index}-{slug}.html";
    }
  } else {
    options.url = positional[0];
    if (!options.url) throw new Error("A URL is required");
    if (!options.output) throw new Error("--output is required");
    if (options.outputDir) throw new Error("--output-dir requires --url-list");
    if (options.outputTemplate !== undefined) {
      throw new Error("--output-template requires --url-list");
    }
    if (options.failFast) throw new Error("--fail-fast requires --url-list");
  }
  if (!["raw", "rendered"].includes(options.mode)) {
    throw new Error("--mode must be raw or rendered");
  }
  if (!["keep", "strip"].includes(options.javascript)) {
    throw new Error("--javascript must be keep or strip");
  }
  if (!["keep", "strip"].includes(options.css)) {
    throw new Error("--css must be keep or strip");
  }
  if (!["auto", "off"].includes(options.cloudflare)) {
    throw new Error("--cloudflare must be auto or off");
  }
  if (!Number.isInteger(options.wait) || options.wait < 0) {
    throw new Error("--wait must be a non-negative integer");
  }
  if (!Number.isInteger(options.challengeTimeout) || options.challengeTimeout <= 0) {
    throw new Error("--challenge-timeout must be a positive integer");
  }
  return options;
}

function errorText(error) {
  return error instanceof Error ? error.message : String(error);
}

async function readUrlList(filename) {
  let contents;
  try {
    contents = await readFile(resolve(filename), "utf8");
  } catch (error) {
    throw new Error(`Cannot read URL list ${filename}: ${errorText(error)}`);
  }

  const urls = contents
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));

  if (urls.length === 0) {
    throw new Error(`URL list ${filename} does not contain any URLs`);
  }
  return urls;
}

function safeNamePart(value, fallback) {
  const result = String(value)
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, "-")
    .replace(/\s+/g, "-")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^\.+|\.+$/g, "")
    .slice(0, 120);
  return result || fallback;
}

function outputMetadata(urlText) {
  const parsed = new URL(urlText);
  const host = safeNamePart(parsed.host || parsed.hostname, "page");
  const path = safeNamePart(
    parsed.pathname.replace(/^\/+|\/+$/g, "").replace(/\/+/g, "-"),
    "root",
  );
  const query = parsed.search ? safeNamePart(parsed.search.slice(1), "") : "";
  const slug = safeNamePart([host, path, query].filter(Boolean).join("-"), "page");
  return { host, path, slug };
}

function renderOutputName(urlText, index, template) {
  const metadata = outputMetadata(urlText);
  const values = {
    index: String(index).padStart(3, "0"),
    ...metadata,
  };
  const placeholders = [...template.matchAll(/\{([^{}]+)\}/g)].map((match) => match[1]);
  const unknown = placeholders.find((name) => !(name in values));
  if (unknown) {
    throw new Error(
      `Unknown --output-template placeholder {${unknown}}; use {index}, {host}, {path}, or {slug}`,
    );
  }

  let filename = template.replace(/\{([^{}]+)\}/g, (_, name) => values[name]);
  filename = safeNamePart(filename, `${values.index}-page`);
  if (!/\.html?$/i.test(filename)) filename += ".html";
  return filename;
}

function uniqueFilename(filename, usedNames) {
  const extensionMatch = filename.match(/(\.[^.]+)$/);
  const extension = extensionMatch ? extensionMatch[1] : "";
  const stem = extension ? filename.slice(0, -extension.length) : filename;
  let candidate = filename;
  let suffix = 2;
  while (usedNames.has(candidate.toLowerCase())) {
    candidate = `${stem}-${suffix}${extension}`;
    suffix += 1;
  }
  usedNames.add(candidate.toLowerCase());
  return candidate;
}

function sessionNameFor(options, index) {
  if (options.mode !== "rendered" || !options.urlList) return options.session;
  return `${options.session}-${String(index).padStart(3, "0")}`;
}

function stripRequestedTags(html, options) {
  let result = html;
  if (options.javascript === "strip") {
    result = result.replace(/<script\b[^>]*>[\s\S]*?<\/script\s*>/gi, "");
    result = result.replace(/<script\b[^>]*\/?>/gi, "");
  }
  if (options.css === "strip") {
    result = result.replace(/<style\b[^>]*>[\s\S]*?<\/style\s*>/gi, "");
    result = result.replace(
      /<link\b(?=[^>]*\brel\s*=\s*["'][^"']*\bstylesheet\b[^"']*["'])[^>]*\/?>/gi,
      "",
    );
  }
  return result;
}

async function saveRaw(options) {
  const response = await fetch(options.url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`);
  }
  const source = await response.text();
  return stripRequestedTags(source, options);
}

function playwrightArgs(options, command, ...args) {
  return [
    "--yes",
    "--package",
    "@playwright/cli",
    "playwright-cli",
    "--session",
    options.session,
    command,
    ...args,
  ];
}

function shellQuoteWindows(value) {
  const text = String(value);
  if (!/[\s"&|<>^()]/.test(text)) return text;
  return `"${text.replace(/(["\\])/g, "\\$1")}"`;
}

function runPlaywright(options, command, ...args) {
  const cliArgs = playwrightArgs(options, command, ...args);
  const npxCli = resolve(
    dirname(process.execPath),
    "node_modules",
    "npm",
    "bin",
    "npx-cli.js",
  );
  const useDirectNode = existsSync(npxCli);
  const executable = useDirectNode ? process.execPath : "npx.cmd";
  const executableArgs = useDirectNode
    ? [npxCli, ...cliArgs]
    : cliArgs.map(shellQuoteWindows);

  try {
    return execFileSync(executable, executableArgs, {
      encoding: "utf8",
      maxBuffer: 50 * 1024 * 1024,
      shell: !useDirectNode,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    const detail = [error.stderr, error.stdout]
      .filter((part) => typeof part === "string" && part.trim())
      .join("\n")
      .trim();
    if (detail.includes("Error: 9001")) {
      throw new Error(
        "Cloudflare challenge did not clear before timeout; complete the authorized browser challenge or increase --challenge-timeout.",
      );
    }
    if (detail.includes("Error: 9002")) {
      throw new Error(
        "Rendered page is still a browser challenge; complete the authorized browser challenge before saving.",
      );
    }
    throw new Error(detail ? `${error.message}\n${detail}` : error.message);
  }
}

function renderExpression(options) {
  const stripJavaScript = options.javascript === "strip";
  const stripCss = options.css === "strip";
  const challengePattern = JSON.stringify(CHALLENGE_PATTERN_SOURCE);
  return `() => { const pageText = document.title + '\\n' + (document.body ? document.body.innerText : ''); if (new RegExp(${challengePattern}, 'i').test(pageText) || document.querySelectorAll('[id^=challenge], .cf-chl-widget, input[name=cf-turnstile-response]').length > 0) throw new Error(9002); if (${stripJavaScript}) { for (const node of document.querySelectorAll('script')) node.remove(); } if (${stripCss}) { for (const node of document.querySelectorAll('style')) node.remove(); for (const node of document.querySelectorAll('link[rel~=stylesheet]')) node.remove(); } const doctype = document.doctype ? '<!DOCTYPE ' + document.doctype.name + '>\\n' : ''; return doctype + document.documentElement.outerHTML; }`;
}

function challengeWaitExpression(options) {
  const timeoutMs = options.challengeTimeout * 1000;
  const challengePattern = JSON.stringify(CHALLENGE_PATTERN_SOURCE);
  return `async () => { const end = Date.now() + ${timeoutMs}; await page.waitForLoadState('domcontentloaded').catch(() => {}); const hasChallenge = async () => { try { return await page.evaluate((pattern) => { const pageText = document.title + '\\n' + (document.body ? document.body.innerText : ''); return new RegExp(pattern, 'i').test(pageText) || document.querySelectorAll('[id^=challenge], .cf-chl-widget, input[name=cf-turnstile-response]').length > 0; }, ${challengePattern}); } catch (error) { if (/execution context was destroyed|navigation/i.test(String(error && error.message))) return true; throw error; } }; while (Date.now() < end) { if (!(await hasChallenge())) { await page.waitForTimeout(500); if (!(await hasChallenge())) return; } await page.waitForTimeout(1000); } if (await hasChallenge()) throw new Error(9001); }`;
}

function parsePlaywrightRawResult(stdout) {
  const value = stdout.trim();
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`Playwright did not return HTML. Output was: ${value.slice(0, 500)}`);
  }
}

async function saveRendered(options) {
  let opened = false;
  try {
    const openArgs = [options.url];
    if (options.headed) openArgs.push("--headed");
    opened = true;
    runPlaywright(options, "open", ...openArgs);
    if (options.cloudflare === "auto") {
      runPlaywright(options, "run-code", challengeWaitExpression(options));
    }
    if (options.wait > 0) {
      runPlaywright(
        options,
        "run-code",
        `async () => { await page.waitForTimeout(${options.wait}); }`,
      );
    }
    const stdout = runPlaywright(options, "--raw", "eval", renderExpression(options));
    return parsePlaywrightRawResult(stdout);
  } finally {
    if (opened && !options.keepSession) {
      try {
        runPlaywright(options, "close");
      } catch {
        // Preserve the capture error if cleanup cannot reach the session.
      }
    }
  }
}

async function saveOne(options) {
  const html = options.mode === "raw"
    ? await saveRaw(options)
    : await saveRendered(options);
  const output = resolve(options.output);

  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, html, "utf8");
  return {
    success: true,
    url: options.url,
    mode: options.mode,
    javascript: options.javascript,
    css: options.css,
    cloudflare: options.cloudflare,
    session: options.mode === "rendered" && options.keepSession ? options.session : undefined,
    output,
    bytes: Buffer.byteLength(html, "utf8"),
  };
}

async function saveUrlList(options) {
  const urls = await readUrlList(options.urlList);
  const outputDir = resolve(options.outputDir);
  await mkdir(outputDir, { recursive: true });
  const usedNames = new Set();
  const results = [];

  for (let i = 0; i < urls.length; i += 1) {
    const url = urls[i];
    const index = i + 1;
    let output;
    try {
      output = resolve(outputDir, uniqueFilename(
        renderOutputName(url, index, options.outputTemplate),
        usedNames,
      ));
      const itemOptions = {
        ...options,
        url,
        output,
        session: sessionNameFor(options, index),
      };
      const result = await saveOne(itemOptions);
      results.push({ index, ...result });
      console.log(JSON.stringify({ index, ...result }));
    } catch (error) {
      const result = {
        success: false,
        index,
        url,
        output,
        error: errorText(error),
      };
      results.push(result);
      console.error(JSON.stringify(result));
      if (options.failFast) break;
    }
  }

  const succeeded = results.filter((result) => result.success).length;
  const failed = results.length - succeeded;
  const summary = {
    success: failed === 0 && results.length === urls.length,
    list: resolve(options.urlList),
    outputDir,
    total: urls.length,
    attempted: results.length,
    succeeded,
    failed,
    results,
  };
  console.log(JSON.stringify(summary));
  if (!summary.success) process.exitCode = 1;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.urlList) {
    await saveUrlList(options);
    return;
  }
  console.log(JSON.stringify(await saveOne(options)));
}

main().catch((error) => {
  console.error(JSON.stringify({
    success: false,
    error: error instanceof Error ? error.message : String(error),
  }));
  process.exitCode = 1;
});
