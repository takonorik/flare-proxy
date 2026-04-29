from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import re
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "version": "3.0", "source": "flare.builders"}

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.get("/validators")
async def get_validators():
    """Fetch live validator data from flare.builders (SSR page)"""
    url = "https://flare.builders/validators"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        html = r.text

    # Extract NodeIDs from the SSR HTML
    # Pattern: NodeID-XXXX appears in the rendered HTML
    node_ids = re.findall(r'NodeID-([A-Za-z0-9]+)', html)
    node_ids = list(dict.fromkeys(node_ids))  # dedupe preserving order

    # Also try to extract structured data from JSON-LD or __NEXT_DATA__
    next_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    
    result = {
        "source": "flare.builders",
        "fetchedAt": int(time.time()),
        "html_length": len(html),
        "node_ids": node_ids,
        "node_count": len(node_ids),
        "has_next_data": next_data is not None,
    }

    if next_data:
        import json
        try:
            data = json.loads(next_data.group(1))
            result["next_data_keys"] = list(data.get("props", {}).get("pageProps", {}).keys())
            # Try to get validator data
            page_props = data.get("props", {}).get("pageProps", {})
            validators = page_props.get("validators", page_props.get("data", None))
            if validators:
                result["validators"] = validators
        except Exception as e:
            result["next_data_error"] = str(e)

    return result
