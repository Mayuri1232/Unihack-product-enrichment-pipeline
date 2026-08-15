"""
tests/test_extract.py

Tests the offline parts of extract.py -- CSV parsing, placeholder
cleaning, and manufacturer code splitting. These don't need
GEMINI_API_KEY since extract_from_csv has no LLM dependency.

extract_from_text / extract_from_pdf / extract_from_image DO need a
live Gemini key, so they're not covered here -- test those manually
with `python extract.py` once your .env is set up.

Run with:
    pip install pytest --break-system-packages
    pytest tests/test_extract.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from extract import extract_from_csv, split_manufacturer_code, normalize_row

TEST_CSV = os.path.join(os.path.dirname(__file__), "sample_input.csv")


def test_extract_from_csv_returns_all_rows():
    """The 8-row test fixture should produce exactly 8 normalized products."""
    products = extract_from_csv(TEST_CSV)
    assert len(products) == 8


def test_every_product_has_part_number_and_description():
    """These two fields should never be blank in the real Unihack
    data -- confirmed true across all 1000 rows during manual testing."""
    products = extract_from_csv(TEST_CSV)
    for p in products:
        assert p["Mfg_Part_Num"].strip() != "", "Found a product with blank Mfg_Part_Num"
        assert p["Part_Desc"].strip() != "", "Found a product with blank Part_Desc"


def test_placeholder_brand_values_become_blank():
    """'-- Unbranded --' etc. must be cleaned to '' -- otherwise it
    would look like an actual brand name downstream in enrich.py."""
    products = extract_from_csv(TEST_CSV)
    first = products[0]  # known to have '-- Unbranded --' in the fixture
    assert first["E1_Brand"] == ""
    assert first["Unilog_Brand"] == ""
    assert first["DIB_Brand"] == ""


def test_split_manufacturer_code_with_code():
    name, code = split_manufacturer_code("Freud Inc (2435)")
    assert name == "Freud Inc"
    assert code == "2435"


def test_split_manufacturer_code_without_code():
    name, code = split_manufacturer_code("Some Company With No Code")
    assert name == "Some Company With No Code"
    assert code == ""


def test_normalize_row_adds_split_manufacturer_fields():
    raw = {
        "Mfg_Part_Num": "ABC123",
        "Part_Desc": "Test product",
        "E1_Brand": "",
        "Unilog_Brand": "",
        "DIB_Brand": "",
        "Part_Manuf": "Acme Corp (ACME1)",
    }
    result = normalize_row(raw)
    assert result["Part_Manuf_Name"] == "Acme Corp"
    assert result["Part_Manuf_Code"] == "ACME1"


def test_missing_csv_columns_raise_clear_error():
    """If someone uploads a CSV missing expected columns, this should
    raise a clear ValueError (caught and shown as a 400 in app.py /
    an st.error in streamlit_app.py), not a confusing KeyError."""
    import csv
    import tempfile

    fd, bad_path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(bad_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Only_One_Column"])
        writer.writeheader()
        writer.writerow({"Only_One_Column": "x"})

    try:
        raised = False
        try:
            extract_from_csv(bad_path)
        except ValueError:
            raised = True
        assert raised, "Expected ValueError for a CSV missing required columns"
    finally:
        os.remove(bad_path)


if __name__ == "__main__":
    import traceback

    test_functions = [
        test_extract_from_csv_returns_all_rows,
        test_every_product_has_part_number_and_description,
        test_placeholder_brand_values_become_blank,
        test_split_manufacturer_code_with_code,
        test_split_manufacturer_code_without_code,
        test_normalize_row_adds_split_manufacturer_fields,
        test_missing_csv_columns_raise_clear_error,
    ]

    passed, failed = 0, 0
    for test_fn in test_functions:
        try:
            test_fn()
            print(f"PASS: {test_fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {test_fn.__name__} -- {e}")
            failed += 1
        except Exception:
            print(f"ERROR: {test_fn.__name__}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")