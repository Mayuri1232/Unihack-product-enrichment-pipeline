"""
enrich.py

Calls Gemini to enrich one normalized product (from extract.py) into
the fields defined in schema.py.

IMPORTANT -- current scope given no search API key yet:
Only two of the three field categories discussed are active right now:

  1. EXTRACT  -- attributes parsed out of Part_Desc text itself
                 (e.g. "1/2 in x 18 in" -> size attributes)
  2. REFORMAT -- rewrites of the known description into SHORT_DESC,
                 RETAIL_DESC, MOBILE_DESC etc, using ONLY facts already
                 present in the input -- no invented specs.

  3. LOOKUP-GROUNDED (MFR URL, spec-sheet-derived attributes, images)
     is intentionally NOT attempted here. Those fields require a
     verified manufacturer page (search_fetch.py), which needs a
     search API key you don't have yet. Rather than let Gemini guess
     at those fields with no grounding -- which is exactly the
     hallucination risk flagged earlier -- this module leaves them
     blank and records that decision in the meta columns.

Once a search API key is added, call enrich_product() with
page_text=<verified fetched text> to unlock category 3 as well; the
prompt already has a branch for it.
"""

import json
import os
from schema import COLUMNS, ATTRIBUTE_COLUMNS, NUM_ATTRIBUTE_SLOTS

# pip install google-genai python-dotenv --break-system-packages
# NOTE: the older `google-generativeai` package is deprecated as of
# 2025 -- this uses the current `google-genai` SDK instead.
from google import genai
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.5-flash-lite"  # confirmed available via list_models.py -- stable (non-preview) release

_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


# Fields we ask Gemini to produce WITHOUT a verified source page.
# Deliberately excludes MFR URL / Product Image / Specification Sheet --
# those need real grounding and are left blank until search_fetch.py
# is wired in with a search API key.
NO_LOOKUP_TARGET_FIELDS = [
    "PART_NUMBER",
    "SKU",
    "Dept",
    "Class",
    "Fine",
    "Classpath",
    "MANUFACTURER_NAME",
    "BRAND_NAME",
    "Product Name",
    "SHORT_DESC",
    "LONG_DESC1",
    "RETAIL_DESC",
    "INVOICE_DESC",
    "MOBILE_DESC",
] + ATTRIBUTE_COLUMNS


def _build_prompt(product: dict, page_text: str | None) -> str:
    """Build the Gemini prompt. Explicitly instructs the model not to
    invent facts, and to leave a field blank rather than guess --
    this is the main defense against hallucination discussed earlier.
    """
    base_facts = (
        f"Part Number: {product.get('Mfg_Part_Num', '')}\n"
        f"Description: {product.get('Part_Desc', '')}\n"
        f"Manufacturer/Distributor: {product.get('Part_Manuf_Name', '')}\n"
        f"E1 Brand: {product.get('E1_Brand', '')}\n"
    )

    grounding_note = ""
    if page_text:
        # Truncate to keep prompt size sane -- a full manufacturer page
        # can be huge; a few thousand characters is plenty of context.
        grounding_note = (
            "\nAdditional verified source page content (use this for any "
            "spec details, but only state things actually present in it):\n"
            f"{page_text[:4000]}\n"
        )

    attr_slots_desc = "\n".join(
        f"  ATTRIBUTE_LABEL_{i}, ATTRIBUTE_VALUE_{i}, ATTRIBUTE_UOM_{i}"
        for i in range(1, NUM_ATTRIBUTE_SLOTS + 1)
    )

    prompt = f"""You are enriching a single product record for a B2B commerce catalog.

KNOWN FACTS (this is ALL you know about this product -- do not invent
anything beyond what is stated here{" or in the source page below" if page_text else ""}):
{base_facts}{grounding_note}

Return a single JSON object with these fields. For any field you
cannot fill from the facts above, use an empty string "" -- do NOT
guess, do NOT invent plausible-sounding values, do NOT fill in a
typical/average value. An empty string is the correct answer when the
information isn't present in what you were given.

Fields to return:
- PART_NUMBER: same as the input part number, cleaned up
- SKU: same as part number if no separate SKU is implied
- Dept, Class, Fine: a 3-level product category classification
  (e.g. Dept="Tools & Equipment", Class="Abrasives", Fine="Sanding Discs")
  based on the description. Only classify if reasonably confident.
- Classpath: the category path joined with ">" e.g. "Tools & Equipment>Abrasives>Sanding Discs"
- MANUFACTURER_NAME: the actual product manufacturer if identifiable
  from the description or brand fields (note: the "Manufacturer/Distributor"
  fact above may actually be a distributor, not the real manufacturer --
  use judgement, and leave blank if unsure)
- BRAND_NAME: the brand as it would appear on the product itself
- Product Name: a clean, short product name
- SHORT_DESC: a short description (under ~15 words), REWORDED from the
  known description -- do not add new facts
- LONG_DESC1: a longer description using only the known facts
- RETAIL_DESC: a customer-facing description using only the known facts
- INVOICE_DESC: a compact description suitable for an invoice line item
- MOBILE_DESC: a very short description suitable for a mobile screen
- Attribute pairs -- extract any measurable attributes literally stated
  in the description (sizes, grit/grade, pack quantity, material, voltage,
  etc). Use these exact field name patterns for up to {NUM_ATTRIBUTE_SLOTS} pairs:
{attr_slots_desc}
  Only fill as many slots as you have real attributes for; leave the
  rest as "".

Return ONLY the JSON object, no markdown formatting, no explanation."""

    return prompt


def _parse_json_response(raw_text: str) -> dict:
    """Gemini sometimes wraps JSON in markdown code fences -- strip
    those before parsing."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


def enrich_product(product: dict, page_text: str | None = None,
                    source_url: str | None = None) -> dict:
    """Enrich one normalized product dict into schema-shaped fields.

    product: output of extract.normalize_row()
    page_text: verified manufacturer page text, if search_fetch.py
               found and verified one. None means lookup-grounded
               fields are skipped (current default -- no search key yet).
    source_url: the URL page_text came from, for the meta columns.

    Returns a dict with keys matching schema.COLUMNS -- ready to pass
    straight to writer.append_product_row().
    """
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable not set. "
            "Set it before calling enrich_product()."
        )

    prompt = _build_prompt(product, page_text)

    try:
        response = _client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        llm_fields = _parse_json_response(response.text)
    except Exception as e:
        print(f"[enrich] Gemini call/parse failed for "
              f"{product.get('Mfg_Part_Num', '?')}: {e}")
        llm_fields = {}

    # Merge: start from the raw input fields we already trust,
    # layer LLM-derived fields on top, never let the LLM overwrite
    # the original identifiers/brand fields we already know for certain.
    result = {
        "Mfg_Part_Num": product.get("Mfg_Part_Num", ""),
        "Part_Desc": product.get("Part_Desc", ""),
        "Part_Manuf": product.get("Part_Manuf", ""),
        "E1_Brand": product.get("E1_Brand", ""),
        "Unilog_Brand": product.get("Unilog_Brand", ""),
        "DIB_Brand": product.get("DIB_Brand", ""),
        "MANUFACTURER_PART_NUMBER": product.get("Mfg_Part_Num", ""),
    }

    for field in NO_LOOKUP_TARGET_FIELDS:
        value = llm_fields.get(field, "")
        result[field] = value if isinstance(value, str) else str(value)

    # Lookup-grounded fields: only fill if we actually have a verified
    # source page. Left blank otherwise -- see module docstring.
    result["MFR URL"] = source_url if page_text and source_url else ""
    result["Product Image"] = ""
    result["Specification Sheet"] = ""

    # Meta / provenance columns -- makes it obvious in the output CSV
    # exactly how each row was produced, useful for debugging and for
    # explaining scoping decisions to judges.
    fields_from_extract = [f for f in NO_LOOKUP_TARGET_FIELDS if result.get(f)]
    result["source_url_used"] = source_url or ""
    result["part_number_verified"] = bool(page_text)
    result["fields_from_llm_extract"] = ",".join(fields_from_extract)
    result["fields_from_llm_lookup"] = ""  # nothing lookup-grounded yet

    return result


if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not found -- checked .env and environment.")
        print("Copy .env.example to .env and fill in your key, then re-run.")
    else:
        from extract import extract_from_csv

        products = extract_from_csv("data/input/sample_input.csv")
        test_product = products[0]

        print(f"Enriching: {test_product['Mfg_Part_Num']} -- {test_product['Part_Desc']}\n")
        enriched = enrich_product(test_product, page_text=None, source_url=None)

        filled = {k: v for k, v in enriched.items() if v not in ("", False)}
        print(f"Filled {len(filled)}/{len(COLUMNS)} columns:")
        for k, v in filled.items():
            print(f"  {k}: {v}")