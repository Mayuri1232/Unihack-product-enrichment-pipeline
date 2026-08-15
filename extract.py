"""
extract.py

Reads a raw input file and turns each row into a clean, normalized
dict of the 6 base fields defined in schema.INPUT_COLUMNS.

Supports: CSV (structured, no LLM needed), and PDF / free text / images
(unstructured -- uses Gemini to find and pull out the 6 fields from
messy text, since that's genuinely where LLM help adds the most value
compared to already-clean CSV rows).

extract_auto(path) picks the right extractor automatically based on
file extension, for callers (app.py, streamlit_app.py) that don't
want to handle format detection themselves.

All extractors funnel into normalize_row(), so the rest of the
pipeline (enrich.py, writer.py) never needs to know which input
format a product originally came from.
"""

import csv
import json
import os
import re

from schema import INPUT_COLUMNS

# pip install pdfplumber python-dotenv google-genai --break-system-packages
import pdfplumber
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.5-flash-lite"  # same model confirmed working in enrich.py

_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Placeholder values Unilog uses in the input data to mean "no value".
# These should be treated as blank, not as real brand names --
# otherwise "-- Unbranded --" would end up looking like an actual brand.
PLACEHOLDER_VALUES = {
    "-- unbranded --",
    "-- no unilog brand --",
    "-- no dib brand --",
    "-",
    "n/a",
    "na",
    "none",
    "unknown",
    "",
}


def _clean_value(value: str) -> str:
    """Strip whitespace and convert known placeholder strings to ''."""
    if value is None:
        return ""
    value = value.strip()
    if value.lower() in PLACEHOLDER_VALUES:
        return ""
    return value


def split_manufacturer_code(part_manuf: str) -> tuple[str, str]:
    """Part_Manuf often looks like 'Freud Inc (2435)' -- a distributor
    name followed by a code in parentheses. Split them apart so
    downstream steps can use the name for search queries and keep the
    code separately if needed.

    Returns (name, code). code is '' if no parenthesized code found.
    """
    match = re.match(r"^(.*)\(([^)]+)\)\s*$", part_manuf.strip())
    if match:
        name = match.group(1).strip()
        code = match.group(2).strip()
        return name, code
    return part_manuf.strip(), ""


def normalize_row(raw_row: dict) -> dict:
    """Take one raw CSV row (dict with INPUT_COLUMNS keys) and return
    a cleaned version: placeholders removed, whitespace stripped,
    manufacturer code split out.
    """
    cleaned = {col: _clean_value(raw_row.get(col, "")) for col in INPUT_COLUMNS}

    manuf_name, manuf_code = split_manufacturer_code(cleaned["Part_Manuf"])
    cleaned["Part_Manuf_Name"] = manuf_name
    cleaned["Part_Manuf_Code"] = manuf_code

    return cleaned


def extract_from_csv(path: str) -> list[dict]:
    """Read the input CSV and return a list of normalized product dicts."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        missing = set(INPUT_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Input CSV is missing expected columns: {sorted(missing)}. "
                f"Found columns: {reader.fieldnames}"
            )

        return [normalize_row(row) for row in reader]


# ---------------------------------------------------------------------------
# Messy input support: free text, PDF, images.
#
# Unlike extract_from_csv (which reads clean, already-labeled columns),
# these formats hand us unstructured text/pixels where the 6 base
# fields aren't cleanly separated -- a paragraph might contain a part
# number, description, and brand all run together. Gemini is used
# here purely as a STRUCTURE-EXTRACTION step: "pull out what's
# literally stated," never invent missing fields. This is the same
# "extract only, don't guess" discipline used in enrich.py.
# ---------------------------------------------------------------------------

_STRUCTURE_PROMPT = """You are extracting structured product records from raw, possibly messy text.
The text may describe ONE product or MULTIPLE products (e.g. a parts list, an invoice, a catalog page).

For EACH distinct product you find, extract these fields if stated:
- Mfg_Part_Num: the manufacturer's part number / SKU / model number
- Part_Desc: the product description
- Part_Manuf: the manufacturer or distributor name (include any code in parentheses if present)
- E1_Brand: a brand name, only if explicitly labeled as such
- Unilog_Brand: leave "" unless explicitly present
- DIB_Brand: leave "" unless explicitly present

Rules:
- Do NOT invent a part number, description, or brand that isn't actually
  in the text. If a field isn't stated, use "".
- If the text describes multiple products (e.g. a list/table), return
  one object per product.
- If you truly cannot find any product information at all, return an
  empty list.

Return ONLY a JSON array of objects with exactly these keys:
Mfg_Part_Num, Part_Desc, Part_Manuf, E1_Brand, Unilog_Brand, DIB_Brand

Text to extract from:
---
{raw_text}
---

Return ONLY the JSON array, no markdown formatting, no explanation."""


def _parse_json_array(raw_text: str) -> list[dict]:
    """Strip markdown code fences (if any) and parse a JSON array."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, list):
        raise ValueError("Expected a JSON array from the structure-extraction call.")
    return parsed


def extract_from_text(raw_text: str) -> list[dict]:
    """Take raw, unstructured text (pasted text, OCR output, etc.) and
    return a list of normalized product dicts.

    This is the format where LLM help matters most -- CSV rows are
    already structured, but free text needs an actual extraction step
    to find part numbers/descriptions/brands buried in prose.
    """
    if not _client:
        raise RuntimeError(
            "GEMINI_API_KEY not configured -- required for text extraction "
            "(unlike extract_from_csv, this needs the LLM to find structure "
            "in unstructured text)."
        )

    if not raw_text or not raw_text.strip():
        return []

    prompt = _STRUCTURE_PROMPT.format(raw_text=raw_text[:8000])  # keep prompt size sane

    response = _client.models.generate_content(model=MODEL_NAME, contents=prompt)
    raw_products = _parse_json_array(response.text)

    return [normalize_row(p) for p in raw_products]


def extract_from_pdf(path: str) -> list[dict]:
    """Extract text from a PDF (via pdfplumber) and run it through the
    same structure-extraction step as extract_from_text.

    Handles multi-page PDFs by concatenating all page text before
    extraction -- a parts list or spec sheet may span several pages.
    """
    full_text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            full_text_parts.append(page_text)

    full_text = "\n".join(full_text_parts)

    if not full_text.strip():
        raise ValueError(
            f"No extractable text found in {path}. If this is a scanned "
            f"image-based PDF, use extract_from_image() on rendered page "
            f"images instead -- pdfplumber only reads embedded text."
        )

    return extract_from_text(full_text)


def extract_from_image(image_path: str) -> list[dict]:
    """Extract product info from an image (photo of a label, scanned
    page, etc.) using Gemini's vision input directly -- no separate
    OCR step needed, Gemini reads the image and extracts structure
    in one call.
    """
    if not _client:
        raise RuntimeError(
            "GEMINI_API_KEY not configured -- required for image extraction."
        )

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    mime_type = mime_map.get(ext, "image/png")

    prompt = _STRUCTURE_PROMPT.format(
        raw_text="[No separate text provided -- read the attached image directly.]"
    )

    response = _client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            {"inline_data": {"mime_type": mime_type, "data": image_bytes}},
            prompt,
        ],
    )
    raw_products = _parse_json_array(response.text)

    return [normalize_row(p) for p in raw_products]


def extract_auto(path: str) -> list[dict]:
    """Convenience dispatcher: picks the right extractor based on file
    extension. Useful for app.py / streamlit_app.py so they don't need
    their own format-detection logic.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".csv":
        return extract_from_csv(path)
    elif ext == ".pdf":
        return extract_from_pdf(path)
    elif ext in (".png", ".jpg", ".jpeg", ".webp"):
        return extract_from_image(path)
    elif ext == ".txt":
        with open(path, encoding="utf-8") as f:
            return extract_from_text(f.read())
    else:
        raise ValueError(
            f"Unsupported file type: {ext}. Supported: .csv, .pdf, "
            f".txt, .png, .jpg, .jpeg, .webp"
        )


if __name__ == "__main__":
    products = extract_from_csv("data/input/sample_input.csv")

    print(f"Parsed {len(products)} products from CSV.\n")

    print("First 3 normalized products:")
    for p in products[:3]:
        print(" ", p)

    # Sanity checks worth knowing before building enrich.py on top of this
    no_desc = [p for p in products if not p["Part_Desc"]]
    no_part_num = [p for p in products if not p["Mfg_Part_Num"]]
    unbranded_count = sum(1 for p in products if not p["E1_Brand"])
    unique_manufacturers = {p["Part_Manuf_Name"] for p in products if p["Part_Manuf_Name"]}

    print(f"\nRows missing Part_Desc: {len(no_desc)}")
    print(f"Rows missing Mfg_Part_Num: {len(no_part_num)}")
    print(f"Rows with no E1_Brand (placeholder cleaned): {unbranded_count}/{len(products)}")
    print(f"Unique distributor/manufacturer names found: {len(unique_manufacturers)}")
    print(f"Sample of manufacturer names: {sorted(list(unique_manufacturers))[:5]}")

    # Smoke test the messy-text extractor, if a key is configured.
    if _client:
        print("\n--- Testing extract_from_text() on a messy sample ---")
        messy_sample = (
            "Item: DCB518ASTS06G, Diablo brand 1/2 in x 18 in sanding belt, "
            "pack of 6, distributed by Freud Inc (code 2435). "
            "Also have PDSH4816AF - a Frigidaire dishwasher, stainless steel."
        )
        text_products = extract_from_text(messy_sample)
        print(f"Extracted {len(text_products)} product(s) from free text:")
        for p in text_products:
            print(" ", p)
    else:
        print("\n(GEMINI_API_KEY not set -- skipping extract_from_text() smoke test)")