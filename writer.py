"""
writer.py

Takes one enriched product as a flat Python dict (whatever keys
enrich.py produced from Gemini's JSON response) and writes it as a
single row into the output CSV, using schema.COLUMNS as the fixed
column order.

Design choices:
- Missing keys in the input dict become "" in the CSV, not an error --
  a field we couldn't enrich should show up as genuinely blank, not
  crash the pipeline.
- Extra keys in the input dict that aren't in schema.COLUMNS are
  silently dropped (they don't belong in the delivery format), but a
  warning is printed so nothing goes missing silently during dev.
- Writer opens in append mode and writes the header only once, so it
  can be called row-by-row as each product finishes enrichment
  (useful for a Streamlit progress bar / partial results on crash).
"""

import csv
import os
from schema import COLUMNS


def init_output_csv(path: str) -> None:
    """Create the output CSV with just the header, overwriting any
    previous run. Call this once at the start of a batch."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()


def append_product_row(path: str, product: dict) -> None:
    """Append one product's data as a row to the output CSV.

    product: flat dict, e.g. {"PART_NUMBER": "20887830", "Dept": "Appliances", ...}
    path: path to the output CSV. Must already exist with a header
          (call init_output_csv first) or this will create it fresh.
    """
    file_exists = os.path.exists(path)

    # Warn (don't crash) if the product dict has keys outside our schema --
    # helps catch typos in enrich.py's field names during development.
    unknown_keys = set(product.keys()) - set(COLUMNS)
    if unknown_keys:
        print(f"[writer] warning: dropping unrecognized keys: {sorted(unknown_keys)}")

    row = {col: product.get(col, "") for col in COLUMNS}

    mode = "a" if file_exists else "w"
    with open(path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if mode == "w":
            writer.writeheader()
        writer.writerow(row)


def write_all_products(path: str, products: list[dict]) -> None:
    """Convenience: write a full batch of products at once,
    overwriting any existing file."""
    init_output_csv(path)
    for product in products:
        append_product_row(path, product)


if __name__ == "__main__":
    # Smoke test with two fake products -- one fully populated,
    # one sparse -- to confirm blanks and ordering behave correctly.
    test_path = "/tmp/test_output.csv"

    fake_products = [
        {
            "PART_NUMBER": "20887830",
            "Mfg_Part_Num": "PDSH4816AF",
            "Dept": "Appliances",
            "Class": "Large Appliances",
            "Fine": "Dishwashers",
            "MANUFACTURER_NAME": "Rheem Manufacturing",
            "BRAND_NAME": "FRIGIDAIRE\u00ae",
            "Part_Desc": "PDSH4816AF Dishwasher SS - Display Only",
            "SHORT_DESC": "Dishwasher with CleanBoost, 5-cycle, stainless steel.",
            "ATTRIBUTE_LABEL_1": "Voltage Rating",
            "ATTRIBUTE_VALUE_1": "120",
            "ATTRIBUTE_UOM_1": "V",
            "MFR URL": "https://www.frigidaire.com/en/p/owner-center/product-support/PDSH4816AF",
            "source_url_used": "https://www.frigidaire.com/en/p/owner-center/product-support/PDSH4816AF",
            "part_number_verified": True,
        },
        {
            # sparse product -- most fields intentionally missing
            "Mfg_Part_Num": "DCB518ASTS06G",
            "Part_Desc": "DCB518ASTS06G Diablo 1/2\"x18\" - Sanding Belt 6pc",
            "Part_Manuf": "Freud Inc (2435)",
            "part_number_verified": False,
        },
        {
            # deliberately includes a bad/unknown key to test the warning path
            "Mfg_Part_Num": "TEST123",
            "NOT_A_REAL_COLUMN": "should be dropped with a warning",
        },
    ]

    write_all_products(test_path, fake_products)

    print(f"\nWrote {len(fake_products)} rows to {test_path}\n")
    with open(test_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            filled = sum(1 for v in row.values() if v.strip())
            print(f"Row {i}: {filled}/{len(row)} columns filled "
                  f"(Mfg_Part_Num={row['Mfg_Part_Num']!r})")