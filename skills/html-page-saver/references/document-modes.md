# Direct File Modes

Use [scripts/save_pdf_si.mjs](../scripts/save_pdf_si.mjs) for direct article-PDF/SI URLs or `discover-si` when the user supplies an article landing page and wants the helper to find its SI links. This helper is separate from `save_html.mjs`; it does not change HTML capture behavior.

## Modes

- `--mode pdf` requires the response body to begin with `%PDF-`. This prevents login pages, Cloudflare challenge pages, and Chrome PDF viewer HTML from being saved with a `.pdf` name.
- `--mode si` is for publisher supplementary information. It accepts valid non-HTML files such as PDF, DOC/DOCX, RTF, CIF/text, ZIP, spreadsheet files, and other binary attachments. The input should be the direct file URL, not the article landing page.
- `--mode discover-si` renders an article page, finds high-confidence links labeled `Supporting Information`, `Supplementary Material`, `Supplemental Data`, `Additional Information`, `Associated Content`, `Data Availability`, `Source Data`, `Online Supplement`, `Appendix`, `SI`, `ESI`, `ESM`, `supp. info`, and common Chinese equivalents, then downloads the candidates as SI files.
- `--discover-only` writes candidates to `discovery.json` without downloading. `--max-links` caps the number of candidate links inspected.

The helper records the final response URL, detected content type, byte count, SHA-256, and capture source (`direct` or `browser`). URL-list mode also writes `manifest.json` in the output directory.

## Direct Capture

For a public or directly accessible article PDF:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_pdf_si.mjs" `
  "https://publisher.example/article.pdf" `
  --mode pdf `
  --output ".\article.pdf"
```

For a direct SI URL:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_pdf_si.mjs" `
  "https://publisher.example/supplement.pdf" `
  --mode si `
  --output ".\article-si.pdf"
```

For automatic discovery from an article page:

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

Inspect `discovery.json` for each candidate's URL, label, confidence score, and evidence. Discovery is heuristic: it handles ordinary anchors, `area`/role links, common data/attachment URL attributes, nearby link context, and simple `onclick` URLs. It filters generic site resources and common web assets, but it does not click arbitrary controls or infer undocumented download APIs. When a site exposes several unrelated files, use `--discover-only` first.

## Authorized Browser Capture

Use a headed ordinary Chrome session when the publisher requires normal login or a browser challenge:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_pdf_si.mjs" `
  "https://publisher.example/supplement.pdf" `
  --mode si `
  --output ".\article-si.pdf" `
  --headed `
  --browser chrome `
  --cloudflare auto `
  --challenge-timeout 180 `
  --wait 5000 `
  --session article-si
```

The user may complete the publisher's normal sign-in or challenge in the visible browser. The helper then reads a successful file response from the browser's authorized context and validates it before writing the output. If the browser remains on a login/challenge page or only returns the PDF viewer shell, the capture fails.

Do not use proxy rotation, CAPTCHA solving, cookie extraction, cookie replay, stealth patches, or paywall bypasses. The helper never prints, saves, or injects `cf_clearance` or other authentication cookies.

## URL Lists

Use one direct file URL per line. Blank lines and lines beginning with `#` are ignored:

```powershell
node "$env:CODEX_HOME\skills\html-page-saver\scripts\save_pdf_si.mjs" `
  --url-list ".\file-urls.txt" `
  --mode si `
  --output-dir ".\supplements" `
  --headed `
  --cloudflare auto `
  --challenge-timeout 180 `
  --wait 5000 `
  --session supplements
```

The list is processed serially. Failed items are recorded and processing continues unless `--fail-fast` is supplied. In browser list mode, sessions are suffixed with the one-based item number so one item cannot silently reuse another item's browser state. A successful run exits with code `0`; any failed or unattempted item exits with code `1`.

The default filename template is `{index}-{slug}.{ext}`. Supported placeholders are `{index}`, `{host}`, `{path}`, `{slug}`, and `{ext}`. For dynamic download URLs whose extension is not visible in the URL, inspect `manifest.json` and the recorded `contentType`.

## Handoff

To acquire SI from a saved article page, either use `discover-si` on the original article URL or locate the publisher-provided direct attachment URL in the HTML. After the file is saved and validated, use the PDF/document workflow for parsing or rendering it. A link in an article page, a visible browser PDF, and a validated local file are separate states.
