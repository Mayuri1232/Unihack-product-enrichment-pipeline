"""
list_models.py

Diagnostic script -- run this once to see exactly which models your
GEMINI_API_KEY has access to. Model availability has been changing
fast in 2026 (new keys losing access to older models), so rather than
guess model names, ask the API directly.

Usage:
    python list_models.py
"""

import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("GEMINI_API_KEY not found -- check your .env file.")
    raise SystemExit(1)

client = genai.Client(api_key=api_key)

print("Models available to your API key that support generate_content:\n")
for model in client.models.list():
    actions = getattr(model, "supported_actions", None) or getattr(model, "supported_generation_methods", None) or []
    if any("generateContent" in str(a) or "generate_content" in str(a) for a in actions) or not actions:
        print(f"  {model.name}")