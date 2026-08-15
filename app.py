"""
app.py

FastAPI backend that wires the pipeline together:

    upload file -> extract.py -> enrich.py (per product) -> writer.py -> output CSV

Endpoints:
    POST /enrich        upload an input CSV, get back an enriched output CSV
    GET  /health         simple health check

This is intentionally a thin orchestration layer -- all the actual
logic lives in extract.py / enrich.py / writer.py / search_fetch.py.
app.py just calls them in order and handles the HTTP plumbing.

Run locally with:
    pip install fastapi uvicorn python-multipart --break-system-packages
    uvicorn app:app --reload

Then open http://127.0.0.1:8000/docs for an interactive test UI.
"""

import os
import shutil
import tempfile
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from extract import extract_auto
from enrich import enrich_product, GEMINI_API_KEY
from writer import init_output_csv, append_product_row
from search_fetch import find_verified_source, SEARCH_API_KEY
from validate import build_manufacturer_reference, validate_product
from schema import COLUMNS, NUM_ATTRIBUTE_SLOTS

app = FastAPI(title="Unihack Product Enrichment Pipeline")

OUTPUT_DIR = "data/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.get("/health")
def health():
    """Quick check that the server is up and the Gemini key is configured."""
    return {
        "status": "ok",
        "gemini_key_configured": bool(GEMINI_API_KEY),
        "schema_columns": len(COLUMNS),
    }


@app.post("/enrich")
async def enrich_endpoint(file: UploadFile = File(...), limit: int | None = None):
    """Upload an input CSV, run it through the enrichment pipeline, and
    return a downloadable output CSV.

    limit: optional query param to cap how many rows are processed --
           useful for quick testing without burning API quota on a
           full 1000-row file, e.g. POST /enrich?limit=10
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY not configured on the server. Check .env.",
        )

    if not file.filename.lower().endswith((".csv", ".pdf", ".txt", ".png", ".jpg", ".jpeg", ".webp")):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Supported: .csv, .pdf, .txt, .png, .jpg, .jpeg, .webp",
        )

    # Save the upload to a temp file, preserving its extension so
    # extract_auto() can detect the right extractor to use.
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        products = extract_auto(tmp_path)
    except ValueError as e:
        os.remove(tmp_path)
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    if limit:
        products = products[:limit]

    # Reference list for manufacturer-name self-consistency matching --
    # built from THIS batch's own data, not an official Unilog list
    # (that file was never located -- see validate.py docstring).
    manufacturer_reference = build_manufacturer_reference(products)

    run_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(OUTPUT_DIR, f"enriched_{run_id}.csv")
    init_output_csv(output_path)

    results = {"total": len(products), "succeeded": 0, "failed": 0, "errors": []}

    for product in products:
        try:
            page_text, source_url = None, None
            if SEARCH_API_KEY:
                # Search key is configured -- look up and verify the
                # manufacturer page before enrichment, so MFR URL /
                # spec-grounded fields can actually be filled.
                lookup = find_verified_source(
                    product.get("Mfg_Part_Num", ""),
                    product.get("Part_Manuf_Name", ""),
                )
                if lookup["verified"]:
                    page_text, source_url = lookup["page_text"], lookup["url"]

            enriched = enrich_product(product, page_text=page_text, source_url=source_url)
            enriched = validate_product(enriched, manufacturer_reference, NUM_ATTRIBUTE_SLOTS)
            append_product_row(output_path, enriched)
            results["succeeded"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"part_num": product.get("Mfg_Part_Num", "?"), "error": str(e)})

    results["output_file"] = os.path.basename(output_path)
    results["download_url"] = f"/download/{os.path.basename(output_path)}"
    return results


@app.get("/download/{filename}")
def download(filename: str):
    """Download a previously generated output CSV by filename
    (as returned by the /enrich response)."""
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, media_type="text/csv", filename=filename)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)