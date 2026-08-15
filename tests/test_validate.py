"""
tests/test_validate.py

Tests unit normalization and manufacturer-name fuzzy matching.
Includes a regression test for a real false-positive bug caught
during manual testing: "Totally Different Company" was wrongly
matched to "3M Company" using a too-permissive scorer/threshold.

Run with:
    pip install pytest --break-system-packages
    pytest tests/test_validate.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from validate import (
    normalize_uom,
    normalize_all_uom_fields,
    fuzzy_match_manufacturer,
    build_manufacturer_reference,
    validate_product,
)


def test_normalize_uom_handles_common_variants():
    assert normalize_uom("in") == "in"
    assert normalize_uom("Inch") == "in"
    assert normalize_uom("INCHES") == "in"
    assert normalize_uom('"') == "in"
    assert normalize_uom("volts") == "V"
    assert normalize_uom("VAC") == "V"
    assert normalize_uom("Pieces") == "pc"


def test_normalize_uom_leaves_unrecognized_values_unchanged():
    """Conservative behavior: don't guess at units we don't recognize."""
    assert normalize_uom("frobnicate") == "frobnicate"


def test_normalize_uom_handles_blank():
    assert normalize_uom("") == ""
    assert normalize_uom("   ") == ""


def test_normalize_all_uom_fields_only_touches_uom_columns():
    product = {
        "ATTRIBUTE_UOM_1": "inches",
        "ATTRIBUTE_LABEL_1": "Width",  # should NOT be touched
        "ATTRIBUTE_VALUE_1": "1/2",    # should NOT be touched
        "ATTRIBUTE_UOM_2": "volts",
    }
    result = normalize_all_uom_fields(product, num_slots=10)
    assert result["ATTRIBUTE_UOM_1"] == "in"
    assert result["ATTRIBUTE_UOM_2"] == "V"
    assert result["ATTRIBUTE_LABEL_1"] == "Width"
    assert result["ATTRIBUTE_VALUE_1"] == "1/2"


def test_fuzzy_match_collapses_near_duplicates():
    reference = ["Freud Inc", "3M Company", "Jam Industrial Supply LLC"]
    assert fuzzy_match_manufacturer("Freud Inc.", reference) == "Freud Inc"
    assert fuzzy_match_manufacturer("FREUD INC", reference) == "Freud Inc"
    assert fuzzy_match_manufacturer("3M Co", reference) == "3M Company"


def test_fuzzy_match_does_not_invent_matches_for_unrelated_names():
    """Regression test: a real bug found during manual testing where
    'Totally Different Company' matched '3M Company' purely because
    both contain the word 'Company'. Never merge two different
    companies just because of shared common words."""
    reference = ["Freud Inc", "3M Company", "Jam Industrial Supply LLC"]
    assert fuzzy_match_manufacturer("Totally Different Company", reference) == "Totally Different Company"
    assert fuzzy_match_manufacturer("Acme Corp", reference) == "Acme Corp"


def test_fuzzy_match_handles_empty_input():
    reference = ["Freud Inc"]
    assert fuzzy_match_manufacturer("", reference) == ""
    assert fuzzy_match_manufacturer("Freud Inc", []) == "Freud Inc"


def test_build_manufacturer_reference_dedupes_and_sorts():
    products = [
        {"Part_Manuf_Name": "Freud Inc"},
        {"Part_Manuf_Name": "Freud Inc"},  # duplicate
        {"Part_Manuf_Name": "3M Company"},
        {"Part_Manuf_Name": ""},  # blank -- should be excluded
    ]
    ref = build_manufacturer_reference(products)
    assert ref == ["3M Company", "Freud Inc"]


def test_validate_product_normalizes_units_and_manufacturer():
    reference = ["Freud Inc"]
    product = {
        "Mfg_Part_Num": "TEST1",
        "MANUFACTURER_NAME": "FREUD INC.",
        "ATTRIBUTE_UOM_1": "inches",
    }
    result = validate_product(product, reference, num_attribute_slots=10)
    assert result["MANUFACTURER_NAME"] == "Freud Inc"
    assert result["ATTRIBUTE_UOM_1"] == "in"


def test_validate_product_records_correction_in_meta_column():
    """When a manufacturer name gets corrected, that should be
    visible in the meta columns, not a silent change."""
    reference = ["Freud Inc"]
    product = {"Mfg_Part_Num": "TEST1", "MANUFACTURER_NAME": "FREUD INC."}
    result = validate_product(product, reference, num_attribute_slots=10)
    assert "MANUFACTURER_NAME_normalized" in result.get("fields_from_llm_lookup", "")


if __name__ == "__main__":
    import traceback

    test_functions = [
        test_normalize_uom_handles_common_variants,
        test_normalize_uom_leaves_unrecognized_values_unchanged,
        test_normalize_uom_handles_blank,
        test_normalize_all_uom_fields_only_touches_uom_columns,
        test_fuzzy_match_collapses_near_duplicates,
        test_fuzzy_match_does_not_invent_matches_for_unrelated_names,
        test_fuzzy_match_handles_empty_input,
        test_build_manufacturer_reference_dedupes_and_sorts,
        test_validate_product_normalizes_units_and_manufacturer,
        test_validate_product_records_correction_in_meta_column,
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