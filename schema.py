"""
schema.py

Single source of truth for the reduced output schema.
Every other module (Gemini prompts, CSV writer, Streamlit preview)
should import COLUMNS from here instead of hardcoding field names,
so there is exactly one place to change if the schema evolves.

This schema is a deliberately reduced subset of Unilog's full
252-column "Expected Output - Delivery Format", scoped down to the
fields that were actually populated in their own example row.
"""

# How many ATTRIBUTE_LABEL/VALUE/UOM slot triples to keep.
# Their example row used well under 15 of the available 50 -- 10 is a
# safe working number. Change this in one place if needed.
NUM_ATTRIBUTE_SLOTS = 10

# --- 1. Identifiers ---
IDENTIFIER_COLUMNS = [
    "PART_NUMBER",
    "SKU",
    "Mfg_Part_Num",
    "MANUFACTURER_PART_NUMBER",
]

# --- 2. Classification ---
CLASSIFICATION_COLUMNS = [
    "Dept",
    "Class",
    "Fine",
    "Classpath",
]

# --- 3. Brand / Manufacturer ---
BRAND_COLUMNS = [
    "Part_Manuf",
    "MANUFACTURER_NAME",
    "BRAND_NAME",
    "E1_Brand",
    "Unilog_Brand",
    "DIB_Brand",
]

# --- 4. Descriptions ---
DESCRIPTION_COLUMNS = [
    "Product Name",
    "Part_Desc",
    "SHORT_DESC",
    "LONG_DESC1",
    "RETAIL_DESC",
    "INVOICE_DESC",
    "MOBILE_DESC",
]

# --- 5. Key Attributes (dynamic, fixed number of slots) ---
ATTRIBUTE_COLUMNS = []
for _i in range(1, NUM_ATTRIBUTE_SLOTS + 1):
    ATTRIBUTE_COLUMNS.append(f"ATTRIBUTE_LABEL_{_i}")
    ATTRIBUTE_COLUMNS.append(f"ATTRIBUTE_VALUE_{_i}")
    ATTRIBUTE_COLUMNS.append(f"ATTRIBUTE_UOM_{_i}")

# --- 6. Compliance / Extras ---
COMPLIANCE_COLUMNS = [
    "Standard/Approvals",
    "Warranty",
    "With",
]

# --- 7. Media / Source ---
MEDIA_COLUMNS = [
    "MFR URL",
    "Product Image",
    "Specification Sheet",
]

# --- 8. Pipeline metadata (not part of Unilog's schema, but useful for
#         debugging / judging -- shows where each row's data came from) ---
META_COLUMNS = [
    "source_url_used",       # which URL was scraped, if any
    "part_number_verified",  # True/False -- did the part number appear on the fetched page
    "fields_from_llm_extract",   # comma list of fields derived purely from input text
    "fields_from_llm_lookup",    # comma list of fields grounded in scraped page
]

# Full ordered column list for the output CSV
COLUMNS = (
    IDENTIFIER_COLUMNS
    + CLASSIFICATION_COLUMNS
    + BRAND_COLUMNS
    + DESCRIPTION_COLUMNS
    + ATTRIBUTE_COLUMNS
    + COMPLIANCE_COLUMNS
    + MEDIA_COLUMNS
    + META_COLUMNS
)

# The 6 columns present in the raw hackathon input file.
# Used by extract.py to know what it can read directly, no enrichment needed.
INPUT_COLUMNS = [
    "Mfg_Part_Num",
    "Part_Desc",
    "E1_Brand",
    "Unilog_Brand",
    "DIB_Brand",
    "Part_Manuf",
]

if __name__ == "__main__":
    # Quick sanity check when run directly
    print(f"Total output columns: {len(COLUMNS)}")
    assert len(COLUMNS) == len(set(COLUMNS)), "Duplicate column name detected!"
    print("No duplicate column names. Schema OK.")
    for name, group in [
        ("Identifiers", IDENTIFIER_COLUMNS),
        ("Classification", CLASSIFICATION_COLUMNS),
        ("Brand", BRAND_COLUMNS),
        ("Descriptions", DESCRIPTION_COLUMNS),
        ("Attributes", ATTRIBUTE_COLUMNS),
        ("Compliance", COMPLIANCE_COLUMNS),
        ("Media", MEDIA_COLUMNS),
        ("Meta", META_COLUMNS),
    ]:
        print(f"  {name}: {len(group)} columns")