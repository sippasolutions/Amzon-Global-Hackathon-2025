"""
MCP Tools for Smart Goal Generator
"""
from strands import tool
import os
import io
import boto3
import requests
import chardet
from docx import Document
from PyPDF2 import PdfReader

import json, time, uuid, re, mimetypes
from typing import Tuple, List, Optional

from botocore.exceptions import BotoCoreError, ClientError


# Globals
s3_client = boto3.client("s3")
DEFAULT_SOURCE = None
DATA_LOG_FILE = "/tmp/fetch_data_log.txt"  # Lambda safe tmp storage

ROW_DELIM = "@"                        # row delimiter for raw data

# ======================
# ===== S3 helpers =====
# ======================
def _parse_s3_uri(uri: str) -> Tuple[str, str]:
    # s3://bucket/key -> (bucket, key)
    assert uri.lower().startswith("s3://"), "Not an s3:// URI"
    without = uri[5:]
    parts = without.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key


def _read_s3_object(s3_path: str) -> bytes:
    """
    Read an object from S3 given s3://bucket/key
    Returns raw bytes.
    """
    bucket, key = _parse_s3_uri(s3_path)
    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"S3 read failed for {s3_path}: {e}")


def _list_s3_uris(s3_prefix: str, extensions: Optional[List[str]] = None) -> List[str]:
    """
    Expand an s3 prefix (ending with '/'): s3://bucket/prefix/ -> [s3://bucket/prefix/file1, ...]
    Optionally filter by extensions ['.docx', '.pdf', '.txt'] (case-insensitive).
    """
    bucket, prefix = _parse_s3_uri(s3_prefix)
    s3 = boto3.client("s3")
    uris = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            if extensions:
                ext = os.path.splitext(key)[1].lower()
                if ext not in [e.lower() for e in extensions]:
                    continue
            uris.append(f"s3://{bucket}/{key}")
    return uris


def _ext_or_mime(uri: str, content_bytes: bytes) -> str:
    mime, _ = mimetypes.guess_type(uri)
    return mime or "application/octet-stream"


def _extract_text_from_bytes(uri: str, content: bytes) -> str:    
    """
    Extract text depending on file type (PDF, DOCX, TXT).
    """
    mime = _ext_or_mime(uri, content)
    luri = uri.lower()
    if luri.endswith(".pdf") or mime == "application/pdf":
        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(p.strip() for p in parts if p)
    if luri.endswith(".docx") or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        d = Document(io.BytesIO(content))
        return "\n".join(p.text for p in d.paragraphs if p.text)
    # Fallback: treat as UTF-8 text
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1", errors="ignore")


# ======================
# ===== helpers ========
# ======================
def _format_rows_as_lines(text: str) -> str:
    """
    If the data uses '@' as a row delimiter, split onto newlines.
    Otherwise, return the text as-is (e.g., clinician notes).
    """
    text = (text or "").strip()
    if ROW_DELIM in text:
        chunks = [c.strip() for c in text.split(ROW_DELIM) if c.strip()]
        return "\n".join(chunks)
    return text


def _save_formatted_to_file(formatted_text: str, log_path: str):
    """
    Save formatted text to local file (e.g., for logging).
    """
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n=== Run at {timestamp} ===\n")
        f.write(formatted_text + "\n")


def _read_jsonl(path: str):
    items = []
    if not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


# --- Internal helper function ----
# ---------- Build SMART-goal cases (rubric-driven) ----------
# ---------- Low-level loaders as tools ----------
@tool
def load_analyzer_runs_v2(analyzer_json_src: str, limit: int | None = None) -> dict:
    # Need to define input source
    """
    Load analyzer outputs (JSONL), sorted by timestamp ASC. Optionally keep only latest 'limit'.
    """
    #runs = _read_jsonl(analyzer_json_src)
    runs = analyzer_json_src
    runs.sort(key=lambda r: r.get("timestamp", ""))
    if limit:
        runs = runs[-limit:]
    return {"runs": runs}

# ---------- Planning tool that abstracts use cases ----------
@tool
def build_eval_plan_v2(analyzer_json_src: str, limit=50) -> dict:
    """
    Decide which evaluation to run based on analyzer_outputs.jsonl contents.
    Returns a plan with:
      {
        "evaluation_type": "engagement_vs_clinician" | "smart_goals_rubric",
        "metrics": ["..."],
        "rubric": { ... optional ... },
        "cases": [ ... normalized cases ... ]
      }
    """
    runs = load_analyzer_runs_v2(analyzer_json_src=analyzer_json_src, limit=limit)["runs"]
    cases = runs
#    cases = _build_smart_goal_cases_v2(runs)
    return {
            "evaluation_type": "smart_goals_rubric",
            "metrics": ["specific", "measurable", "achievable", "relevant", "time_bound", "clarity"],
            "rubric": {
                "specific":   "Clearly states the behavior/target (who/what/when/where).",
                "measurable": "Includes a quantifiable criterion (count, frequency, value).",
                "achievable": "Feasible for the patient (resources/constraints).",
                "relevant":   "Aligned to diabetes/health needs in the notes.",
                "time_bound": "Contains a concrete timeframe or deadline.",
                "clarity":    "Readable, unambiguous, free of contradictions."
            },
            "cases": cases
    }

    # Fallback: nothing to evaluate
    return {
        "evaluation_type": "none",
        "metrics": [],
        "rubric": {},
        "cases": []
    }

"""
def _build_smart_goal_cases_v2(runs):
    
    # Flatten SMART goals from analyzer_output.smart_goals.
    #Each case contains goal text plus a default SMART rubric that the judge can use.
    
    cases = []
    for run in runs:
        ts = run.get("timestamp", "")
        ao = run.get("analyzer_output") or {}
        goals = ao.get("smart_goals") or []
        for g in goals:
            num = g.get("goal_number")
            desc = g.get("description", "")
            cases.append({
                "case_id": f"{ts}::goal_{num}",
                "timestamp": ts,
                "goal_number": num,
                "goal_text": desc,
            })
    return cases

# ---------- Low-level loaders as tools ----------
@tool
def load_analyzer_runs_v2(analyzer_json_src: str, limit: int | None = None) -> dict:
    # Need to define input source
    
    #Load analyzer outputs (JSONL), sorted by timestamp ASC. Optionally keep only latest 'limit'.
    
    runs = _read_jsonl(analyzer_json_src)
    runs.sort(key=lambda r: r.get("timestamp", ""))
    if limit:
        runs = runs[-limit:]
    return {"runs": runs}


# ---------- Planning tool that abstracts use cases ----------
@tool
def build_eval_plan_v2(analyzer_json_src: str, limit=50) -> dict:
    
    #Decide which evaluation to run based on analyzer_outputs.jsonl contents.
    #Returns a plan with:
    #  {
    #    "evaluation_type": "engagement_vs_clinician" | "smart_goals_rubric",
    #    "metrics": ["..."],
    #    "rubric": { ... optional ... },
    #    "cases": [ ... normalized cases ... ]
    #  }
    
    runs = load_analyzer_runs_v2(analyzer_json_src=analyzer_json_src, limit=limit)["runs"]
    has_smart = any((r.get("analyzer_output") or {}).get("smart_goals") for r in runs)

    if has_smart:
        cases = _build_smart_goal_cases_v2(runs)
        return {
            "evaluation_type": "smart_goals_rubric",
            "metrics": ["specific", "measurable", "achievable", "relevant", "time_bound", "clarity"],
            "rubric": {
                "specific":   "Clearly states the behavior/target (who/what/when/where).",
                "measurable": "Includes a quantifiable criterion (count, frequency, value).",
                "achievable": "Feasible for the patient (resources/constraints).",
                "relevant":   "Aligned to diabetes/health needs in the notes.",
                "time_bound": "Contains a concrete timeframe or deadline.",
                "clarity":    "Readable, unambiguous, free of contradictions."
            },
            "cases": cases
        }

    # Fallback: nothing to evaluate
    return {
        "evaluation_type": "none",
        "metrics": [],
        "rubric": {},
        "cases": []
    }
"""

# ================================================
# ----- fetch_data exposed via MCP API gateway ----
# ================================================
@tool
def fetch_data(data_source: str | None = None) -> dict:
    """
    Fetch data from S3, HTTP/HTTPS, or local file.
    Returns { raw_text, formatted_text, meta }.
    """
    ds = data_source or DEFAULT_SOURCE
    if not ds:
        return {
            "error": "No data_source provided.",
            "raw_text": "",
            "formatted_text": "",
            "meta": {"source_type": "unknown", "data_source": str(ds)},
        }

    # S3
    if ds.lower().startswith("s3://"):
        try:
            blob = _read_s3_object(ds)
            raw_text = _extract_text_from_bytes(ds, blob)
        except Exception as e:
            return {
                "error": f"S3 error: {e}",
                "raw_text": "",
                "formatted_text": "",
                "meta": {"source_type": "s3", "data_source": ds},
            }
        formatted = _format_rows_as_lines(raw_text)
        _save_formatted_to_file(formatted, DATA_LOG_FILE)
        return {"raw_text": raw_text, "formatted_text": formatted, "meta": {"source_type": "s3", "data_source": ds}}

    # URL
    if ds.lower().startswith(("http://", "https://")):
        try:
            resp = requests.get(ds, timeout=60)
            resp.raise_for_status()
            raw = resp.text
        except Exception as e:
            return {
                "error": f"HTTP error: {e}",
                "raw_text": "",
                "formatted_text": "",
                "meta": {"source_type": "url", "data_source": ds},
            }
        formatted = _format_rows_as_lines(raw)
        _save_formatted_to_file(formatted, DATA_LOG_FILE)
        return {"raw_text": raw, "formatted_text": formatted, "meta": {"source_type": "url", "data_source": ds}}

    # Local file (only useful for local testing, not Lambda)
    if os.path.exists(ds):
        try:
            if ds.lower().endswith((".pdf", ".docx")):
                with open(ds, "rb") as f:
                    content = f.read()
                raw_text = _extract_text_from_bytes(ds, content)
            else:
                with open(ds, "r", encoding="utf-8") as f:
                    raw_text = f.read()
        except Exception as e:
            return {
                "error": f"File read error: {e}",
                "raw_text": "",
                "formatted_text": "",
                "meta": {"source_type": "file", "data_source": ds},
            }
        formatted = _format_rows_as_lines(raw_text)
        return {"raw_text": raw_text, "formatted_text": formatted, "meta": {"source_type": "file", "data_source": ds}}

    # Unknown
    return {
        "error": f"Unsupported data_source: {ds}",
        "raw_text": "",
        "formatted_text": "",
        "meta": {"source_type": "unknown", "data_source": str(ds)},
    }