# HTML Page Saver

`html-page-saver` 是一个面向人类和 Codex skill 使用者的网页归档工具。它可以保存网页 HTML，也可以在用户有权访问的前提下保存论文 PDF 和 Supporting Information（SI）等附件。

它适合以下任务：

- 保存原始 HTML 或浏览器渲染后的 HTML
- 选择是否保留 HTML 中的 JavaScript 和 CSS 引用
- 下载直接 PDF、补充材料和其他非 HTML 附件
- 从论文页面自动发现并下载 SI 链接
- 对 URL 列表批量执行相同的保存操作

## 安装

### 新安装

在 PowerShell 中执行：

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
$skillDir = Join-Path $codexHome "skills\html-page-saver"

New-Item -ItemType Directory -Force -Path (Split-Path $skillDir) | Out-Null
git clone git@git.xmu.edu.cn:ai4catalysis/html-page-saver-skill.git $skillDir
```

### 更新已有安装

```powershell
git -C "$HOME\.codex\skills\html-page-saver" pull --ff-only
```

如果使用了 `CODEX_HOME`，将上面的路径替换为 `$env:CODEX_HOME\skills\html-page-saver`。

## 环境要求

- Node.js 18 或更高版本
- npm/npx
- `rendered`、有头浏览器和 Cloudflare/登录流程需要可用的 Chrome、Edge、Firefox 或 WebKit 浏览器
- PDF 页数和元数据检查可选使用 `pdfinfo`

第一次使用 Playwright CLI 时，`npx` 可能需要下载或准备相关依赖。

## HTML 保存

脚本位置：

```powershell
$htmlSaver = "$HOME\.codex\skills\html-page-saver\scripts\save_html.mjs"
```

### 保存原始 HTML

`raw` 模式直接读取服务器响应，不执行页面 JavaScript：

```powershell
node $htmlSaver `
  "https://example.com/article" `
  --output ".\article.html" `
  --mode raw `
  --javascript keep `
  --css keep
```

### 保存浏览器渲染后的 HTML

`rendered` 模式使用真实浏览器执行 JavaScript，并导出当前 DOM：

```powershell
node $htmlSaver `
  "https://example.com/article" `
  --output ".\article-rendered.html" `
  --mode rendered `
  --javascript strip `
  --css keep `
  --wait 3000 `
  --headed
```

### JavaScript 和 CSS 选项

| 选项 | 含义 |
| --- | --- |
| `--javascript keep` | 保留 `<script>` 标签及其引用 |
| `--javascript strip` | 保存前删除 `<script>` 标签 |
| `--css keep` | 保留 `<style>` 和样式表 `<link>` 引用 |
| `--css strip` | 保存前删除内联样式和样式表链接 |

这些选项控制保存结果，不完全等同于禁用页面运行时。对于动态页面，如果希望先执行 JavaScript、再保存不含脚本的 HTML，应使用：

```powershell
--mode rendered --javascript strip
```

如果希望完全不执行页面 JavaScript，则使用 `--mode raw`。

`css keep` 只保留 CSS 引用，不会自动下载和打包所有外部图片、字体、脚本或样式资源。

## HTML URL 列表

每行一个 URL，空行和以 `#` 开头的行会被忽略：

```text
# urls.txt
https://example.com/article-one
https://example.org/article-two
```

批量保存：

```powershell
node $htmlSaver `
  --url-list ".\urls.txt" `
  --output-dir ".\html-snapshots" `
  --mode rendered `
  --javascript strip `
  --css keep `
  --wait 3000
```

批量运行会在输出目录中写入 `manifest.json`，记录每个 URL 的成功/失败状态、最终 URL、本地文件和错误信息。默认按顺序处理；需要遇到第一个错误就停止时，加上 `--fail-fast`。

## PDF 和 Supporting Information

PDF/SI 使用独立脚本，不使用 HTML 的 `--javascript` 或 `--css` 选项：

```powershell
$fileSaver = "$HOME\.codex\skills\html-page-saver\scripts\save_pdf_si.mjs"
```

### 直接保存 PDF

`pdf` 模式要求文件头为 `%PDF-`，可以避免把登录页、挑战页或 Chrome PDF viewer 外壳误保存为 PDF：

```powershell
node $fileSaver `
  "https://publisher.example/article.pdf" `
  --mode pdf `
  --output ".\article.pdf"
```

### 直接保存 SI 文件

`si` 模式支持 PDF、DOC/DOCX、RTF、CIF、TXT、ZIP、表格及常见数据附件：

```powershell
node $fileSaver `
  "https://publisher.example/action/downloadSupplement?..." `
  --mode si `
  --output ".\article-si.pdf" `
  --headed `
  --cloudflare auto `
  --challenge-timeout 180 `
  --wait 5000
```

### 从文章页面自动发现 SI

当用户只有文章页或 DOI，而没有直接附件 URL 时，使用 `discover-si`：

```powershell
node $fileSaver `
  "https://doi.org/10.1002/adfm.202209114" `
  --mode discover-si `
  --output-dir ".\article-si" `
  --headed `
  --cloudflare auto `
  --challenge-timeout 180 `
  --wait 5000 `
  --session article-si-discovery
```

发现器会识别常见标签和文件线索，包括：

- `Supporting Information`
- `Supplementary Material`、`Supplemental Data`
- `Additional Information`、`Associated Content`
- `Data Availability`、`Source Data`、`Online Supplement`
- `Appendix`、`SI`、`ESI`、`ESM`、`supp. info`
- `补充信息`、`支持材料`、`附加材料`、`数据集`

它还会检查链接文本、ARIA 标签、DOM 属性、附近上下文、下载属性、URL 路径和文件扩展名，并过滤 `robots.txt`、sitemap、favicon、manifest、service worker、CSS/JS 等通用资源。

只发现不下载：

```powershell
node $fileSaver `
  "https://publisher.example/article" `
  --mode discover-si `
  --discover-only `
  --output-dir ".\discovery"
```

发现结果写入 `discovery.json`，其中包含候选 URL、标签、评分、证据、成功下载项和失败项。

### SI URL 列表

如果已经从多个文章页或其他来源取得直接附件 URL，可以批量下载：

```powershell
node $fileSaver `
  --url-list ".\si-urls.txt" `
  --mode si `
  --output-dir ".\supplements" `
  --headed `
  --cloudflare auto `
  --challenge-timeout 180 `
  --wait 5000 `
  --session supplements
```

URL 列表模式会生成 `manifest.json`，包含 `source`、`finalUrl`、`contentType`、文件大小、SHA-256 和本地输出路径。

## 人工挑战和登录

某些出版社会要求正常的 Cloudflare 检查、登录或机构访问。推荐使用有头模式：

1. 使用`tools/simple_pattern_clicker.zip`挂一个自动点击cf的后台软件，软件用法已在压缩包说明。
2. 使用 `--headed --cloudflare auto` 启动普通浏览器。
3. 如果页面显示正常的挑战或登录界面，自动点击cf的后台软件会帮你点了。
4. 脚本等待页面稳定后，再读取页面或附件响应。
5. 检查 `discovery.json`、`manifest.json` 和文件校验信息。

本 skill 不会自动解决 CAPTCHA，不会提取、打印、保存或注入 `cf_clearance`，也不会轮换代理、绕过付费墙或猜测隐藏 API。

## 限制

- `discover-si` 是启发式发现，不是通用网页爬虫。
- 它处理普通链接、`area`/ARIA link、常见 `data-*` URL 属性和简单 `onclick` URL。
- 对必须点击复杂控件、先执行站点内部 API 或通过不可见状态生成 URL 的页面，可能需要人工找到直接附件 URL，再使用 `--mode si`。
- 页面上存在 SI 链接并不保证用户拥有下载权限；登录、机构授权和出版社限制仍然有效。
- 保存 HTML 时，`css keep` 和 `javascript keep` 不代表所有外部资源已被打包成本地离线副本。

## 文件结构

```text
html-page-saver/
├── SKILL.md
├── agents/openai.yaml
├── references/document-modes.md
└── scripts/
    ├── save_html.mjs
    └── save_pdf_si.mjs
```

## 开发和验证

在技能目录中运行：

```powershell
node --check scripts/save_html.mjs
node --check scripts/save_pdf_si.mjs
py -3 -X utf8 `
  "$HOME\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
  "."
```

项目仓库：`git@git.xmu.edu.cn:ai4catalysis/html-page-saver-skill.git`
