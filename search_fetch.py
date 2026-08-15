"""
search_fetch.py

Given a product's part number + manufacturer name, find the
manufacturer's own product page, fetch it, and verify the part number
actually appears on that page before trusting it as a source.

Design choices (from earlier discussion):
- Search query anchors on the part number FIRST, brand name second --
  the part number is the near-unique key; the brand is a tiebreaker,
  not the primary filter. This avoids the "Whirlpool vs Samsung"
  confusion since we're not searching by category/brand alone.
- No hardcoded search provider. search_web() below is a thin wrapper
  you plug a real API into (Google Custom Search / Serper / Bing /
  SerpAPI -- whichever you have a key for). Everything downstream
  (fetch, verify) works the same regardless of provider.
- verify_part_number_on_page() is the safeguard discussed earlier:
  never let Gemini extract from a page unless the exact part number
  string is actually present in that page's text. If it's not there,
  the result is discarded rather than silently trusted.
"""

import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present

SEARCH_API_KEY = os.environ.get("SEARCH_API_KEY")


# NOTE: plug in a real search API here. Left as a stub so the rest of
# the pipeline (extract -> search_fetch -> enrich -> writer) can be
# wired and tested end-to-end even before a search API key exists --
# search_web() can be swapped for a real implementation with zero
# changes needed anywhere else in the pipeline.
def search_web(query: str, num_results: int = 5) -> list[str]:
    """Return a list of candidate URLs for the given query, using the
    Serper.dev Google Search API.

    Get a free-tier key at https://serper.dev, then add it to .env as:
        SEARCH_API_KEY=your_key_here
    """
    if not SEARCH_API_KEY:
        raise NotImplementedError(
            "search_web() has no SEARCH_API_KEY set (checked .env and "
            "environment). Sign up for a free key at https://serper.dev "
            "and add SEARCH_API_KEY to .env."
        )

    response = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": SEARCH_API_KEY, "Content-Type": "application/json"},
        json={"q": query, "num": num_results},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    return [r["link"] for r in data.get("organic", []) if "link" in r]


def build_search_query(part_number: str, manufacturer_name: str) -> str:
    """Build the search query anchored on part number first.

    e.g. build_search_query("WDTS7024RZ", "Whirlpool")
         -> '"WDTS7024RZ" Whirlpool'
    """
    part_number = part_number.strip()
    manufacturer_name = manufacturer_name.strip()
    if manufacturer_name:
        return f'"{part_number}" {manufacturer_name}'
    return f'"{part_number}"'


def fetch_page_text(url: str, timeout: int = 10) -> str:
    """Fetch a URL and return its visible text content.

    Uses a simple tag-strip rather than a full HTML parser dependency,
    good enough for the verify-before-extract text search below. If
    BeautifulSoup is available in the environment, swap this for
    proper parsing to get cleaner text for the Gemini extraction step.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Unihack product enrichment bot)"}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()

    text = response.text
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def verify_part_number_on_page(part_number: str, page_text: str) -> bool:
    """Check the part number literally appears in the fetched page text.

    This is the core safeguard: never extract from a page unless the
    exact part number string is present. Case-insensitive, and
    tolerant of hyphen/space variants since manufacturers format part
    numbers inconsistently (e.g. "WDTS-7024RZ" vs "WDTS7024RZ").
    """
    if not part_number or not page_text:
        return False

    normalized_part = re.sub(r"[\s\-]", "", part_number).lower()
    normalized_page = re.sub(r"[\s\-]", "", page_text).lower()
    return normalized_part in normalized_page


def find_verified_source(part_number: str, manufacturer_name: str,
                          max_candidates: int = 5) -> dict:
    """Full search -> fetch -> verify flow for one product.

    Returns a dict:
        {
            "verified": bool,
            "url": str or None,       # the URL that passed verification
            "page_text": str or None, # fetched text, only if verified
            "candidates_tried": int,
        }

    Tries each search result in order and stops at the first one that
    verifies. If none verify, returns verified=False so the caller
    (enrich.py) knows to skip lookup-grounded fields for this product
    rather than guessing.
    """
    query = build_search_query(part_number, manufacturer_name)

    try:
        candidate_urls = search_web(query, num_results=max_candidates)
    except NotImplementedError:
        raise
    except Exception as e:
        print(f"[search_fetch] search failed for {query!r}: {e}")
        return {"verified": False, "url": None, "page_text": None, "candidates_tried": 0}

    tried = 0
    for url in candidate_urls:
        tried += 1
        try:
            page_text = fetch_page_text(url)
        except Exception as e:
            print(f"[search_fetch] fetch failed for {url}: {e}")
            continue

        if verify_part_number_on_page(part_number, page_text):
            return {
                "verified": True,
                "url": url,
                "page_text": page_text,
                "candidates_tried": tried,
            }
        else:
            print(f"[search_fetch] part number not found on {url}, trying next candidate")

    return {"verified": False, "url": None, "page_text": None, "candidates_tried": tried}


if __name__ == "__main__":
    # Offline unit tests for the pieces that don't need a live API key.
    # (find_verified_source needs search_web() implemented -- test that
    # separately once a search API key is wired in.)

    print("Testing build_search_query():")
    q1 = build_search_query("WDTS7024RZ", "Whirlpool")
    print(f"  {q1!r}")
    assert q1 == '"WDTS7024RZ" Whirlpool'

    q2 = build_search_query("PDSH4816AF", "")
    print(f"  {q2!r}")
    assert q2 == '"PDSH4816AF"'
    print("  OK\n")

    print("Testing verify_part_number_on_page():")
    page = "The Whirlpool WDTS7024RZ dishwasher features a 3rd rack..."
    assert verify_part_number_on_page("WDTS7024RZ", page) is True
    assert verify_part_number_on_page("wdts7024rz", page) is True  # case-insensitive
    assert verify_part_number_on_page("WDTS-7024-RZ", page) is True  # hyphen-tolerant
    assert verify_part_number_on_page("SOMETHING-ELSE", page) is False
    assert verify_part_number_on_page("", page) is False
    assert verify_part_number_on_page("WDTS7024RZ", "") is False
    print("  OK\n")

    print("All offline tests passed.")
    print("\nNote: search_web() is still a stub -- plug in a real search")
    print("API (Serper/Google Custom Search/Bing/SerpAPI) before running")
    print("find_verified_source() end-to-end.")