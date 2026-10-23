#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, extname, resolve } from "node:path";
import process from "node:process";
import crypto from "node:crypto";

const CHALLENGE_PATTERN_SOURCE =
  "just a moment|checking your browser|performing security verification|verify you are human|enable javascript and cookies to continue|please wait|\\u8bf7\\u7a0d\\u5019|\\u5b89\\u5168\\u9a8c\\u8bc1|\\u60a8\\u662f\\u673a\\u5668\\u4eba|\\u9a8c\\u8bc1[\\s\\S]{0,40}\\u4eba\\u7c7b|\\u6b63\\u5728\\u7b49\\u5f85[\\s\\S]{0,80}\\u54cd\\u5e94";

const KNOWN_EXTENSIONS = new Set([
  "7z",
  "cif",
  "csv",
  "doc",
  "docx",
  "gz",
  "jpeg",
  "jpg",
  "json",
  "mol",
  "pdb",
  "pdf",
  "png",
  "rar",
  "rtf",
  "sdf",
  "svg",
  "tar",
  "tgz",
  "tsv",
  "txt",
  "xls",
  "xlsx",
  "xml",
  "zip",
]);

function usage() {
  console.log(`Usage:
  node save_pdf_si.mjs <url> --mode pdf|si|discover-si --output <file>
  node save_pdf_si.mjs --url-list <urls.txt> --mode pdf|si|discover-si --output-dir <directory>

Options:
  --mode pdf|si|discover-si  direct article PDF, SI file, or article-page SI discovery (default: pdf)
  --url-list <file>          one direct file URL per line; blank lines and # comments ignored
  --output <file>            output file for single-URL mode
  --output-dir <directory>   output directory for URL-list mode
  --output-template <name>   list filename template (default: {index}-{slug}.{ext})
                             placeholders: {index}, {host}, {path}, {slug}, {ext}
  --fail-fast                stop URL-list mode after the first failure
  --discover-only            with --mode discover-si, only write discovered links
  --max-links <number>       maximum SI links to inspect in discover-si mode (default: 20)
  --wait <milliseconds>      extra browser wait after navigation (default: 3000)
  --cloudflare auto|off      wait for an observed browser challenge to clear
  --challenge-timeout <sec> maximum browser challenge/login wait (default: 120)
  --headed                   show the browser for user interaction
  --browser <name>           chrome, msedge, firefox, or webkit (default: chrome)
  --session <name>           named Playwright CLI session
  --keep-session             leave the browser session open after capture
  --help                     show this help

Examples:
  node save_pdf_si.mjs https://example.com/article.pdf --mode pdf --output article.pdf
  node save_pdf_si.mjs https://example.com/si.pdf --mode si --output article-si.pdf --headed --cloudflare auto
  node save_pdf_si.mjs https://example.com/article --mode discover-si --output-dir article-si
  node save_pdf_si.mjs --url-list urls.txt --mode si --output-dir supplements
`);
}

function parseArgs(argv) {
  const options = {
    urlList: undefined,
    output: undefined,
    outputDir: undefined,
    outputTemplate: undefined,
    failFast: false,
    mode: "pdf",
    discoverOnly: false,
    maxLinks: 20,
    wait: 3000,
    cloudflare: "off",
    challengeTimeout: 120,
    headed: false,
    browser: "chrome",
    keepSession: false,
    session: `document-save-${crypto.randomUUID().slice(0, 8)}`,
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
    if (["--headed", "--keep-session", "--fail-fast", "--discover-only"].includes(key)) {
      if (inlineValue !== undefined) {
        throw new Error(`${key} does not take a value`);
      }
      if (key === "--headed") options.headed = true;
      if (key === "--keep-session") options.keepSession = true;
      if (key === "--fail-fast") options.failFast = true;
      if (key === "--discover-only") options.discoverOnly = true;
      continue;
    }

    const value = inlineValue ?? argv[++i];
    if (value === undefined) {
      throw new Error(`Missing value for ${key}`);
    }

    if (key === "--mode") options.mode = value;
    else if (key === "--url-list") options.urlList = value;
    else if (key === "--output") options.output = value;
    else if (key === "--output-dir") options.outputDir = value;
    else if (key === "--output-template") options.outputTemplate = value;
    else if (key === "--wait") options.wait = Number(value);
    else if (key === "--cloudflare") options.cloudflare = value;
    else if (key === "--challenge-timeout") options.challengeTimeout = Number(value);
    else if (key === "--max-links") options.maxLinks = Number(value);
    else if (key === "--browser") options.browser = value;
    else if (key === "--session") options.session = value;
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
    if (options.outputTemplate === undefined && options.mode !== "discover-si") {
      options.outputTemplate = "{index}-{slug}.{ext}";
    }
  } else {
    options.url = positional[0];
    if (!options.url) throw new Error("A URL is required");
    if (options.mode !== "discover-si" && !options.output) throw new Error("--output is required");
    if (options.mode === "discover-si" && options.output) {
      throw new Error("--output cannot be used with --mode discover-si; use --output-dir");
    }
    if (options.outputDir && options.mode !== "discover-si") {
      throw new Error("--output-dir requires --url-list");
    }
    if (options.outputTemplate !== undefined) {
      throw new Error("--output-template requires --url-list");
    }
    if (options.failFast) throw new Error("--fail-fast requires --url-list");
  }
  if (!["pdf", "si", "discover-si"].includes(options.mode)) {
    throw new Error("--mode must be pdf, si, or discover-si");
  }
  if (options.mode === "discover-si" && !options.outputDir) {
    throw new Error("--output-dir is required with --mode discover-si");
  }
  if (options.mode === "discover-si" && options.outputTemplate !== undefined) {
    throw new Error("--output-template is not supported with --mode discover-si");
  }
  if (options.discoverOnly && options.mode !== "discover-si") {
    throw new Error("--discover-only requires --mode discover-si");
  }
  if (!Number.isInteger(options.maxLinks) || options.maxLinks <= 0) {
    throw new Error("--max-links must be a positive integer");
  }
  if (!["auto", "off"].includes(options.cloudflare)) {
    throw new Error("--cloudflare must be auto or off");
  }
  if (!["chrome", "msedge", "firefox", "webkit"].includes(options.browser)) {
    throw new Error("--browser must be chrome, msedge, firefox, or webkit");
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
  const host = safeNamePart(parsed.host || parsed.hostname, "file");
  const rawPath = parsed.pathname
    .split("/")
    .filter(Boolean)
    .join("-")
    .replace(/\.(?:7z|cif|csv|docx?|gz|jpeg|jpg|json|mol|pdb|pdf|png|rar|rtf|sdf|svg|tar|tgz|tsv|txt|xls|xlsx|xml|zip)$/i, "");
  const path = safeNamePart(
    rawPath,
    "root",
  );
  const query = parsed.search ? safeNamePart(parsed.search.slice(1), "") : "";
  const slug = safeNamePart([host, path, query].filter(Boolean).join("-"), "file");
  return { host, path, slug };
}

function extensionHintFromUrl(urlText, mode) {
  if (mode === "pdf") return "pdf";
  try {
    const pathname = new URL(urlText).pathname.toLowerCase();
    const filename = pathname.split("/").pop() || "";
    const match = filename.match(/\.([a-z0-9]{1,8})$/);
    if (match && KNOWN_EXTENSIONS.has(match[1])) return match[1];
  } catch {
    // URL validation is performed by the network operation.
  }
  return "bin";
}

function renderOutputName(urlText, index, template, mode) {
  const metadata = outputMetadata(urlText);
  const values = {
    index: String(index).padStart(3, "0"),
    ext: extensionHintFromUrl(urlText, mode),
    ...metadata,
  };
  const placeholders = [...template.matchAll(/\{([^{}]+)\}/g)].map((match) => match[1]);
  const unknown = placeholders.find((name) => !(name in values));
  if (unknown) {
    throw new Error(
      `Unknown --output-template placeholder {${unknown}}; use {index}, {host}, {path}, {slug}, or {ext}`,
    );
  }

  let filename = template.replace(/\{([^{}]+)\}/g, (_, name) => values[name]);
  filename = safeNamePart(filename, `${values.index}-file`);
  if (!extname(filename)) filename += `.${values.ext}`;
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
  if (!options.urlList) return options.session;
  return `${options.session}-${String(index).padStart(3, "0")}`;
}

function normalizeContentType(value) {
  return String(value || "").split(";", 1)[0].trim().toLowerCase();
}

function startsWithBytes(buffer, text) {
  return buffer.subarray(0, Buffer.byteLength(text)).equals(Buffer.from(text));
}

function isPdf(buffer) {
  return startsWithBytes(buffer, "%PDF-");
}

function isZip(buffer) {
  return (
    buffer.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04])) ||
    buffer.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x05, 0x06])) ||
    buffer.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x07, 0x08]))
  );
}

function isOleCompoundFile(buffer) {
  return buffer.subarray(0, 8).equals(Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]));
}

function textSample(buffer) {
  return buffer
    .subarray(0, 8192)
    .toString("utf8")
    .replace(/^\uFEFF/, "")
    .replace(/\u0000/g, "")
    .trimStart();
}

function looksLikeHtml(buffer, contentType) {
  if (["text/html", "application/xhtml+xml"].includes(contentType)) return true;
  const sample = textSample(buffer).toLowerCase();
  return /^(?:<!doctype\s+html|<html\b|<head\b|<body\b|<script\b)/i.test(sample);
}

function looksLikeChallenge(buffer) {
  const sample = textSample(buffer);
  return new RegExp(CHALLENGE_PATTERN_SOURCE, "i").test(sample);
}

function validateResource(buffer, contentType, urlText, mode) {
  if (!buffer || buffer.length === 0) {
    throw new Error("The downloaded response is empty");
  }
  if (looksLikeChallenge(buffer) && !isPdf(buffer) && !isZip(buffer) && !isOleCompoundFile(buffer)) {
    throw new Error("The response is a browser challenge or login page, not the requested file");
  }
  if (looksLikeHtml(buffer, contentType)) {
    throw new Error("The response is HTML rather than the requested file");
  }
  if (mode === "pdf" && !isPdf(buffer)) {
    const type = contentType || "unknown content type";
    throw new Error(`PDF mode requires a valid %PDF- file; received ${type} from ${urlText}`);
  }
}

function extensionForResource(resource, mode) {
  if (mode === "pdf" || isPdf(resource.buffer)) return "pdf";
  const contentType = normalizeContentType(resource.contentType);
  const typeExtensions = new Map([
    ["application/pdf", "pdf"],
    ["application/zip", "zip"],
    ["application/x-7z-compressed", "7z"],
    ["application/x-rar-compressed", "rar"],
    ["application/rtf", "rtf"],
    ["application/msword", "doc"],
    ["application/vnd.ms-excel", "xls"],
    ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"],
    ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"],
    ["text/csv", "csv"],
    ["text/plain", "txt"],
    ["application/json", "json"],
    ["application/xml", "xml"],
    ["text/xml", "xml"],
  ]);
  if (typeExtensions.has(contentType)) return typeExtensions.get(contentType);
  if (isZip(resource.buffer)) return "zip";
  if (isOleCompoundFile(resource.buffer)) return "bin";
  if (textSample(resource.buffer).startsWith("{\\rtf")) return "rtf";
  return extensionHintFromUrl(resource.finalUrl || resource.url || "", "si");
}

async function fetchResource(urlText, mode) {
  let response;
  try {
    response = await fetch(urlText, { redirect: "follow" });
  } catch (error) {
    throw new Error(`Direct request failed: ${errorText(error)}`);
  }
  const buffer = Buffer.from(await response.arrayBuffer());
  const contentType = normalizeContentType(response.headers.get("content-type"));
  if (!response.ok) {
    throw new Error(`Direct request returned HTTP ${response.status} ${response.statusText}`);
  }
  validateResource(buffer, contentType, response.url || urlText, mode);
  return {
    buffer,
    contentType,
    finalUrl: response.url || urlText,
    source: "direct",
  };
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
      maxBuffer: 200 * 1024 * 1024,
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
        "Browser challenge did not clear before timeout; complete the authorized challenge or increase --challenge-timeout.",
      );
    }
    if (detail.includes("Error: 9002")) {
      throw new Error(
        "The browser is still showing a challenge page; complete the authorized challenge before downloading.",
      );
    }
    throw new Error(detail ? `${error.message}\n${detail}` : error.message);
  }
}

function challengeWaitExpression(options) {
  const timeoutMs = options.challengeTimeout * 1000;
  const challengePattern = JSON.stringify(CHALLENGE_PATTERN_SOURCE);
  return `async () => { const end = Date.now() + ${timeoutMs}; await page.waitForLoadState('domcontentloaded').catch(() => {}); const hasChallenge = async () => { try { return await page.evaluate((pattern) => { const pageText = document.title + '\\n' + (document.body ? document.body.innerText : ''); return new RegExp(pattern, 'i').test(pageText) || document.querySelectorAll('[id^=challenge], .cf-chl-widget, input[name=cf-turnstile-response]').length > 0; }, ${challengePattern}); } catch (error) { if (/execution context was destroyed|navigation/i.test(String(error && error.message))) return true; throw error; } }; while (Date.now() < end) { if (!(await hasChallenge())) { await page.waitForTimeout(500); if (!(await hasChallenge())) return; } await page.waitForTimeout(1000); } if (await hasChallenge()) throw new Error(9001); }`;
}

function parseJsonOutput(stdout, label) {
  try {
    return JSON.parse(stdout.trim());
  } catch {
    throw new Error(`Playwright did not return JSON for ${label}: ${stdout.trim().slice(0, 500)}`);
  }
}

function parseHeaders(stdout) {
  const headers = new Map();
  for (const line of stdout.split(/\r?\n/)) {
    const separator = line.indexOf(":");
    if (separator <= 0) continue;
    headers.set(line.slice(0, separator).trim().toLowerCase(), line.slice(separator + 1).trim());
  }
  return headers;
}

function parseRequestListing(stdout) {
  const payload = parseJsonOutput(stdout, "requests");
  const listing = typeof payload.result === "string" ? payload.result : "";
  const requests = [];
  for (const line of listing.split(/\r?\n/)) {
    const match = line.match(/^(\d+)\.\s+\[([^\]]+)\]\s+(.+?)\s+=>\s+\[(\d{3})\]/);
    if (!match) continue;
    requests.push({
      index: Number(match[1]),
      method: match[2],
      url: match[3].trim(),
      status: Number(match[4]),
    });
  }
  return requests;
}

function stripHash(urlText) {
  try {
    const parsed = new URL(urlText);
    parsed.hash = "";
    return parsed.toString();
  } catch {
    return urlText;
  }
}

function candidateScore(request, requestedUrl, mode) {
  let score = 0;
  const requested = stripHash(requestedUrl);
  const candidate = stripHash(request.url);
  if (candidate === requested) score += 1000;
  try {
    const parsed = new URL(request.url);
    const path = parsed.pathname.toLowerCase();
    if (parsed.protocol === "http:" || parsed.protocol === "https:") score += 20;
    if (/\.(?:pdf|docx?|zip|cif|rtf|xlsx?|csv|txt)(?:$|[?#])/i.test(path)) score += 100;
    if (/supp|supplement|support|download|full.?text|article/i.test(path)) score += 40;
    if (mode === "pdf" && /pdf/i.test(path)) score += 60;
  } catch {
    // Invalid request URLs are ignored later.
  }
  return score - request.index / 10000;
}

function isBrowserResourceUrl(urlText) {
  return /^(?:https?:|blob:)/i.test(urlText);
}

function likelyDocumentContentType(contentType, mode, urlText) {
  if (!contentType) return true;
  if (["text/html", "application/xhtml+xml", "text/css", "text/javascript", "application/javascript"].includes(contentType)) {
    return false;
  }
  if (mode === "pdf") {
    return contentType === "application/pdf" || /\.pdf(?:$|[?#])/i.test(urlText);
  }
  return !/^(?:font|image\/svg\+xml)/i.test(contentType);
}

async function readBrowserResponseBody(options, requestIndex) {
  const stdout = runPlaywright(options, "--raw", "response-body", String(requestIndex));
  const trimmed = stdout.trim();
  const possiblePaths = [
    trimmed,
    ...trimmed.split(/\r?\n/).reverse(),
  ];
  for (const possiblePath of possiblePaths) {
    const cleaned = possiblePath.replace(/^['"]|['"]$/g, "");
    if (!cleaned || !existsSync(resolve(cleaned))) continue;
    return readFile(resolve(cleaned));
  }
  return Buffer.from(stdout, "utf8");
}

function browserFetchExpression(urlText, referer) {
  const serializedUrl = JSON.stringify(urlText);
  const requestOptions = referer
    ? `, { headers: { referer: ${JSON.stringify(referer)} } }`
    : "";
  return `async () => { const response = await page.request.get(${serializedUrl}${requestOptions}); const bytes = new Uint8Array(await response.body()); const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'; let base64 = ''; for (let index = 0; index < bytes.length; index += 3) { const first = bytes[index]; const second = index + 1 < bytes.length ? bytes[index + 1] : 0; const third = index + 2 < bytes.length ? bytes[index + 2] : 0; const value = (first << 16) | (second << 8) | third; base64 += alphabet[(value >> 18) & 63] + alphabet[(value >> 12) & 63] + (index + 1 < bytes.length ? alphabet[(value >> 6) & 63] : '=') + (index + 2 < bytes.length ? alphabet[value & 63] : '='); } return { status: response.status(), statusText: response.statusText(), contentType: response.headers()['content-type'] || '', finalUrl: response.url(), base64 }; }`;
}

async function fetchBrowserResponse(options, urlText, referer) {
  const stdout = runPlaywright(options, "--raw", "run-code", browserFetchExpression(urlText, referer));
  const payload = parseJsonOutput(stdout, "browser response");
  if (!payload || payload.status < 200 || payload.status >= 300) {
    throw new Error(`Browser fetch returned HTTP ${payload?.status || "unknown"}`);
  }
  const buffer = Buffer.from(payload.base64 || "", "base64");
  return {
    buffer,
    contentType: normalizeContentType(payload.contentType),
    finalUrl: payload.finalUrl || urlText,
  };
}

function discoveryExpression() {
  return `() => { const nodes = [...document.querySelectorAll('a[href], area[href], [role=link], [data-href], [data-url], [data-download-url], [data-file-url], [data-resource-url], [data-attachment-url], [data-download], [data-file]')]; const prefilter = /(?:supporting\\s+(?:information|material|materials|data|file|files|document|documents|dataset|datasets|appendix|appendices)|supplement(?:ary|al)?\\s+(?:information|material|materials|data|file|files|document|documents|dataset|datasets|appendix|appendices)|electronic\\s+(?:supporting|supplementary)|additional\\s+(?:information|material|materials|data|file|files|document|documents|dataset|datasets|appendix)|associated\\s+(?:content|data|file|files|dataset|datasets)|data\\s+(?:supplement|set|dataset|file)|online[-\\s]+(?:supplement|appendix|material)|extended\\s+data|extra\\s+material|appendix|\\b(?:s\\.?\\s*i\\.?|e\\.?\\s*s\\.?\\s*i\\.?|e\\.?\\s*s\\.?\\s*m)\\b|supp\\.?\\s*(?:info(?:rmation)?|mat(?:erial)?|data|files?)|suppdata|\\u8865\\u5145|\\u652f\\u6301|\\u9644\\u52a0|\\u7535\\u5b50\\u8865\\u5145|\\u5728\\u7ebf\\u8865\\u5145|\\u6570\\u636e\\u96c6|\\.pdf(?:$|[?#])|download)/i; const urlFromNode = (node) => { const rawValues = [node.getAttribute('href'), node.getAttribute('data-href'), node.getAttribute('data-url'), node.getAttribute('data-download-url'), node.getAttribute('data-file-url'), node.getAttribute('data-resource-url'), node.getAttribute('data-attachment-url'), node.getAttribute('data-download'), node.getAttribute('data-file')]; for (const raw of rawValues) { if (!raw || /^(?:#|javascript:|mailto:|tel:|data:)/i.test(raw)) continue; try { return new URL(raw, location.href).href; } catch {} } const onclick = node.getAttribute('onclick') || ''; const match = onclick.match(/['"]((?:https?:|\\/|\\.\\.?\\/)[^'"]+)['"]/i); if (!match) return null; try { return new URL(match[1], location.href).href; } catch {} return null; }; return nodes.map((node) => { const href = urlFromNode(node); if (!href) return null; const text = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim(); const ariaLabel = node.getAttribute('aria-label') || ''; const title = node.getAttribute('title') || ''; const download = node.getAttribute('download') || ''; const rel = node.getAttribute('rel') || ''; const id = node.id || ''; const className = typeof node.className === 'string' ? node.className : ''; const parentText = node.parentElement ? (node.parentElement.innerText || '').replace(/\\s+/g, ' ').trim() : ''; const context = parentText.length <= 600 ? parentText : ''; const evidence = [text, ariaLabel, title, download, rel, id, className, context, href].join(' '); if (!prefilter.test(evidence)) return null; return { href, text, ariaLabel, title, download, rel, id, className, context }; }).filter(Boolean); }`;
}

const SI_LABEL_PATTERN = new RegExp(
  "supporting\\s+(?:information|material|materials|data|file|files|document|documents|dataset|datasets|appendix|appendices)|supplementary\\s+(?:information|material|materials|data|file|files|document|documents|dataset|datasets|appendix|appendices)|supplemental\\s+(?:information|material|materials|data|file|files|document|documents|dataset|datasets|appendix|appendices)|electronic\\s+(?:supporting|supplementary)|additional\\s+(?:information|material|materials|data|file|files|document|documents|dataset|datasets|appendix|appendices)|associated\\s+(?:content|data|file|files|dataset|datasets)|data\\s+(?:supplement|supplements|set|sets|file|files|dataset|datasets)|(?:source|research)\\s+data|online[-\\s]+(?:supplement|appendix|material)|extended\\s+data|extra\\s+material|supplementary\\s+files?|supporting\\s+files?|appendix|appendices|\\b(?:s\\.?\\s*i\\.?|e\\.?\\s*s\\.?\\s*i\\.?|e\\.?\\s*s\\.?\\s*m)\\b|supp\\.?\\s*(?:info(?:rmation)?|mat(?:erial)?|data|files?)|suppdata|\\u8865\\u5145(?:\\u4fe1\\u606f|\\u8d44\\u6599|\\u6750\\u6599|\\u6570\\u636e|\\u6587\\u4ef6|\\u9644\\u5f55)|\\u652f\\u6301(?:\\u4fe1\\u606f|\\u8d44\\u6599|\\u6750\\u6599|\\u6570\\u636e|\\u6587\\u4ef6)|\\u9644\\u52a0(?:\\u4fe1\\u606f|\\u8d44\\u6599|\\u6750\\u6599|\\u6587\\u4ef6)|\\u7535\\u5b50\\u8865\\u5145|\\u5728\\u7ebf\\u8865\\u5145|\\u6570\\u636e\\u96c6",
  "i",
);
const SI_URL_PATTERN = /supporting|supplementary|supplemental|supplement|suppl(?:ement)?|suppl_file|downloadSupplement|suppdata|additional[-_]?(?:information|material|data|files?)|associated[-_]?(?:content|data|file|dataset)|electronic[-_]?supp|online[-_]?(?:supp|appendix)|extended[-_]?data|extra[-_]?material|data[-_]?(?:supplement|set|dataset)|(?:source|research)[-_]?data|appendix|appendices|(?:^|[\/_-])esi(?:[\/_?.-]|$)|(?:^|[\/_-])si(?:[\/_?.-]|$)/i;
const SI_FILE_PATTERN = /\.(?:pdf|docx?|zip|cif|rtf|xlsx?|csv|tsv|txt|json|xml|7z|rar|tar|gz|pptx?|od[stp]|mat|h5|hdf5|nc|npy|r|py|m|mm|tex|bib|md|mol|sdf|pdb|mp4|m4v|mov|avi|webm|mp3|wav|jpe?g|png|gif|svg)(?:$|[?#])/i;
const SI_GENERIC_RESOURCE_PATTERN = /(?:^|[\/])(?:robots|sitemap(?:[-_]index)?|favicon|manifest|browserconfig|security|humans|ads|crossdomain|clientaccesspolicy|service-worker)(?:\.[^\/?#]+)?$/i;
const SI_WEB_ASSET_PATTERN = /\.(?:css|js|mjs|map|woff2?|ttf|otf|eot)(?:$|[?#])/i;
const SI_NOISE_PATTERN = /citation|export|reference|abstract|metrics|share|author|related|purchase|issue|article\s+tools?|login|sign[\s-]*in|cookie|privacy|terms|rss|atom|feed|search|navigation|menu/i;


function scoreSiCandidate(candidate) {
  const label = [candidate.text, candidate.ariaLabel, candidate.title, candidate.download, candidate.rel, candidate.id, candidate.className, candidate.context]
    .filter(Boolean)
    .join(" ");
  let parsedUrl;
  try {
    parsedUrl = new URL(candidate.href);
  } catch {
    return { score: -Infinity, evidence: ["invalid-url"] };
  }
  const pathAndQuery = `${parsedUrl.pathname}${parsedUrl.search}`;
  if (SI_GENERIC_RESOURCE_PATTERN.test(parsedUrl.pathname)) {
    return { score: -Infinity, evidence: ["generic-site-resource"] };
  }
  if (SI_WEB_ASSET_PATTERN.test(pathAndQuery)) {
    return { score: -Infinity, evidence: ["web-asset"] };
  }
  let score = 0;
  const evidence = [];
  if (SI_LABEL_PATTERN.test(label)) {
    score += 80;
    evidence.push("label");
  }
  if (SI_URL_PATTERN.test(pathAndQuery)) {
    score += 70;
    evidence.push("url");
  }
  if (SI_FILE_PATTERN.test(pathAndQuery)) {
    score += 25;
    evidence.push("file-extension");
  }
  if (candidate.download) {
    score += 15;
    evidence.push("download-attribute");
  }
  if (/supp|support|suppl|suppdata|additional|associated|appendix/i.test(`${candidate.id} ${candidate.className}`)) {
    score += 35;
    evidence.push("dom-attribute");
  }
  if (SI_NOISE_PATTERN.test(label) && !SI_LABEL_PATTERN.test(label)) score -= 20;
  if (parsedUrl.hostname === "localhost" || parsedUrl.hostname === "127.0.0.1") {
    evidence.push("local-test-host");
  }
  return { score, evidence };
}


function discoverSiCandidates(rawCandidates, articleUrl, maxLinks) {
  const articleKey = stripHash(articleUrl);
  const byUrl = new Map();
  for (const rawCandidate of rawCandidates) {
    if (!rawCandidate.href) continue;
    const href = stripHash(rawCandidate.href);
    if (href === articleKey) continue;
    const scored = scoreSiCandidate({ ...rawCandidate, href });
    if (scored.score < 45) continue;
    const existing = byUrl.get(href);
    if (!existing || scored.score > existing.score) {
      byUrl.set(href, {
        ...rawCandidate,
        href,
        score: scored.score,
        evidence: scored.evidence,
      });
    } else {
      existing.evidence = [...new Set([...existing.evidence, ...scored.evidence])];
    }
  }
  return [...byUrl.values()]
    .sort((left, right) => right.score - left.score || left.href.localeCompare(right.href))
    .slice(0, maxLinks);
}

async function withBrowserSession(options, callback) {
  let opened = false;
  try {
    const openArgs = [options.url, "--browser", options.browser];
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
    return await callback();
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

async function navigateBrowser(options, urlText) {
  runPlaywright(options, "goto", urlText);
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
}

async function fetchAuthorizedResource(options, urlText, mode, referer) {
  let firstError;
  try {
    const fetched = await fetchBrowserResponse(options, urlText, referer);
    validateResource(fetched.buffer, fetched.contentType, fetched.finalUrl || urlText, mode);
    return {
      ...fetched,
      source: "browser",
    };
  } catch (error) {
    firstError = error;
  }

  if (!options.headed && options.cloudflare !== "auto") {
    throw firstError;
  }

  try {
    await navigateBrowser(options, urlText);
    const fetched = await fetchBrowserResponse(options, urlText, referer);
    validateResource(fetched.buffer, fetched.contentType, fetched.finalUrl || urlText, mode);
    return {
      ...fetched,
      source: "browser",
    };
  } catch (error) {
    throw new Error(`Browser file request failed: ${errorText(firstError)} Navigation retry failed: ${errorText(error)}`);
  }
}

async function captureFromBrowser(options) {
  return withBrowserSession(options, async () => {
    const requestsOutput = runPlaywright(options, "--json", "requests", "--static");
    const requests = parseRequestListing(requestsOutput)
      .filter((request) => request.method === "GET" && request.status >= 200 && request.status < 300)
      .filter((request) => isBrowserResourceUrl(request.url))
      .sort((left, right) => candidateScore(right, options.url, options.mode) - candidateScore(left, options.url, options.mode));

    let lastError;
    for (const request of requests) {
      let headers;
      try {
        headers = parseHeaders(runPlaywright(options, "--raw", "response-headers", String(request.index)));
      } catch (error) {
        lastError = error;
        continue;
      }
      const contentType = normalizeContentType(headers.get("content-type"));
      if (!likelyDocumentContentType(contentType, options.mode, request.url)) continue;

      try {
        const buffer = await readBrowserResponseBody(options, request.index);
        validateResource(buffer, contentType, request.url, options.mode);
        return {
          buffer,
          contentType,
          finalUrl: request.url,
          source: "browser",
          contentDisposition: headers.get("content-disposition") || undefined,
        };
      } catch (error) {
        lastError = error;
        try {
          const fetched = await fetchBrowserResponse(options, request.url);
          validateResource(fetched.buffer, fetched.contentType || contentType, request.url, options.mode);
          return {
            buffer: fetched.buffer,
            contentType: fetched.contentType || contentType,
            finalUrl: fetched.finalUrl || request.url,
            source: "browser",
            contentDisposition: headers.get("content-disposition") || undefined,
          };
        } catch (browserFetchError) {
          lastError = browserFetchError;
        }
      }
    }

    const detail = lastError ? ` Last candidate error: ${errorText(lastError)}` : "";
    throw new Error(`No valid ${options.mode === "pdf" ? "PDF" : "supplementary-information file"} response was found in the browser network log.${detail}`);
  });
}

async function captureResource(options) {
  if (options.headed) {
    return captureFromBrowser(options);
  }

  try {
    return await fetchResource(options.url, options.mode);
  } catch (directError) {
    if (options.cloudflare !== "auto") {
      throw new Error(
        `${errorText(directError)} Use --cloudflare auto for a browser retry, and add --headed when manual login or challenge interaction is required.`,
      );
    }
    try {
      return await captureFromBrowser(options);
    } catch (browserError) {
      throw new Error(`Direct capture failed: ${errorText(directError)} Browser capture failed: ${errorText(browserError)}`);
    }
  }
}

async function persistResource(options, resource, output, mode = options.mode, url = options.url) {
  const effectiveMode = mode === "discover-si" ? "si" : mode;
  const resolvedOutput = resolve(output);
  await mkdir(dirname(resolvedOutput), { recursive: true });
  await writeFile(resolvedOutput, resource.buffer);
  return {
    success: true,
    url,
    finalUrl: resource.finalUrl,
    mode: effectiveMode,
    source: resource.source,
    contentType: resource.contentType || undefined,
    extension: extensionForResource(resource, effectiveMode),
    contentDisposition: resource.contentDisposition,
    output: resolvedOutput,
    bytes: resource.buffer.length,
    sha256: crypto.createHash("sha256").update(resource.buffer).digest("hex"),
  };
}

async function saveOne(options) {
  const resource = await captureResource(options);
  return persistResource(options, resource, options.output);
}

function discoveredFilename(articleUrl, candidate, articleIndex, linkIndex, resource) {
  const articleSlug = safeNamePart(outputMetadata(articleUrl).slug, "article").slice(0, 60);
  let linkSlug = candidate.text;
  if (!linkSlug) {
    linkSlug = outputMetadata(candidate.href).path;
  }
  linkSlug = safeNamePart(linkSlug, "supplement").slice(0, 60);
  const extension = extensionForResource(resource, "si");
  return `${String(articleIndex).padStart(3, "0")}-si-${String(linkIndex).padStart(2, "0")}-${articleSlug}-${linkSlug}.${extension}`;
}

async function discoverArticle(options, articleIndex, usedNames) {
  return withBrowserSession(options, async () => {
    const raw = parseJsonOutput(
      runPlaywright(options, "--raw", "eval", discoveryExpression()),
      "SI link discovery",
    );
    const candidates = discoverSiCandidates(
      Array.isArray(raw) ? raw : [],
      options.url,
      options.maxLinks,
    );
    const result = {
      index: articleIndex,
      articleUrl: options.url,
      candidates,
      saved: [],
      failed: [],
    };

    if (!options.discoverOnly) {
      for (let i = 0; i < candidates.length; i += 1) {
        const candidate = candidates[i];
        const linkIndex = i + 1;
        try {
          const resource = await fetchAuthorizedResource(
            options,
            candidate.href,
            "si",
            options.url,
          );
          const filename = uniqueFilename(
            discoveredFilename(options.url, candidate, articleIndex, linkIndex, resource),
            usedNames,
          );
          const saved = await persistResource(
            { ...options, url: candidate.href },
            resource,
            resolve(options.outputDir, filename),
            "si",
            candidate.href,
          );
          result.saved.push({
            linkIndex,
            score: candidate.score,
            evidence: candidate.evidence,
            text: candidate.text,
            href: candidate.href,
            ...saved,
          });
        } catch (error) {
          result.failed.push({
            linkIndex,
            score: candidate.score,
            evidence: candidate.evidence,
            text: candidate.text,
            href: candidate.href,
            success: false,
            error: errorText(error),
          });
        }
      }
    }

    result.success = candidates.length > 0 && (
      options.discoverOnly || result.failed.length === 0
    );
    if (candidates.length === 0) {
      result.error = "No high-confidence Supporting Information/Supplementary Material links were found";
    }
    return result;
  });
}

async function saveDiscoverySingle(options) {
  const outputDir = resolve(options.outputDir);
  await mkdir(outputDir, { recursive: true });
  let result;
  try {
    result = await discoverArticle(options, 1, new Set());
  } catch (error) {
    result = {
      index: 1,
      articleUrl: options.url,
      candidates: [],
      saved: [],
      failed: [],
      success: false,
      error: errorText(error),
    };
  }
  const record = {
    generatedAt: new Date().toISOString(),
    mode: "discover-si",
    ...result,
  };
  await writeFile(
    resolve(outputDir, "discovery.json"),
    `${JSON.stringify(record, null, 2)}\n`,
    "utf8",
  );
  console.log(JSON.stringify(record));
  if (!result.success) process.exitCode = 1;
}

async function saveDiscoveryList(options) {
  const urls = await readUrlList(options.urlList);
  const outputDir = resolve(options.outputDir);
  await mkdir(outputDir, { recursive: true });
  const usedNames = new Set();
  const results = [];

  for (let i = 0; i < urls.length; i += 1) {
    const index = i + 1;
    const itemOptions = {
      ...options,
      url: urls[i],
      session: sessionNameFor(options, index),
    };
    let result;
    try {
      result = await discoverArticle(itemOptions, index, usedNames);
    } catch (error) {
      result = {
        index,
        articleUrl: urls[i],
        candidates: [],
        saved: [],
        failed: [],
        success: false,
        error: errorText(error),
      };
    }
    results.push(result);
    await writeFile(
      resolve(outputDir, `${String(index).padStart(3, "0")}-discovery.json`),
      `${JSON.stringify({ generatedAt: new Date().toISOString(), mode: "discover-si", ...result }, null, 2)}\n`,
      "utf8",
    );
    console.log(JSON.stringify(result));
    if (!result.success && options.failFast) break;
  }

  const succeeded = results.filter((result) => result.success).length;
  const failed = results.length - succeeded;
  const summary = {
    success: failed === 0 && results.length === urls.length,
    list: resolve(options.urlList),
    outputDir,
    mode: "discover-si",
    total: urls.length,
    attempted: results.length,
    succeeded,
    failed,
    results,
  };
  await writeFile(
    resolve(outputDir, "manifest.json"),
    `${JSON.stringify({ generatedAt: new Date().toISOString(), ...summary }, null, 2)}\n`,
    "utf8",
  );
  console.log(JSON.stringify(summary));
  if (!summary.success) process.exitCode = 1;
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
        renderOutputName(url, index, options.outputTemplate, options.mode),
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
    mode: options.mode,
    total: urls.length,
    attempted: results.length,
    succeeded,
    failed,
    results,
  };
  try {
    await writeFile(
      resolve(outputDir, "manifest.json"),
      `${JSON.stringify({
        generatedAt: new Date().toISOString(),
        ...summary,
      }, null, 2)}\n`,
      "utf8",
    );
  } catch (error) {
    summary.success = false;
    summary.manifestError = errorText(error);
  }
  console.log(JSON.stringify(summary));
  if (!summary.success) process.exitCode = 1;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.mode === "discover-si") {
    if (options.urlList) {
      await saveDiscoveryList(options);
    } else {
      await saveDiscoverySingle(options);
    }
    return;
  }
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
