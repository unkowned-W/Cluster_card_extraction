#!/usr/bin/env python3
"""Convert local PDFs to flat DOI-named Markdown files with the MinerU API.

Only the main Markdown file is retained. Images and the downloaded ZIP are
discarded because the original PDF remains available as the visual fallback.
Credentials are read from MINERU_API_KEY or a local .env file.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError as exc:
    raise SystemExit("缺少 requests：请先在当前 Python 环境安装 requests。") from exc

API_ROOT = "https://mineru.net/api/v4"
TERMINAL_FAILURE_STATES = {"failed", "error", "cancelled", "canceled"}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_dotenv_if_present(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _read_ledger(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row.get("pdf_path", ""): row for row in csv.DictReader(handle) if row.get("pdf_path")}


def _write_ledger(path: Path, rows: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["pdf_path", "md_path", "status", "batch_id", "error", "updated_at"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows, key=str.lower))


def _select_markdown_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    candidates = [
        item for item in archive.infolist()
        if not item.is_dir() and item.filename.lower().endswith(".md") and item.file_size > 0
    ]
    if not candidates:
        raise FileNotFoundError("MinerU ZIP 中没有非空 Markdown 文件")

    preferred = {"full.md": 0, "content.md": 1, "article.md": 2}
    candidates.sort(
        key=lambda item: (
            preferred.get(Path(item.filename).name.lower(), 10),
            -item.file_size,
        )
    )
    return candidates[0]


def _save_main_markdown(zip_path: Path, destination: Path) -> None:
    """Copy only the principal Markdown member; do not extract images/assets."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        member = _select_markdown_member(archive)
        content = archive.read(member)
    if not content.strip():
        raise ValueError("MinerU 返回的 Markdown 为空")
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    temp_path.write_bytes(content)
    os.replace(temp_path, destination)


class MinerUClient:
    def __init__(self, token: str, timeout: int = 120) -> None:
        if not token:
            raise ValueError("未设置 MINERU_API_KEY")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def submit(
        self,
        pdf_path: Path,
        *,
        is_ocr: bool = False,
        language: str = "en",
        model_version: str = "vlm",
    ) -> str:
        if pdf_path.stat().st_size > 200 * 1024 * 1024:
            raise ValueError(f"文件超过 MinerU 精准解析 API 的 200 MB 限制: {pdf_path.name}")
        data_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", pdf_path.stem)[:128] or "document"
        payload = {
            "enable_formula": True,
            "enable_table": True,
            "language": language,
            "model_version": model_version,
            "files": [{"name": pdf_path.name, "is_ocr": is_ocr, "data_id": data_id}],
        }
        response = self.session.post(
            f"{API_ROOT}/file-urls/batch", json=payload, timeout=self.timeout
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(f"申请上传地址失败: {body.get('msg') or body}")
        data = body.get("data") or {}
        urls = data.get("file_urls") or []
        batch_id = data.get("batch_id")
        if not batch_id or not urls:
            raise RuntimeError(f"MinerU 返回缺少 batch_id/file_urls: {body}")
        with pdf_path.open("rb") as handle:
            uploaded = requests.put(urls[0], data=handle, timeout=self.timeout)
        uploaded.raise_for_status()
        return str(batch_id)

    def wait_result(self, batch_id: str, *, poll_seconds: int = 10, max_wait: int = 3600) -> str:
        url = f"{API_ROOT}/extract-results/batch/{batch_id}"
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
            if body.get("code") not in (None, 0):
                raise RuntimeError(f"查询解析状态失败: {body.get('msg') or body}")
            results = ((body.get("data") or {}).get("extract_result") or [])
            if not results:
                time.sleep(poll_seconds)
                continue
            result = results[0]
            state = str(result.get("state") or "").lower()
            if state == "done":
                zip_url = result.get("full_zip_url")
                if not zip_url:
                    raise RuntimeError("任务完成但没有 full_zip_url")
                return str(zip_url)
            if state in TERMINAL_FAILURE_STATES:
                raise RuntimeError(f"MinerU 解析失败: {result.get('err_msg') or result}")
            time.sleep(poll_seconds)
        raise TimeoutError(f"等待 MinerU 任务超时: {batch_id}")

    def download(self, url: str, destination: Path) -> None:
        with requests.get(url, stream=True, timeout=self.timeout) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)


def convert_one(
    client: MinerUClient,
    pdf_path: Path,
    md_root: Path,
    *,
    overwrite: bool = False,
    is_ocr: bool = False,
    language: str = "en",
    model_version: str = "vlm",
    poll_seconds: int = 10,
    max_wait: int = 3600,
) -> tuple[Path, str]:
    pdf_path = pdf_path.resolve()
    md_path = md_root.resolve() / f"{pdf_path.stem}.md"
    if md_path.is_file() and md_path.stat().st_size > 0 and not overwrite:
        return md_path, ""

    batch_id = client.submit(
        pdf_path, is_ocr=is_ocr, language=language, model_version=model_version
    )
    zip_url = client.wait_result(batch_id, poll_seconds=poll_seconds, max_wait=max_wait)
    md_root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f"{pdf_path.stem}.", suffix=".zip", dir=md_root)
    os.close(fd)
    temp_zip = Path(temp_name)
    try:
        client.download(zip_url, temp_zip)
        _save_main_markdown(temp_zip, md_path)
    finally:
        temp_zip.unlink(missing_ok=True)
    return md_path, batch_id


def run_batch(
    pdf_dir: Path,
    md_root: Path,
    log_csv: Path,
    *,
    limit: int | None = None,
    overwrite: bool = False,
    is_ocr: bool = False,
    language: str = "en",
    model_version: str = "vlm",
    poll_seconds: int = 10,
    max_wait: int = 3600,
) -> list[dict[str, str]]:
    _load_dotenv_if_present(Path.cwd() / ".env")
    client = MinerUClient(os.getenv("MINERU_API_KEY", "").strip())
    ledger = _read_ledger(log_csv)
    all_pdfs = sorted(pdf_dir.glob("*.pdf"), key=lambda p: p.name.lower())
    pending: list[Path] = []
    existing_count = 0
    for pdf_path in all_pdfs:
        md_path = md_root / f"{pdf_path.stem}.md"
        if md_path.is_file() and md_path.stat().st_size > 0 and not overwrite:
            existing_count += 1
        else:
            pending.append(pdf_path)
    if limit is not None:
        pending = pending[:limit]
    print(f"PDF 总数: {len(all_pdfs)}；已有 Markdown: {existing_count}；本批待转换: {len(pending)}")

    results: list[dict[str, str]] = []
    for index, pdf_path in enumerate(pending, start=1):
        key = str(pdf_path.resolve())
        print(f"[{index}/{len(pending)}] 提交: {pdf_path.name}")
        try:
            md_path, batch_id = convert_one(
                client,
                pdf_path,
                md_root,
                overwrite=overwrite,
                is_ocr=is_ocr,
                language=language,
                model_version=model_version,
                poll_seconds=poll_seconds,
                max_wait=max_wait,
            )
            row = {
                "pdf_path": key,
                "md_path": str(md_path),
                "status": "success",
                "batch_id": batch_id,
                "error": "",
                "updated_at": _now(),
            }
            print(f"  完成: {md_path}")
        except Exception as exc:
            row = {
                "pdf_path": key,
                "md_path": "",
                "status": "failed",
                "batch_id": "",
                "error": str(exc),
                "updated_at": _now(),
            }
            print(f"  失败: {exc}")
        ledger[key] = row
        results.append(row)
        _write_ledger(log_csv, ledger)
    return results


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, default=root / "documents" / "pdf")
    parser.add_argument("--md-dir", type=Path, default=root / "documents" / "md")
    parser.add_argument("--log", type=Path, default=root / "data" / "process_csv" / "mineru_conversion_log.csv")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--ocr", action="store_true", help="扫描型 PDF 启用 OCR")
    parser.add_argument("--language", default="en")
    parser.add_argument("--model-version", choices=["pipeline", "vlm"], default="vlm")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--max-wait", type=int, default=3600)
    args = parser.parse_args()
    run_batch(
        args.pdf_dir,
        args.md_dir,
        args.log,
        limit=args.limit,
        overwrite=args.overwrite,
        is_ocr=args.ocr,
        language=args.language,
        model_version=args.model_version,
        poll_seconds=args.poll_seconds,
        max_wait=args.max_wait,
    )


if __name__ == "__main__":
    main()
