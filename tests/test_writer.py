"""
tests/test_writer.py

Checks that writer.py correctly handles the cases discussed earlier:
missing fields becoming blank (not crashing), unknown/typo'd keys
being dropped with a warning rather than corrupting the row, and
column order always matching schema.COLUMNS exactly.

Run with:
    pip install pytest --break-system-packages
    pytest tests/test_writer.py -v
"""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema import COLUMNS
from writer import init_output_csv, append_product_row, write_all_products


def _temp_csv_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    os.remove(path)  # writer.py should be able to create it fresh
    return path


def test_init_creates_header_only():
    """init_output_csv should create a file with just the header row,
    no data rows -- this is what /enrich in app.py relies on before
    appending rows one by one."""
    path = _temp_csv_path()
    init_output_csv(path)

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    assert len(rows) == 1, "Expected exactly one row (the header)"
    assert rows[0] == COLUMNS, "Header row doesn't match schema.COLUMNS exactly"

    os.remove(path)


def test_missing_fields_become_blank_not_error():
    """A product dict missing most fields should NOT raise -- missing
    data must become '' in the row, matching the 'leave blank rather
    than guess' behavior discussed for enrich.py."""
    path = _temp_csv_path()
    init_output_csv(path)

    sparse_product = {"Mfg_Part_Num": "TEST001"}
    append_product_row(path, sparse_product)  # should not raise

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader)

    assert row["Mfg_Part_Num"] == "TEST001"
    # Every other column should exist and be blank, not missing
    for col in COLUMNS:
        if col != "Mfg_Part_Num":
            assert row[col] == "", f"Expected '{col}' to be blank, got {row[col]!r}"

    os.remove(path)


def test_unknown_keys_are_dropped_not_written():
    """A key that isn't part of the schema (e.g. a typo in enrich.py)
    should be silently dropped from the row rather than corrupting the
    CSV structure -- writer.py prints a warning but must not crash."""
    path = _temp_csv_path()
    init_output_csv(path)

    product_with_typo = {
        "Mfg_Part_Num": "TEST002",
        "THIS_COLUMN_DOES_NOT_EXIST": "should be dropped",
    }
    append_product_row(path, product_with_typo)  # should not raise

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert "THIS_COLUMN_DOES_NOT_EXIST" not in reader.fieldnames
        row = next(reader)
        assert row["Mfg_Part_Num"] == "TEST002"

    os.remove(path)


def test_column_order_always_matches_schema():
    """The CSV header order must always exactly match schema.COLUMNS --
    if this drifts, comparing output against Unilog's expected-format
    file by column position would silently misalign."""
    path = _temp_csv_path()
    write_all_products(path, [{"Mfg_Part_Num": "A"}, {"Mfg_Part_Num": "B"}])

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)

    assert header == COLUMNS

    os.remove(path)


def test_write_all_products_row_count_matches_input():
    """Writing N products should produce exactly N data rows (plus
    the header) -- guards against accidentally dropping or duplicating
    rows during a batch run."""
    path = _temp_csv_path()
    fake_products = [{"Mfg_Part_Num": f"P{i}"} for i in range(5)]
    write_all_products(path, fake_products)

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 5
    assert [r["Mfg_Part_Num"] for r in rows] == ["P0", "P1", "P2", "P3", "P4"]

    os.remove(path)


if __name__ == "__main__":
    import traceback

    test_functions = [
        test_init_creates_header_only,
        test_missing_fields_become_blank_not_error,
        test_unknown_keys_are_dropped_not_written,
        test_column_order_always_matches_schema,
        test_write_all_products_row_count_matches_input,
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