# Product Data Enrichment Pipeline

An AI-powered product data enrichment pipeline for industrial and B2B commerce catalogs. Given minimal raw input — a part number, a short description, and a distributor name — the system produces a standardized, commerce-ready record: category classification, structured attributes, multiple description formats, and (when a search API key is configured) manufacturer-verified specification data.

Built for the Unihack "Product Intelligence" challenge, sponsored by Unilog.

## Highlights

- **Multi-format input** — CSV, PDF, pasted free text, and images all accepted, each routed through the right extractor into one shared schema.
- **Grounded, not guessed** — every enriched field traces back to either the source text or a verified manufacturer page. Nothing is invented to fill a gap; unsupported fields are left honestly blank.
- **Verify-before-extract safeguard** — a manufacturer page is only trusted once the exact part number is confirmed present on it, eliminating brand-mismatch risk from naive web scraping.
- **Built-in data validation** — unit strings (e.g. "Inch" / "INCHES" / `"`) are normalized to one canonical form, and manufacturer name variants (e.g. "Freud Inc." / "FREUD INC") are matched and deduplicated via fuzzy string matching.
- **Focused output schema** — ~61 columns scoped from Unilog's own expected-output example, instead of forcing all 252 template columns.
- **Fully tested** — automated test suite covering schema integrity, extraction, writing, and validation logic.
- **Two interfaces** — a Streamlit UI for interactive use, and a FastAPI backend for programmatic access.

## Architecture

```
Input (CSV / PDF / text / image)
        │
        ▼
   extract.py           normalize raw input into 6 base fields
        │
        ▼
 search_fetch.py         find + verify a manufacturer product page
        │                (skipped gracefully if no search key configured)
        ▼
   enrich.py             Gemini: classify, extract attributes, generate descriptions
        │
        ▼
  validate.py            normalize units, match manufacturer name variants
        │
        ▼
   writer.py             write schema-ordered row to output CSV
```

Each stage hands off a clean, typed structure to the next. Extraction never depends on search succeeding, and enrichment gracefully skips lookup-grounded fields when no verified source page is found.

## Project structure

```
.
├── schema.py            # single source of truth for the output column schema
├── extract.py            # input parsing: CSV / PDF / text / image → 6 base fields
├── search_fetch.py        # web search + fetch + part-number verification
├── enrich.py               # Gemini-based classification, extraction, description generation
├── validate.py              # unit normalization + manufacturer-name fuzzy matching
├── writer.py                 # schema-ordered CSV writing
├── app.py                     # FastAPI backend
├── streamlit_app.py            # Streamlit UI
├── list_models.py               # diagnostic: lists Gemini models available to your API key
├── data/
│   ├── input/                    # input CSVs (production + samples)
│   └── output/                    # generated output CSVs
├── tests/                          # pytest suite
├── .env.example                     # required environment variables (copy to .env)
└── requirements.txt
```

## Setup

```bash
git clone <your-repo-url>
cd <repo-folder>

pip install -r requirements.txt
# or individually:
pip install google-genai python-dotenv requests pdfplumber fastapi uvicorn python-multipart streamlit pandas rapidfuzz pytest

cp .env.example .env
# open .env and add your GEMINI_API_KEY
# (optional) add SEARCH_API_KEY from https://serper.dev to enable manufacturer lookup
```

## Running

**Streamlit UI (recommended for demo/testing):**
```bash
streamlit run streamlit_app.py
```
Upload a file or paste text, choose how many products to enrich, and download the resulting CSV.

**FastAPI backend:**
```bash
python app.py
```
Then open `http://127.0.0.1:8000/docs` for the interactive API explorer.

**Command line (quick single-product or batch test):**
```bash
python enrich.py            # enrich the first product from data/input/sample_input.csv
python enrich.py 10         # enrich the first 10 products
python enrich.py all        # enrich the full input file
```

## Tests

```bash
pytest tests/ -v
```

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini API key — used for all classification/extraction/generation calls |
| `SEARCH_API_KEY` | No | Serper.dev API key — enables verified manufacturer page lookup. Pipeline runs correctly without it; lookup-grounded fields are left blank instead. |

## Scope notes

- The output schema is a deliberately reduced subset (~61 columns) of Unilog's full 252-column delivery format, scoped from the fields that were actually populated in Unilog's own example output row.
- Manufacturer-name matching validates *internal consistency* within the input dataset — it is not validated against Unilog's official approved brand/LOV list, as that reference file was not available during development.

## Future development

- Cache verified manufacturer lookups to reduce repeat search cost
- Confidence-tiered output distinguishing directly-extracted fields from inferred/classified ones
- Dynamic (non-fixed-slot) attribute handling for categories with many specifications
- Parallelized enrichment for full-catalog throughput
- Direct integration with an official approved lookup list, once available
