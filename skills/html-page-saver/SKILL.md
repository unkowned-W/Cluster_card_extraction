---
name: html-page-saver
description: Save one or many authorized web pages as HTML, or capture direct article-PDF and supplementary-information file URLs with browser-assisted access after a user completes an allowed challenge. Use for webpage archiving and direct file capture; do not use for literature search, general web scraping, access-control bypass, or cookie extraction.
---

# HTML Page Saver

Save a webpage to an `.html` file, or save a direct article PDF/supplementary-information file while preserving the user's requested capture mode and authorization boundary.

## Modes

Choose the mode from the user's intent:

- `raw`: fetch the server response without running page JavaScript. This is the closest option to "save source".
- `rendered`: open the page in a real browser, allow JavaScript to run, wait for dynamic content, then export the current DOM.

`--javascript` controls the saved HTML, not execution:

- `keep`: retain `<script>` elements and their `src` references.
- `strip`: remove `<script>` elements after the page has loaded. In `rendered` mode this preserves content already produced by JavaScript but removes most later interactivity.

`--css` controls the saved HTML:

- `keep`: retain `<style>` elements and `<link rel="stylesheet">` references. External files are not downloaded or bundled.
- `strip`: remove inline styles and stylesheet link elements.

When the user wants a self-contained offline copy, explain that `keep` preserves references rather than downloading every asset. Use `rendered` for pages whose useful content is injected after load. Use `raw` for an exact server response when no transformation is requested.

## Direct File Modes

For a direct article PDF, supplementary-information URL, or article page whose SI link should be found automatically, use the independent helper [scripts/save_pdf_si.mjs](scripts/save_pdf_si.mjs):

- `--mode pdf` accepts only a response whose bytes begin with `%PDF-`.
- `--mode si` accepts common supplementary files such as PDF, DOC/DOCX, RTF, CIF/text, ZIP, spreadsheets, and other non-HTML attachments.
- `--mode discover-si` renders an article page, identifies high-confidence `Supporting Information`, `Supplementary Material`, `Supplemental Data`, `Additional Information`, `Associated Content`, `Data Availability`, `Source Data`, `Online Supplement`, `Appendix`, `SI`, `ESI`, `ESM`, `supp. info`, `补充信息`, `支持材料`, `附加材料`, and similar links, then downloads the discovered attachments as SI files.
- `--discover-only` with `discover-si` writes the candidate links without downloading them. `--max-links` limits the number of candidates inspected.
- `pdf` and `si` require a direct file URL. `discover-si` instead takes the article landing page and locates publisher-provided attachment URLs from its rendered DOM.
- The helper validates the file body, records the final URL/content type/size/SHA-256, and writes a `manifest.json` for URL-list runs.

Read [references/document-modes.md](references/document-modes.md) when the task involves PDF or supplementary-material acquisition. Use `$pdf` or `$documents` after acquisition when the user asks to parse or render the local file.

## Cloudflare-Protected Pages

Some sites show a browser challenge before serving the target page. The supported workflow is browser-session based:

- Use `--mode rendered --cloudflare auto` to let the real browser run the site's JavaScript and wait for the challenge page to disappear.
- Use `--headed` when a user must interact with a visible challenge or sign-in prompt.
- Use a stable `--session` name for the complete capture flow. Keep the browser session with `--keep-session` only when the user explicitly needs it for follow-up work.
- The script never extracts, prints, saves, or injects `cf_clearance` or other authentication cookies. It relies on the browser's own authorized context, because challenge cookies can be bound to session, browser, network, and other request properties.
- Before writing a rendered snapshot, the helper checks the final title/body for known challenge markers again. A page that is still a challenge shell is reported as a failure instead of being saved as a successful article HTML file.
- DOI and publisher redirects can briefly destroy the execution context while navigation is still in progress. With `--cloudflare auto`, the helper treats that transient state as navigation in progress and waits for a stable page before exporting.
- If the challenge remains after `--challenge-timeout`, stop and report that the user needs to complete or authorize access; do not retry with cookie harvesting, stealth patches, proxy rotation, or challenge-solving services.

### Login/challenge timing and publisher redirects

Publisher pages may need substantially more time than an ordinary page load. A first response can be a temporary challenge document even when the article is openly accessible. Do not classify that response as a missing article or permanently inaccessible source until the normal browser has had time to execute the challenge and follow redirects.

The tested recovery sequence is:

1. Try the DOI/publisher URL once without a proxy. If the direct request returns `403`, `401`, an access-denied page, or a challenge shell, stop repeating that HTTP request. The failure is an access result, not evidence that the paper or its HTML is absent.
2. Open the same URL in a normal headed Chrome channel controlled by Playwright, using a stable session name. Do not use the Codex In-app Browser as a substitute for the ordinary Chrome challenge flow, and do not assume that an external headed window is visible merely because an in-app-browser inventory is empty.
3. Use `--mode rendered --cloudflare auto --headed` and set `--challenge-timeout` to at least 120 seconds for a publisher page; use 180 seconds or longer when a login, institutional redirect, migration redirect, or slow challenge is expected. Keep an explicit `--wait` (normally 3000–5000 ms) after the article page becomes available so injected abstract and figure-caption content is present.
4. Verify the resulting page, rather than trusting a successful navigation alone. The title/URL should be an article page, and the DOM should contain positive markers such as the article title, `Abstract`, section headings, or figure captions. A page containing only `Please wait`, `正在进行安全验证`, `Access Denied`, or a login/challenge message is not an article snapshot.
5. Record both the original DOI URL and the final canonical URL. ACS pages may redirect from a DOI URL to a migrated path such as `/accacs/article/...`; the redirected URL is useful for later reproduction, while the DOI remains the stable citation key.

The initial Scholar-expansion failures followed this pattern: direct/automated requests received 403 or challenge HTML, and the browser was checked too soon or in the wrong browser context. The later successful captures used ordinary headed Chrome, allowed the challenge JavaScript to finish, waited for the redirect, and then reran the rendered saver. This timing change is a supported access workflow, not a challenge bypass.

Do not use any of the following as the sole success/failure signal: an HTTP 200/403 status, a `success` navigation result, a browser tab inventory, or a page title such as `Please wait`. The authoritative check is the rendered DOM after the wait: it must contain the article title and readable article markers. In particular, an empty Codex In-app Browser tab list does not prove that a separate headed Chrome/Playwright session failed or closed.

If a visible challenge or sign-in still remains after the timeout, hand the browser to the authorized user. The user may complete the publisher's normal login/challenge, but the tool must never solve a CAPTCHA, replay a challenge, extract authentication cookies, rotate proxies, or bypass a paywall.

Cloudflare handling is for pages the user is authorized to access. It does not defeat a challenge, bypass a paywall, evade rate limits, or override a site's terms.

## Publisher Supplementary-Material Handoff

Article HTML pages often expose a Supporting Information/Supplementary Material link whose target is a PDF, DOCX, CIF, or another downloadable file. Use `scripts/save_pdf_si.mjs --mode si` for the actual direct-file acquisition; hand the validated local file to the PDF/document workflow when the user asks to read it. The helper does not discover or crawl links from an article page automatically.

For a known direct supplement URL:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_pdf_si.mjs" `
  "https://publisher.example/action/downloadSupplement?..." `
  --mode si `
  --output ".\article-si.pdf" `
  --headed `
  --browser chrome `
  --cloudflare auto `
  --challenge-timeout 180 `
  --wait 5000 `
  --session article-si
```

Use this acquisition pattern for an authorized supplementary PDF:

1. Locate the publisher-provided supplement URL in the saved HTML or rendered DOM. Common forms include ACS `.../doi/suppl/<doi>/suppl_file/<file>.pdf` and Wiley `.../action/downloadSupplement?doi=<doi>&file=<file>.pdf`.
2. Try the direct publisher URL once without a proxy. A 403 from `Invoke-WebRequest`, `curl`, or a headless request is an access result, not evidence that the supplement is missing. Do not rotate proxies, harvest cookies, use Tor/WebVPN, or retry indefinitely.
3. If the user has an authorized visible browser session, use a normal Chrome channel controlled by Playwright (`--browser chrome`), with a stable session name. Do not use the Codex In-app Browser for this workflow. Do not configure a proxy, Tor, or WebVPN unless the user explicitly requests and authorizes that separate access path.
4. Let the user complete any publisher challenge or sign-in in the visible browser. Never solve, bypass, replay, or extract challenge/authentication cookies. The helper reads a successful file response from the authorized browser context after the target file becomes available.
5. Chrome's PDF viewer may load an HTML viewer shell and a `chrome-extension://...` viewer resource. Do not save the viewer shell as the PDF. The helper uses the origin response and a browser-context fetch fallback, then verifies the first bytes are `%PDF-` before reporting PDF success.
6. Validate the saved file with `pdfinfo` or the PDF reader: record page count, page size/title when available, source URL, acquisition time, local path, and SHA-256. Keep the raw PDF separate from extracted text and rendered page images.
7. Only after this validation should the PDF skill extract text/render pages and the literature-reading workflow write evidence back to a vault. A visible PDF, a supplement link, and a parsed local PDF are three different states and must be recorded separately.

Useful Playwright CLI pattern (ordinary Chrome, no proxy):

```powershell
npx --yes --package @playwright/cli playwright-cli `
  -s=publisher-si open --browser chrome --headed `
  "https://publisher.example/action/downloadSupplement?..."
npx --yes --package @playwright/cli playwright-cli -s=publisher-si snapshot
npx --yes --package @playwright/cli playwright-cli -s=publisher-si requests --static
npx --yes --package @playwright/cli playwright-cli -s=publisher-si response-body <origin-request-index>
```

The response-body command may produce a `.bin` path even for a PDF. Inspect the header and use the emitted binary only when it begins with `%PDF-`; otherwise it is usually the viewer HTML shell or an access/challenge response. This method was validated for a Wiley SI that became `200 OK` only after the authorized Chrome session completed the publisher challenge.

## CLI

The reusable helper is [scripts/save_html.mjs](scripts/save_html.mjs). Run it with Node:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_html.mjs" `
  "https://example.com" `
  --output ".\page.html" `
  --mode rendered `
  --javascript strip `
  --css keep `
  --wait 1500 `
  --cloudflare auto `
  --headed
```

Defaults are `--mode raw`, `--javascript keep`, and `--css keep`.

### URL lists

To apply the same capture options to several pages, pass a text file with one URL per line:

```text
# urls.txt
https://example.com
https://www.iana.org/domains/example
```

Run the list serially with an output directory:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_html.mjs" `
  --url-list ".\urls.txt" `
  --output-dir ".\snapshots" `
  --mode rendered `
  --javascript strip `
  --css keep `
  --wait 1500
```

Blank lines and lines beginning with `#` are ignored. The default filename template is `{index}-{slug}.html`, where `{index}` is a one-based three-digit item number, `{host}` is the URL host, `{path}` is the sanitized URL path, and `{slug}` combines host, path, and query. Use `--output-template` to choose another filename, for example `--output-template "{index}-{host}.html"`. Unsafe filename characters are sanitized and duplicate names receive a numeric suffix.

Every list item receives the same `--mode`, `--javascript`, `--css`, wait, Cloudflare, headed, and session options. Items are processed one at a time. A failed item is reported and processing continues by default; use `--fail-fast` to stop after the first failure. The process exits with code `1` if any item fails or if the list is incomplete, and the final JSON object includes `total`, `attempted`, `succeeded`, `failed`, and per-item `results`. In rendered mode, a final challenge shell is a failure even if browser navigation itself returned successfully.

In rendered list mode, the session name is suffixed with the item number (`<session>-001`, `<session>-002`, ...), so browser state from one URL does not leak into another. `--keep-session` leaves those named sessions open for authorized follow-up work; otherwise each item is closed after capture. List mode uses `--output-dir` and cannot be combined with a positional URL or `--output`.

### PDF and SI files

Use the separate `save_pdf_si.mjs` helper for direct file URLs. It does not use the HTML `--javascript` or `--css` options:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_pdf_si.mjs" `
  "https://publisher.example/article.pdf" `
  --mode pdf `
  --output ".\article.pdf"
```

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_pdf_si.mjs" `
  --url-list ".\si-urls.txt" `
  --mode si `
  --output-dir ".\supplements" `
  --headed `
  --browser chrome `
  --cloudflare auto `
  --challenge-timeout 180 `
  --wait 5000 `
  --session supplements
```

To discover SI links directly from an article page and download the discovered files:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_pdf_si.mjs" `
  "https://publisher.example/article" `
  --mode discover-si `
  --output-dir ".\article-si" `
  --headed `
  --cloudflare auto `
  --challenge-timeout 180 `
  --wait 5000 `
  --session article-si-discovery
```

Use `--discover-only` to write `discovery.json` without downloading. The discovery mode scores link text, accessibility labels, DOM attributes, download attributes, file extensions, and SI-related URL paths; it deduplicates URLs and saves all candidates above its confidence threshold. It does not click arbitrary article controls or guess undocumented API endpoints. Each run writes `discovery.json` (single article) or numbered discovery files plus `manifest.json` (article list).

`pdf` mode rejects HTML, login pages, challenge shells, and invalid PDF bytes. `si` mode rejects HTML and accepts common supplementary attachments. In list mode the helper writes `manifest.json`; each result includes `source`, `finalUrl`, `contentType`, `bytes`, `sha256`, and `output`. A direct PDF URL must be used; an article landing page is not automatically searched for a PDF or SI link.

For a Cloudflare-protected page where the user can complete the challenge in a visible browser:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_html.mjs" `
  "https://example.com/protected-page" `
  --output ".\protected-page.html" `
  --mode rendered `
  --cloudflare auto `
  --challenge-timeout 120 `
  --headed `
  --session protected-page-session
```

The rendered path uses the existing Playwright CLI through `npx`; it may need the Playwright browser installed. The helper emits a concise JSON result on success and writes the requested HTML file. It does not bypass authentication, paywalls, robots rules, or access controls.

For a slow publisher page, use a longer challenge window and a stable session:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_html.mjs" `
  "https://pubs.acs.org/doi/10.1021/acscatal.5c03544" `
  --output ".\10.1021_acscatal.5c03544.html" `
  --mode rendered `
  --javascript strip `
  --css keep `
  --wait 4000 `
  --cloudflare auto `
  --challenge-timeout 180 `
  --headed `
  --session acs-article
```

The same pattern applies to Wiley pages. If the saver emits `success: true`, still inspect the saved file for article markers and compute a SHA-256 hash before treating it as a usable source.

## Decision Rules

1. Preserve the requested mode and asset policy; do not silently execute JavaScript when the user asked for raw source.
2. If the user says "without JavaScript" but still wants dynamic text, use `rendered --javascript strip`: execute scripts during capture, then remove script elements from the output.
3. If the page is Cloudflare-protected, use `--cloudflare auto`; add `--headed` when human interaction is needed.
4. If the page is private, use the user's authorized browser session or ask them to authenticate; never attempt to defeat access controls.
5. For raw mode with stripping enabled, the helper applies conservative tag removal. For malformed HTML or complex transformations, prefer rendered mode.
6. If `Invoke-WebRequest`, `curl`, `request`/HTTP-client calls, or another non-browser request encounters `403 Forbidden` (or a comparable access-denied response), stop retrying that request and invoke the Playwright CLI directly with an ordinary Chrome session (`--browser chrome`); do not use the Codex In-app Browser, proxy rotation, cookie harvesting, or access-control bypass. If a visible challenge or sign-in is presented, let the authorized user complete it before saving the rendered page.
7. A challenge page that later redirects to a readable article is a timing/context failure, not a source failure. Preserve the failed attempt as an access note if useful, then retry once through the normal headed-browser flow with a longer timeout; do not loop indefinitely.
8. Before literature analysis, distinguish these states: `challenge_only`, `login_required`, `article_html_saved`, `supplement_linked`, `supplement_downloaded`, and `supplement_parsed`. Only `article_html_saved` or a later state permits article evidence extraction; `challenge_only` and `login_required` do not.
9. For Google Scholar discovery in this project, the localhost `10808` proxy is permitted only for Scholar search. Publisher article pages, HTML saving, supplementary downloads, and local source reads must use the direct authorized browser path without that proxy.
10. For a direct article PDF or supplementary-information URL, use `scripts/save_pdf_si.mjs`; do not send the file URL through `save_html.mjs`. Require `%PDF-` validation in `pdf` mode and reject HTML/login/challenge responses in both file modes.

## References

The design of the Cloudflare workflow was informed by the following user-provided articles. Treat them as background context, not as authorization to extract or replay session cookies:

- [CSDN: Cloudflare clearance discussion](https://blog.csdn.net/u010087338/article/details/144609041)
- [Data Journal: scrape CF clearance cookies](https://www.data-journal.org/cn/data-scraping/scrape-cf-clearance-cookies/)
- [Scrapeless: cf_clearance overview](https://www.scrapeless.com/zh/blog/cf-clearance)
