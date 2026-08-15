"""
validate.py

Post-enrichment validation: unit normalization + manufacturer-name
fuzzy-matching.

IMPORTANT SCOPE NOTE (be honest about this, don't oversell it):
Unilog's actual official LOV / brand master list was never located
(the referenced Excel file in the solution guide could not be found).
This module does NOT validate against Unilog's approved values --
that's still not possible without that file.

What this DOES do, which is a real improvement over raw LLM output:
  1. UNIT NORMALIZATION -- collapse variant unit strings ("in", "inch",
     "inches", "IN") into one canonical form, so ATTRIBUTE_UOM columns
     are consistent across the output CSV instead of whatever string
     Gemini happened to generate for each product.
  2. MANUFACTURER SELF-CONSISTENCY MATCHING -- fuzzy-match each
     enriched MANUFACTURER_NAME against the set of manufacturer names
     seen elsewhere in THIS dataset, so "Freud Inc", "Freud", and
     "FREUD INC." collapse to one consistent spelling rather than
     being treated as three different manufacturers.

Neither of these requires Unilog's missing file -- both work purely
from internal consistency within the data you already have.
"""

from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# 1. Unit normalization
# ---------------------------------------------------------------------------

# Maps any recognized variant -> one canonical form.
# Keys are lowercased for matching; canonical values are what gets written.
UOM_CANONICAL_MAP = {
    # length
    "in": "in", "inch": "in", "inches": "in", "\"": "in",
    "ft": "ft", "feet": "ft", "foot": "ft",
    "mm": "mm", "millimeter": "mm", "millimeters": "mm", "millimetre": "mm",
    "cm": "cm", "centimeter": "cm", "centimeters": "cm",
    "m": "m", "meter": "m", "meters": "m", "metre": "m",
    # weight
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gram": "g", "grams": "g",
    # electrical
    "v": "V", "volt": "V", "volts": "V", "vac": "V", "vdc": "V",
    "a": "A", "amp": "A", "amps": "A", "ampere": "A", "amperes": "A",
    "w": "W", "watt": "W", "watts": "W",
    "hz": "Hz", "hertz": "Hz",
    # count / packaging
    "pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc",
    "ea": "ea", "each": "ea",
    "pk": "pk", "pack": "pk", "packs": "pk",
    "bx": "bx", "box": "bx", "boxes": "bx",
    "set": "set", "sets": "set",
    # abrasive grit (not a real "unit" but appears in UOM slots often)
    "grit": "grit",
}


def normalize_uom(raw_value: str) -> str:
    """Normalize a single UOM string to its canonical form.

    Unrecognized values are returned unchanged (stripped) -- this is
    deliberately conservative: we only normalize units we're
    confident about, rather than guessing at unfamiliar ones.
    """
    if not raw_value or not raw_value.strip():
        return ""
    key = raw_value.strip().lower().rstrip(".")
    return UOM_CANONICAL_MAP.get(key, raw_value.strip())


def normalize_all_uom_fields(product: dict, num_slots: int) -> dict:
    """Apply normalize_uom() to every ATTRIBUTE_UOM_N field in a
    product dict (in place-style -- returns a new dict, doesn't
    mutate the input)."""
    result = dict(product)
    for i in range(1, num_slots + 1):
        key = f"ATTRIBUTE_UOM_{i}"
        if key in result:
            result[key] = normalize_uom(result[key])
    return result


# ---------------------------------------------------------------------------
# 2. Manufacturer-name self-consistency fuzzy matching
# ---------------------------------------------------------------------------

def build_manufacturer_reference(products: list[dict], field: str = "Part_Manuf_Name") -> list[str]:
    """Build the set of distinct manufacturer/distributor names seen
    across the whole input dataset (from extract.py's normalized
    products, using Part_Manuf_Name). This becomes the reference list
    every enriched product's MANUFACTURER_NAME is matched against --
    NOT an official Unilog list, just internal self-consistency.
    """
    names = {p.get(field, "").strip() for p in products if p.get(field, "").strip()}
    return sorted(names)


def fuzzy_match_manufacturer(name: str, reference_list: list[str],
                              threshold: int = 90) -> str:
    """Match `name` against the reference list. If a close match
    (score >= threshold) exists, return the reference list's version
    (the canonical spelling) instead -- collapsing near-duplicates
    like 'Freud Inc' / 'FREUD INC.' / 'Freud' into one consistent
    string. If no close match is found, the original name is
    returned unchanged (never invents a manufacturer that isn't
    actually in the reference list).

    Uses WRatio (rapidfuzz's weighted combination of several
    comparison strategies -- handles case, word order, and partial
    containment). threshold=90 is intentionally strict: a lower
    threshold (e.g. partial_ratio alone) produces false positives
    like matching "Totally Different Company" to "3M Company" purely
    because both contain the word "Company" -- better to leave a
    name unmatched than to wrongly merge two different companies.
    """
    if not name or not name.strip() or not reference_list:
        return name

    best_name, best_score = None, 0
    for candidate in reference_list:
        score = fuzz.WRatio(name, candidate, processor=str.lower)
        if score > best_score:
            best_name, best_score = candidate, score

    if best_name is not None and best_score >= threshold:
        return best_name
    return name


def validate_product(product: dict, manufacturer_reference: list[str],
                      num_attribute_slots: int) -> dict:
    """Apply both validation steps to one enriched product dict.
    Call this after enrich_product() and before writer.append_product_row().
    """
    result = normalize_all_uom_fields(product, num_attribute_slots)

    for field in ("MANUFACTURER_NAME", "BRAND_NAME"):
        if result.get(field):
            matched = fuzzy_match_manufacturer(result[field], manufacturer_reference)
            if matched != result[field]:
                # Record that a correction happened, for transparency --
                # visible in the meta columns rather than silently changed.
                note = result.get("fields_from_llm_lookup", "")
                result["fields_from_llm_lookup"] = (
                    note + f",{field}_normalized" if note else f"{field}_normalized"
                )
            result[field] = matched

    return result


if __name__ == "__main__":
    # Offline tests -- no API keys needed for either validation step.
    print("Testing normalize_uom():")
    tests = [
        ("in", "in"), ("Inch", "in"), ("INCHES", "in"), ('"', "in"),
        ("V", "V"), ("volts", "V"), ("VAC", "V"),
        ("pc", "pc"), ("Pieces", "pc"), ("pcs", "pc"),
        ("unknown_unit_xyz", "unknown_unit_xyz"),  # unrecognized -> unchanged
        ("", ""),
    ]
    for raw, expected in tests:
        result = normalize_uom(raw)
        status = "OK" if result == expected else "FAIL"
        print(f"  [{status}] normalize_uom({raw!r}) = {result!r} (expected {expected!r})")

    print("\nTesting fuzzy_match_manufacturer():")
    reference = ["Freud Inc", "3M Company", "Jam Industrial Supply LLC"]
    fuzzy_tests = [
        ("Freud Inc.", "Freud Inc"),
        ("FREUD INC", "Freud Inc"),
        ("3M Co", "3M Company"),
        ("Totally Different Company", "Totally Different Company"),  # no match -> unchanged
        ("Acme Corp", "Acme Corp"),  # another clearly-unrelated name -> unchanged
    ]
    for raw, expected in fuzzy_tests:
        result = fuzzy_match_manufacturer(raw, reference)
        status = "OK" if result == expected else "FAIL"
        print(f"  [{status}] fuzzy_match_manufacturer({raw!r}) = {result!r} (expected {expected!r})")

    print("\nAll offline checks complete.")