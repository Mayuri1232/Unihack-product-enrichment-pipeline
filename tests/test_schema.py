"""
tests/test_schema.py

Checks the integrity of the output schema itself -- catches mistakes
like duplicate column names or a broken attribute-slot count before
they cause confusing bugs downstream in writer.py or enrich.py.

Run with:
    pip install pytest --break-system-packages
    pytest tests/test_schema.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema import (
    COLUMNS,
    INPUT_COLUMNS,
    ATTRIBUTE_COLUMNS,
    NUM_ATTRIBUTE_SLOTS,
    IDENTIFIER_COLUMNS,
    CLASSIFICATION_COLUMNS,
    BRAND_COLUMNS,
    DESCRIPTION_COLUMNS,
    COMPLIANCE_COLUMNS,
    MEDIA_COLUMNS,
    META_COLUMNS,
)


def test_no_duplicate_columns():
    """A duplicate column name would silently overwrite data in the
    output CSV -- this must never happen."""
    assert len(COLUMNS) == len(set(COLUMNS)), (
        f"Found duplicate column names: "
        f"{[c for c in COLUMNS if COLUMNS.count(c) > 1]}"
    )


def test_all_group_columns_are_in_full_list():
    """Every column from every group must actually appear in the
    final COLUMNS list -- catches a group being forgotten when
    COLUMNS is assembled."""
    all_groups = (
        IDENTIFIER_COLUMNS
        + CLASSIFICATION_COLUMNS
        + BRAND_COLUMNS
        + DESCRIPTION_COLUMNS
        + ATTRIBUTE_COLUMNS
        + COMPLIANCE_COLUMNS
        + MEDIA_COLUMNS
        + META_COLUMNS
    )
    for col in all_groups:
        assert col in COLUMNS, f"{col} is defined in a group but missing from COLUMNS"


def test_attribute_columns_match_slot_count():
    """ATTRIBUTE_COLUMNS should have exactly 3 columns (LABEL/VALUE/UOM)
    per slot -- if NUM_ATTRIBUTE_SLOTS changes, this should scale
    automatically without manual editing elsewhere."""
    expected = NUM_ATTRIBUTE_SLOTS * 3
    assert len(ATTRIBUTE_COLUMNS) == expected, (
        f"Expected {expected} attribute columns for "
        f"{NUM_ATTRIBUTE_SLOTS} slots, got {len(ATTRIBUTE_COLUMNS)}"
    )


def test_attribute_slot_naming_pattern():
    """Each attribute slot must have exactly LABEL, VALUE, UOM --
    enrich.py's prompt relies on this exact naming pattern."""
    for i in range(1, NUM_ATTRIBUTE_SLOTS + 1):
        for suffix in ("LABEL", "VALUE", "UOM"):
            col = f"ATTRIBUTE_{suffix}_{i}"
            assert col in ATTRIBUTE_COLUMNS, f"Missing expected column: {col}"


def test_input_columns_match_known_unihack_format():
    """The 6 input columns must match exactly what's in Unilog's raw
    CSV -- if this test breaks, extract_from_csv's column-presence
    check will also break against real input data."""
    expected = {
        "Mfg_Part_Num",
        "Part_Desc",
        "E1_Brand",
        "Unilog_Brand",
        "DIB_Brand",
        "Part_Manuf",
    }
    assert set(INPUT_COLUMNS) == expected


def test_no_empty_column_names():
    """An empty string as a column name would break the CSV header silently."""
    for col in COLUMNS:
        assert col.strip() != "", "Found an empty/whitespace-only column name"


if __name__ == "__main__":
    # Allow running directly with `python tests/test_schema.py` as a
    # fallback if pytest isn't installed -- runs every test_* function
    # and reports pass/fail without needing the pytest package.
    import traceback

    test_functions = [
        test_no_duplicate_columns,
        test_all_group_columns_are_in_full_list,
        test_attribute_columns_match_slot_count,
        test_attribute_slot_naming_pattern,
        test_input_columns_match_known_unihack_format,
        test_no_empty_column_names,
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