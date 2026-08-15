"""
streamlit_app.py

Simple upload -> enrich -> preview/download UI for the pipeline.

This calls extract.py / enrich.py / writer.py directly (no need for
app.py / FastAPI to be running separately -- Streamlit runs the
pipeline in-process). Run app.py instead if you specifically need an
HTTP API for something else to call.

Run with:
    pip install streamlit --break-system-packages
    streamlit run streamlit_app.py
"""

import os
import tempfile
import time

import pandas as pd
import streamlit as st

from extract import extract_auto, extract_from_text
from enrich import enrich_product, GEMINI_API_KEY
from writer import init_output_csv, append_product_row
from search_fetch import find_verified_source, SEARCH_API_KEY
from validate import build_manufacturer_reference, validate_product
from schema import COLUMNS, NUM_ATTRIBUTE_SLOTS

st.set_page_config(page_title="Unihack Product Enrichment", layout="wide")

st.title("Product Data Enrichment Pipeline")
st.caption("Upload raw product data \u2192 get back a standardized, enriched CSV.")

if not GEMINI_API_KEY:
    st.error(
        "GEMINI_API_KEY not found. Copy .env.example to .env, add your "
        "key, and restart this app."
    )
    st.stop()

# --- Sidebar: run settings ---
st.sidebar.header("Run settings")
limit_mode = st.sidebar.radio(
    "How many products to enrich?",
    ["Quick test (first 10)", "Custom number", "All rows"],
)

custom_limit = None
if limit_mode == "Custom number":
    custom_limit = st.sidebar.number_input(
        "Number of rows", min_value=1, max_value=1000, value=50, step=10
    )


# --- Main: choose input mode ---
input_mode = st.radio(
    "How do you want to provide product data?",
    ["Upload file", "Paste text"],
    horizontal=True,
)

products = None

if input_mode == "Upload file":
    st.session_state.pop("pasted_products", None)  # clear stale text-mode results

    uploaded_file = st.file_uploader(
        "Upload input file", type=["csv", "pdf", "txt", "png", "jpg", "jpeg", "webp"]
    )

    if uploaded_file is not None:
        # Save upload to a temp path, preserving extension so extract_auto
        # can detect the right extractor (csv/pdf/text/image).
        suffix = os.path.splitext(uploaded_file.name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        try:
            products = extract_auto(tmp_path)
        except ValueError as e:
            st.error(f"Could not read this file: {e}")
            st.stop()
        finally:
            os.remove(tmp_path)

else:  # Paste text
    pasted_text = st.text_area(
        "Paste messy product text here (a description, a parts list, "
        "an invoice snippet, etc.)",
        height=200,
        placeholder=(
            "Paste text here"
        ),
    )

    if st.button("Extract products from text"):
        if not pasted_text.strip():
            st.warning("Paste some text first.")
            st.stop()

        with st.spinner("Reading text and pulling out product info..."):
            try:
                extracted = extract_from_text(pasted_text)
            except Exception as e:
                st.error(f"Couldn't extract products from that text: {e}")
                st.stop()

        if not extracted:
            st.warning(
                "No product information found in that text. Try including "
                "a part number and description."
            )
            st.stop()

        # Stored in session_state because a plain local variable would
        # be lost on the next rerun (e.g. when "Run enrichment" is
        # clicked below) -- buttons only return True on the run they
        # were clicked, unlike a file_uploader which persists its file.
        st.session_state["pasted_products"] = extracted

    products = st.session_state.get("pasted_products")

if products is not None:

    st.success(f"Parsed {len(products)} products.")

    # Determine how many to actually process
    if limit_mode == "Quick test (first 10)":
        products_to_run = products[:10]
    elif limit_mode == "Custom number":
        products_to_run = products[: int(custom_limit)]
    else:
        products_to_run = products

    st.write(f"Will enrich **{len(products_to_run)}** products.")

    if st.button("Run enrichment", type="primary"):
        output_path = "data/output/streamlit_output.csv"
        os.makedirs("data/output", exist_ok=True)
        init_output_csv(output_path)

        progress_bar = st.progress(0)
        status_text = st.empty()
        results_placeholder = st.empty()

        succeeded, failed = 0, 0
        errors = []
        start_time = time.time()

        # Reference list for manufacturer-name self-consistency matching --
        # built from this batch's own data (see validate.py docstring for
        # why this isn't the same as Unilog's official LOV list).
        manufacturer_reference = build_manufacturer_reference(products_to_run)

        for i, product in enumerate(products_to_run, 1):
            part_num = product.get("Mfg_Part_Num", "?")
            status_text.text(f"Enriching {i}/{len(products_to_run)}: {part_num}")

            try:
                page_text, source_url = None, None
                if SEARCH_API_KEY:
                    lookup = find_verified_source(
                        product.get("Mfg_Part_Num", ""),
                        product.get("Part_Manuf_Name", ""),
                    )
                    if lookup["verified"]:
                        page_text, source_url = lookup["page_text"], lookup["url"]

                enriched = enrich_product(product, page_text=page_text, source_url=source_url)
                enriched = validate_product(enriched, manufacturer_reference, NUM_ATTRIBUTE_SLOTS)
                append_product_row(output_path, enriched)
                succeeded += 1
            except Exception as e:
                failed += 1
                errors.append({"part_num": part_num, "error": str(e)})

            progress_bar.progress(i / len(products_to_run))

        elapsed = time.time() - start_time
        status_text.text(f"Done in {elapsed:.1f}s.")

        with results_placeholder.container():
            col1, col2, col3 = st.columns(3)
            col1.metric("Succeeded", succeeded)
            col2.metric("Failed", failed)
            col3.metric("Total", len(products_to_run))

            if errors:
                with st.expander(f"View {len(errors)} error(s)"):
                    st.dataframe(pd.DataFrame(errors), use_container_width=True)

        # Preview + download
        if succeeded > 0:
            st.subheader("Preview of enriched output")
            output_df = pd.read_csv(output_path)

            # Show a summary of how filled the output actually is,
            # since a 61-column schema with mostly blanks is expected
            # (see earlier discussion) -- this makes that visible
            # rather than looking like a bug at a glance.
            filled_counts = output_df.notna().sum(axis=1) - (output_df == "").sum(axis=1)
            st.caption(
                f"Average {filled_counts.mean():.0f} / {len(COLUMNS)} "
                f"columns filled per product."
            )

            st.dataframe(output_df, use_container_width=True, height=400)

            with open(output_path, "rb") as f:
                st.download_button(
                    "Download enriched CSV",
                    data=f,
                    file_name="enriched_output.csv",
                    mime="text/csv",
                    type="primary",
                )
elif input_mode == "Upload file":
    pass
else:
    pass