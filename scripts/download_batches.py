# -*- coding: utf-8 -*-
"""Step 4: download one batch of article PDFs through the local html-page-saver skill."""
from __future__ import annotations

import csv
import html as html_module
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Iterable

try:
    from .ccdc_data import doi_filename, normalize_doi
except ImportError:
    from ccdc_data import doi_filename, normalize_doi

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILL = ROOT / "skills" / "html-page-saver" / "scripts"
CITATION_PDF_RES = (
    re.compile(r"<meta\b[^>]*(?:name|property)\s*=\s*['\"](?:citation_pdf_url|pdfurl|wkhealth_pdf_url)['\"][^>]*content\s*=\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"<meta\b[^>]*content\s*=\s*['\"]([^'\"]+)['\"][^>]*(?:name|property)\s*=\s*['\"](?:citation_pdf_url|pdfurl|wkhealth_pdf_url)['\"]", re.I),
    re.compile(r"<link\b[^>]*type\s*=\s*['\"]application/pdf['\"][^>]*href\s*=\s*['\"]([^'\"]+)['\"]", re.I),
)


def _valid_pdf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 5:
        return False
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def _load_dois(csv_path: Path) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        doi_col = next((name for name in fields if name.lower() == "doi"), None)
        if not doi_col:
            raise ValueError("CSV 中没有 doi 列")
        for row in reader:
            doi = normalize_doi(row.get(doi_col) or "")
            key = doi.lower()
            if doi and key not in seen:
                seen.add(key)
                result.append(doi)
    return result


def _find_node() -> str:
    configured = os.environ.get("NODE_EXE", "").strip()
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("node")
    if found:
        return found
    raise FileNotFoundError("找不到 node.exe；请先安装 Node.js，或把 node 加入 PATH")


def _node_run(node: str, script: Path, args: list[str], timeout: int) -> dict:
    env = os.environ.copy()
    env["PATH"] = str(Path(node).resolve().parent) + os.pathsep + env.get("PATH", "")
    try:
        proc = subprocess.run(
            [node, str(script), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Node/浏览器执行超时"}
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    for line in reversed(stdout.splitlines()):
        if line.lstrip().startswith("{"):
            try:
                data = json.loads(line)
                if stderr:
                    data["_stderr"] = stderr[-500:]
                return data
            except json.JSONDecodeError:
                pass
    return {"success": False, "error": (stderr or stdout or f"node exit {proc.returncode}")[-800:]}


def publisher_pdf_candidates(doi: str) -> list[str]:
    low = doi.lower()
    quoted = urllib.parse.quote(doi, safe="")
    urls: list[str] = []
    if low.startswith("10.1021/"):
        urls.extend([
            f"https://pubs.acs.org/doi/pdf/{doi}",
            f"https://pubs.acs.org/doi/pdfdirect/{doi}?download=true",
        ])
    if low.startswith("10.1039/"):
        urls.append(f"https://pubs.rsc.org/en/content/articlepdf/{doi}")
    if low.startswith("10.1002/"):
        urls.extend([
            f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}",
            f"https://onlinelibrary.wiley.com/doi/pdf/{doi}",
        ])
    if low.startswith(("10.1007/", "10.1023/")):
        urls.append(f"https://link.springer.com/content/pdf/{quoted}.pdf")
    if low.startswith("10.1038/"):
        urls.append(f"https://www.nature.com/articles/{doi.split('/', 1)[1]}.pdf")
    return list(dict.fromkeys(urls))


def _browser_args(headed: bool, challenge_timeout: int, wait_ms: int, browser: str = "chrome") -> list[str]:
    args = [
        "--browser", browser,
        "--cloudflare", "auto",
        "--challenge-timeout", str(challenge_timeout),
        "--wait", str(wait_ms),
    ]
    if headed:
        args.append("--headed")
    return args


def _download_direct(
    node: str,
    skill_dir: Path,
    url: str,
    dest: Path,
    session: str,
    headed: bool,
    challenge_timeout: int,
    wait_ms: int,
) -> tuple[bool, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not _valid_pdf(dest):
        dest.unlink()
    args = [
        url, "--mode", "pdf", "--output", str(dest),
        *_browser_args(headed, challenge_timeout, wait_ms),
        "--session", session,
    ]
    result = _node_run(node, skill_dir / "save_pdf_si.mjs", args, challenge_timeout + 240)
    if result.get("success") and _valid_pdf(dest):
        return True, f"{result.get('bytes', dest.stat().st_size)} bytes; {result.get('finalUrl', url)}"
    if dest.exists() and not _valid_pdf(dest):
        dest.unlink()
    detail = result.get("error") or result.get("_stderr") or "未得到有效 PDF"
    return False, str(detail)[:500]


def _find_landing_pdf(
    node: str,
    skill_dir: Path,
    landing_url: str,
    session: str,
    headed: bool,
    challenge_timeout: int,
    wait_ms: int,
) -> tuple[str | None, str]:
    with tempfile.TemporaryDirectory(prefix="cluster_landing_") as folder:
        output = Path(folder) / "landing.html"
        args = [
            landing_url, "--output", str(output), "--mode", "rendered",
            "--javascript", "strip", "--css", "keep",
            "--cloudflare", "auto", "--challenge-timeout", str(challenge_timeout),
            "--wait", str(wait_ms), "--session", session,
        ]
        if headed:
            args.append("--headed")
        result = _node_run(node, skill_dir / "save_html.mjs", args, challenge_timeout + 240)
        if not result.get("success") or not output.exists():
            detail = result.get("error") or result.get("_stderr") or "落地页保存失败"
            return None, str(detail)[:500]
        text = output.read_text(encoding="utf-8", errors="ignore")
    for pattern in CITATION_PDF_RES:
        match = pattern.search(text)
        if match:
            url = html_module.unescape(match.group(1).strip())
            return urllib.parse.urljoin(landing_url, url), "找到 citation_pdf_url"
    return None, "页面中没有 citation_pdf_url"


def _read_existing_log(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return ["doi", "status", "file", "detail"], []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _update_log(path: Path, results: Iterable[dict[str, str]]) -> None:
    """Update either the new four-column log or the old project's wider log without losing history."""
    fields, rows = _read_existing_log(path)
    if not fields:
        fields = ["doi", "status", "file", "detail"]
    old_style = "pdf_status" in fields
    by_doi = {normalize_doi(row.get("doi") or "").lower(): row for row in rows if normalize_doi(row.get("doi") or "")}
    order = [normalize_doi(row.get("doi") or "").lower() for row in rows if normalize_doi(row.get("doi") or "")]
    for result in results:
        key = result["doi"].lower()
        row = by_doi.get(key, {name: "" for name in fields})
        row["doi"] = result["doi"]
        if old_style:
            row["pdf_status"] = {"ok": "downloaded", "skipped": "skipped", "failed": "failed"}[result["status"]]
            if "pdf_file" in fields:
                row["pdf_file"] = result["file"]
        else:
            for name in ("status", "file"):
                if name not in fields:
                    fields.append(name)
                row[name] = result[name]
        if "detail" not in fields:
            fields.append("detail")
        row["detail"] = result["detail"]
        by_doi[key] = row
        if key not in order:
            order.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for key in order:
            writer.writerow(by_doi[key])


def _update_failures(path: Path, batch: list[str], results: list[dict[str, str]]) -> None:
    failures: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                doi = normalize_doi(row.get("doi") or "")
                if doi:
                    failures[doi.lower()] = {"doi": doi, "reason": row.get("reason") or ""}
    for doi in batch:
        failures.pop(doi.lower(), None)
    for row in results:
        if row["status"] == "failed":
            failures[row["doi"].lower()] = {"doi": row["doi"], "reason": row["detail"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["doi", "reason"])
        writer.writeheader()
        writer.writerows(failures.values())


def run(
    csv_path: str | Path,
    pdf_dir: str | Path | None = None,
    batch_size: int = 50,
    batch_index: int = 0,
    failed_csv: str | Path | None = None,
    log_csv: str | Path | None = None,
    challenge_timeout: int = 120,
    headed: bool = True,
    wait_ms: int = 4000,
    skill_dir: str | Path | None = None,
) -> list[dict[str, str]]:
    """Download one zero-based DOI batch and return its result rows."""
    if batch_size <= 0:
        raise ValueError("batch_size 必须大于 0")
    if batch_index < 0:
        raise ValueError("batch_index 不能小于 0")

    source = Path(csv_path)
    output_dir = Path(pdf_dir) if pdf_dir else ROOT / "documents" / "pdf"
    failed_path = Path(failed_csv) if failed_csv else ROOT / "documents" / "failed_dois.csv"
    log_path = Path(log_csv) if log_csv else ROOT / "documents" / "download_log.csv"
    saver_dir = Path(skill_dir) if skill_dir else DEFAULT_SKILL
    for script_name in ("save_pdf_si.mjs", "save_html.mjs"):
        if not (saver_dir / script_name).exists():
            raise FileNotFoundError(f"缺少 skill 脚本: {saver_dir / script_name}")

    all_dois = _load_dois(source)
    start = batch_index * batch_size
    batch = all_dois[start:start + batch_size]
    if not batch:
        print(f"批次 {batch_index} 为空。唯一 DOI 总数: {len(all_dois)}")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    node = _find_node()
    results: list[dict[str, str]] = []
    print(f"唯一 DOI: {len(all_dois)}；当前批次: {batch_index}；范围: {start + 1}-{start + len(batch)}")

    for position, doi in enumerate(batch, 1):
        dest = output_dir / doi_filename(doi)
        print(f"[{position}/{len(batch)}] {doi}", flush=True)
        if _valid_pdf(dest):
            results.append({"doi": doi, "status": "skipped", "file": str(dest), "detail": "已有有效 PDF"})
            continue

        session = f"cluster-b{batch_index}-{position}-{int(time.time()) % 100000}"
        details: list[str] = []
        success = False
        for candidate in publisher_pdf_candidates(doi):
            ok, detail = _download_direct(
                node, saver_dir, candidate, dest, session + "-direct",
                headed, challenge_timeout, wait_ms,
            )
            if ok:
                results.append({"doi": doi, "status": "ok", "file": str(dest), "detail": f"直链: {detail}"})
                success = True
                break
            details.append(f"直链 {candidate}: {detail}")
        if success:
            continue

        landing = f"https://doi.org/{doi}"
        pdf_url, landing_detail = _find_landing_pdf(
            node, saver_dir, landing, session + "-landing",
            headed, challenge_timeout, wait_ms,
        )
        details.append(f"落地页: {landing_detail}")
        if pdf_url:
            ok, detail = _download_direct(
                node, saver_dir, pdf_url, dest, session + "-pdf",
                headed, challenge_timeout, wait_ms,
            )
            if ok:
                results.append({"doi": doi, "status": "ok", "file": str(dest), "detail": f"落地页 PDF: {detail}"})
                continue
            details.append(f"PDF: {detail}")

        results.append({"doi": doi, "status": "failed", "file": "", "detail": " | ".join(details)[-1500:]})

    _update_log(log_path, results)
    _update_failures(failed_path, batch, results)
    counts = {status: sum(row["status"] == status for row in results) for status in ("ok", "skipped", "failed")}
    print(f"完成：下载 {counts['ok']}；已有 {counts['skipped']}；失败 {counts['failed']}")
    print(f"失败 DOI: {failed_path}")
    print(f"下载日志: {log_path}")
    return results
