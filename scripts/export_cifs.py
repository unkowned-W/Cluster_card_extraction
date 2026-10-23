# -*- coding: utf-8 -*-
"""Export CIFs with each CSD query isolated from the Notebook kernel."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
CSD_API_HOME = Path(os.environ.get("CSD_API_HOME", "D:/CCDC/ccdc-software/csd-python-api"))
CSD_PYTHON = Path(os.environ.get("CSD_PYTHON", CSD_API_HOME / "miniconda" / "python.exe"))
FIELDS = ["ccdc_number", "refcode", "status", "file", "detail"]

def _clean_ccdc_number(value: str) -> str:
    text = (value or "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def _load_targets(csv_path: Path, lookup_by: str = "ccdc") -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Load unique deposition numbers or exact refcodes."""
    targets: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if lookup_by not in {"ccdc", "refcode"}:
            raise ValueError("lookup_by must be 'ccdc' or 'refcode'")
        if lookup_by == "ccdc" and "ccdc_number" not in (reader.fieldnames or []):
            raise ValueError("CSV 必须包含列: ccdc_number")
        if lookup_by == "refcode" and "refcode" not in (reader.fieldnames or []):
            raise ValueError("CSV must contain refcode")
        for row in reader:
            refcode = (row.get("refcode") or row.get("refcodes") or "").strip().upper()
            ccdc = _clean_ccdc_number(row.get("ccdc_number") or "")
            if lookup_by == "refcode":
                for code in (part.strip() for part in refcode.split("|")):
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    targets.append({"refcode": code, "ccdc_number": ccdc})
                continue
            if not ccdc.isascii() or not ccdc.isdigit() or int(ccdc) <= 0:
                rejected.append({
                    "ccdc_number": ccdc, "refcode": refcode,
                    "status": "failed", "file": "",
                    "detail": "CCDC 编号缺失或不是有效正整数，需人工核查",
                })
                continue
            ccdc = str(int(ccdc))
            if ccdc in seen:
                continue
            seen.add(ccdc)
            targets.append({"refcode": refcode, "ccdc_number": ccdc})
    if lookup_by == "refcode" and targets:
        try:
            from .ccdc_data import lookup_records
        except ImportError:
            from ccdc_data import lookup_records
        records = lookup_records([item["refcode"] for item in targets])
        for item in targets:
            item["ccdc_number"] = records[item["refcode"]]["ccdc_number"]
            if not item["ccdc_number"]:
                raise ValueError(f"CSD has no deposition number for {item['refcode']}")
    return targets, rejected


def _pending_targets(
    targets: list[dict[str, str]],
    rows: list[dict[str, str]],
    overwrite: bool,
    destination_for: Callable[[dict[str, str]], Path],
    preview_mode: bool = False,
) -> list[dict[str, str]]:
    pending = []
    for item in targets:
        dest = destination_for(item)
        exists = dest.is_file() and dest.stat().st_size > 0
        if exists and preview_mode:
            status = "would_overwrite" if overwrite else "would_skip"
            rows.append({**item, "status": status, "file": str(dest), "detail": "文件已存在"})
        elif exists and not overwrite:
            rows.append({**item, "status": "skipped", "file": str(dest), "detail": "文件已存在"})
        else:
            pending.append(item)
    return pending


def preview(
    csv_path: str | Path,
    out_dir: str | Path | None = None,
    overwrite: bool = False,
    lookup_by: str = "ccdc",
) -> list[dict[str, str]]:
    """Plan CCDC-number exports without starting CSD or writing files."""
    if lookup_by != "ccdc":
        raise ValueError("只读预览仅支持 lookup_by='ccdc'；refcode 查询需要访问 CSD")
    source = Path(csv_path)
    output_dir = Path(out_dir) if out_dir else ROOT / "CIFs"
    targets, rows = _load_targets(source, lookup_by=lookup_by)
    pending = _pending_targets(
        targets, rows, overwrite,
        lambda item: output_dir / f"{item['ccdc_number']}.cif",
        preview_mode=True,
    )
    rows.extend({
        **item,
        "status": "would_export",
        "file": str(output_dir / f"{item['ccdc_number']}.cif"),
        "detail": "",
    } for item in pending)
    return rows

def _save_log(path: Path, rows: list[dict[str, str]]) -> None:
    """Replace the log atomically, including the currently processing number."""
    fd, name = tempfile.mkstemp(prefix=".cif_log_", suffix=".csv", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _update_catalog(path: Path, record: dict[str, str]) -> None:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fields = ["refcode", "ccdc_number", "doi", "formula"]
    existing = next((row for row in rows if row["refcode"] == record["refcode"]), None)
    if existing is not None:
        existing.update(record)
    else:
        rows.append(record)
    fd, name = tempfile.mkstemp(prefix=".cluster_complex_", suffix=".csv", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _export_one(number: str, output_dir: Path, overwrite: bool,
                refcode: str = "", lookup_by: str = "ccdc", filename: str = "") -> dict[str, str]:
    """Worker only: never import CCDC in the parent Notebook process."""
    row = {"ccdc_number": number, "refcode": refcode, "status": "failed", "file": "", "detail": ""}
    original_path = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = os.pathsep.join(
            part for part in original_path.split(os.pathsep)
            if "\\microsoft\\windowsapps" not in part.lower()
        )
        from ccdc import io, search
    except Exception as exc:
        return {**row, "status": "blocked", "detail": f"CSD API 初始化失败: {exc}"}
    finally:
        os.environ["PATH"] = original_path

    dest = output_dir / (filename or f"{number}.cif")
    temp = None
    try:
        if dest.exists() and dest.stat().st_size > 0 and not overwrite:
            return {**row, "status": "skipped", "file": str(dest), "detail": "文件已存在"}
        if lookup_by == "refcode":
            entry = io.EntryReader("CSD").entry(refcode)
            if entry is None or entry.identifier.upper() != refcode:
                return {**row, "status": "not_found", "detail": "Exact refcode not found"}
        else:
            query = search.TextNumericSearch()
            query.add_ccdc_number(int(number))
            hits = query.search()
            if not hits:
                return {**row, "status": "not_found", "detail": "当前 CSD 数据库未查到该 CCDC 编号"}
            if len(hits) != 1:
                return {**row, "status": "ambiguous",
                        "refcode": " | ".join(sorted({hit.identifier for hit in hits})),
                        "detail": "编号命中多条结构，保留全部候选，未导出"}
            entry = hits[0].entry
        row["refcode"] = entry.identifier
        crystal = entry.crystal
        if crystal is None:
            raise ValueError("CSD 条目没有 crystal 数据")
        fd, name = tempfile.mkstemp(prefix=f".export_{number}_", suffix=".cif", dir=output_dir)
        os.close(fd)
        temp = Path(name)
        with io.CrystalWriter(str(temp)) as writer:
            writer.write(crystal)
        if temp.stat().st_size == 0:
            raise IOError("导出的 CIF 为空")
        temp.replace(dest)
        return {**row, "status": "exported", "file": str(dest)}
    except Exception as exc:
        return {**row, "detail": str(exc)}
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _run_worker(item: dict[str, str], output_dir: Path, overwrite: bool,
                python: str, timeout: float, lookup_by: str = "ccdc", filename: str = "") -> dict[str, str]:
    base = {**item, "file": "", "detail": ""}
    # The worker persists its result before interpreter shutdown. If shutdown
    # crashes, still mark the crash and retain the result for investigation.
    with tempfile.TemporaryDirectory(prefix="csd_worker_") as directory:
        result_path = Path(directory) / "result.json"
        command = [python, str(Path(__file__).resolve()), "--worker",
                   item["ccdc_number"], str(output_dir), str(result_path), str(int(overwrite)),
                   item["refcode"], lookup_by, filename]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return {**base, "status": "timeout", "detail": f"导出子进程超过 {timeout:g} 秒，已终止"}
        except BaseException:
            proc.kill()
            proc.communicate()
            raise
        result = None
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        if proc.returncode != 0:
            detail = f"导出子进程异常退出，exit code={proc.returncode} (0x{proc.returncode & 0xffffffff:08X})"
            diagnostic = (stderr or stdout).decode("utf-8", errors="replace")[-3000:]
            if diagnostic:
                detail += ": " + diagnostic
            if result is not None:
                detail += "; 退出前结果: " + result["status"]
            return {**(result or base), "status": "crashed", "detail": detail}
        if result is None:
            return {**base, "status": "failed", "detail": "子进程未返回结果"}
        return result


def run(csv_path: str | Path, out_dir: str | Path | None = None,
        overwrite: bool = False, log_csv: str | Path | None = None,
        python_executable: str | Path | None = None,
        worker_timeout: float = 120, lookup_by: str = "ccdc",
        catalog_csv: str | Path | None = None) -> Path:
    """Export via CCDC number or exact refcode in isolated workers."""
    if worker_timeout <= 0:
        raise ValueError("worker_timeout 必须大于 0")
    source = Path(csv_path).resolve()
    output_dir = (Path(out_dir) if out_dir else ROOT / "CIFs").resolve()
    log_path = (Path(log_csv) if log_csv else ROOT / "data" / "process_csv" / "export_cifs_log.csv").resolve()
    python = str(python_executable or (CSD_PYTHON if CSD_PYTHON.exists() else sys.executable))
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    targets, rows = _load_targets(source, lookup_by)
    metadata = {}
    if catalog_csv is not None:
        if lookup_by != "refcode":
            raise ValueError("catalog_csv requires lookup_by='refcode'")
        try:
            from .ccdc_data import lookup_records, normalize_doi
        except ImportError:
            from ccdc_data import lookup_records, normalize_doi
        metadata = lookup_records([item["refcode"] for item in targets])
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reviewed = list(csv.DictReader(handle))
        paired = set()
        for source_row in reviewed:
            codes = [part.strip().upper() for part in source_row["refcode"].split("|")]
            dois = [part.strip() for part in (source_row.get("source_doi") or source_row.get("doi") or "").split("|")]
            if not any(dois) and all(code in paired for code in codes):
                continue
            if len(codes) != len(dois) or not all(dois):
                raise ValueError("DOI/refcode pairing is incomplete")
            for code, doi in zip(codes, dois):
                if normalize_doi(metadata[code]["doi"]).lower() != normalize_doi(doi).lower():
                    raise ValueError(f"DOI mismatch: {code}: {doi}")
                metadata[code]["doi"] = doi
                paired.add(code)
    from collections import Counter
    number_counts = Counter(item["ccdc_number"] for item in targets)
    def filename(item: dict[str, str]) -> str:
        number = item["ccdc_number"]
        return (f"{number}_{item['refcode']}.cif"
                if lookup_by == "refcode" and number_counts[number] > 1
                else f"{number}.cif")
    pending = _pending_targets(
        targets, rows, overwrite,
        lambda item: output_dir / filename(item),
    )
    if catalog_csv is not None:
        for row in rows:
            if row["status"] == "skipped":
                _update_catalog(Path(catalog_csv), metadata[row["refcode"]])
    # Preserve the previous run's diagnoses even when retrying the same list.
    if log_path.exists():
        import shutil
        from datetime import datetime
        backup = log_path.with_name(log_path.stem + "." + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".csv")
        shutil.copy2(log_path, backup)
    _save_log(log_path, rows)
    print(f"待处理 {len(pending)} 个编号；每个编号使用独立 CSD 子进程。", flush=True)
    for index, item in enumerate(pending, 1):
        processing = {**item, "status": "processing", "file": "", "detail": "正在子进程中查询/导出"}
        _save_log(log_path, rows + [processing])
        print(f"[{index}/{len(pending)}] 开始 {item['ccdc_number']}", flush=True)
        try:
            result = _run_worker(item, output_dir, overwrite, python, worker_timeout,
                                 lookup_by, filename(item))
        except KeyboardInterrupt:
            rows.append({**processing, "status": "interrupted", "detail": "用户中断，子进程已终止"})
            _save_log(log_path, rows)
            raise
        except Exception as exc:
            result = {**processing, "status": "blocked", "detail": f"无法启动或读取子进程: {exc}"}
        rows.append(result)
        if catalog_csv is not None and result["status"] == "exported":
            _update_catalog(Path(catalog_csv), metadata[item["refcode"]])
        if result["status"] == "blocked":
            rows.extend({**other, "status": "blocked", "file": "", "detail": result["detail"]}
                        for other in pending[index:])
        _save_log(log_path, rows)
        print(f"[{index}/{len(pending)}] {item['ccdc_number']}: {result['status']} {result['refcode']}", flush=True)
        if result["status"] == "blocked":
            raise RuntimeError(result["detail"] + f"。请检查 CSD Python 环境和 CCDC 许可证。日志: {log_path}")
    from collections import Counter
    print(f"导出结果: {dict(Counter(row['status'] for row in rows))}")
    print(f"日志: {log_path}")
    return log_path


if __name__ == "__main__":
    if len(sys.argv) not in {6, 9} or sys.argv[1] != "--worker":
        raise SystemExit("This module is called by Notebook run() or --worker.")
    result = _export_one(sys.argv[2], Path(sys.argv[3]), bool(int(sys.argv[5])),
                         *(sys.argv[6:] if len(sys.argv) == 9 else ()))
    Path(sys.argv[4]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
