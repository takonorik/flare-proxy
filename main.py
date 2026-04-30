from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import re
import time
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

P_CHAIN_ENDPOINTS = [
    "https://flare-api.flare.network/ext/bc/P",
    "https://flare.flare.network/ext/bc/P",
]

@app.get("/")
def root():
    return {"status": "ok", "version": "5.0", "source": "flare.builders + p-chain"}

@app.get("/healthz")
def health():
    return {"status": "ok"}

async def fetch_node_ids(client: httpx.AsyncClient):
    """Fetch full Node IDs from flare.builders (SSR)"""
    url = "https://flare.builders/validators"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = await client.get(url, headers=headers)
    html = r.text
    # Returns full IDs without NodeID- prefix
    node_ids = re.findall(r'NodeID-([A-Za-z0-9]+)', html)
    return list(dict.fromkeys(node_ids))

async def fetch_pchain_validators(client: httpx.AsyncClient):
    """Fetch validator data from Flare P-chain API"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "platform.getCurrentValidators", "params": {}}
    headers = {"Content-Type": "application/json"}
    for endpoint in P_CHAIN_ENDPOINTS:
        try:
            r = await client.post(endpoint, json=payload, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                validators = data.get("result", {}).get("validators", [])
                if validators:
                    return validators
        except Exception:
            continue
    return []

@app.get("/debug")
async def debug():
    """Debug: test P-chain API connectivity and matching"""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        node_ids_task = fetch_node_ids(client)
        pchain_task = fetch_pchain_validators(client)
        node_ids, pchain = await asyncio.gather(node_ids_task, pchain_task, return_exceptions=True)

    if isinstance(node_ids, Exception):
        node_ids = []
    if isinstance(pchain, Exception):
        pchain = []

    # Build pchain map
    pchain_map = {}
    for v in pchain:
        nid = v.get("nodeID", "").replace("NodeID-", "")
        pchain_map[nid] = v

    # Check matches
    matched = []
    unmatched = []
    for nid in node_ids:
        if nid in pchain_map:
            matched.append(nid[:12])
        else:
            unmatched.append(nid[:12])

    return {
        "flare_builders_count": len(node_ids),
        "pchain_count": len(pchain),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "matched_samples": matched[:5],
        "unmatched_samples": unmatched[:5],
        "pchain_sample": list(pchain_map.keys())[0][:12] if pchain_map else "none",
        "builders_sample": node_ids[0][:12] if node_ids else "none",
    }

@app.get("/validators")
async def get_validators():
    now = int(time.time())
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        node_ids_task = fetch_node_ids(client)
        pchain_task = fetch_pchain_validators(client)
        node_ids, pchain_validators = await asyncio.gather(
            node_ids_task, pchain_task, return_exceptions=True
        )

    if isinstance(node_ids, Exception):
        node_ids = []
    if isinstance(pchain_validators, Exception):
        pchain_validators = []

    # Build lookup: full nodeId (without NodeID-) → pchain data
    pchain_map = {}
    for v in pchain_validators:
        nid = v.get("nodeID", "").replace("NodeID-", "")
        pchain_map[nid] = v

    result = []
    for short_id in node_ids:
        pdata = pchain_map.get(short_id, {})
        has_data = bool(pdata)

        # P-chain units (verified via debug3):
        # weight / 1e12 = total node capacity in FLR
        # delegatorWeight / 1e12 = total delegated in FLR
        # free = (weight - delegatorWeight) / 1e12
        w = int(pdata.get("weight", 0))
        dw = int(pdata.get("delegatorWeight", 0))
        capacity_flr = w / 1e12
        delegated_flr = dw / 1e12
        free_flr = max(0, capacity_flr - delegated_flr)
        stake_flr = capacity_flr  # capacity = total node weight
        delegator_count = int(pdata.get("delegatorCount", 0))

        fee_pct = round(float(pdata.get("delegationFee", "0") or "0"), 2)
        # uptime is already in % format (e.g. "99.9933")
        uptime = round(float(pdata.get("uptime", "0") or "0"), 2)
        end_time = int(pdata.get("endTime", 0))
        days_left = max(0, round((end_time - now) / 86400))

        result.append({
            "nodeId": short_id,
            "fullNodeId": "NodeID-" + short_id,
            "stakeFlr": round(stake_flr, 2),
            "delegatedFlr": round(delegated_flr, 2),
            "freeFlr": round(free_flr, 2),
            "delegatorCount": delegator_count,
            "feePct": fee_pct,
            "uptime": uptime,
            "endTime": end_time,
            "daysLeft": days_left,
            "hasPchainData": has_data,
        })

    result.sort(key=lambda x: x["freeFlr"], reverse=True)

    return {
        "source": "flare.builders + p-chain",
        "version": "5.0",
        "fetchedAt": now,
        "count": len(result),
        "pchain_count": len(pchain_validators),
        "matched": sum(1 for r in result if r["hasPchainData"]),
        "validators": result
    }


@app.get("/debug2")
async def debug2():
    """Show raw P-chain data for first validator"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "platform.getCurrentValidators", "params": {}}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(P_CHAIN_ENDPOINTS[0], json=payload, headers={"Content-Type": "application/json"})
        data = r.json()
        validators = data.get("result", {}).get("validators", [])
        if validators:
            # Return first validator's raw keys and values
            v = validators[0]
            return {
                "keys": list(v.keys()),
                "sample": {k: str(v[k])[:50] for k in v.keys() if k != "delegators"},
                "delegator_count": len(v.get("delegators") or []),
                "delegator_sample": (v.get("delegators") or [{}])[0] if v.get("delegators") else {}
            }
    return {"error": "no data"}


@app.get("/debug3")
async def debug3(nodeId: str = "w4tjm1YTWgnw"):
    """Show raw P-chain data for a specific node by prefix"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "platform.getCurrentValidators", "params": {}}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(P_CHAIN_ENDPOINTS[0], json=payload, headers={"Content-Type": "application/json"})
        data = r.json()
        validators = data.get("result", {}).get("validators", [])
        
    for v in validators:
        nid = v.get("nodeID", "").replace("NodeID-", "")
        if nid.startswith(nodeId[:12]):
            w = int(v.get("weight", 0))
            dw = int(v.get("delegatorWeight", 0))
            return {
                "nodeID": v.get("nodeID"),
                "weight_raw": w,
                "delegatorWeight_raw": dw,
                "weight_div1e6": w / 1e6,
                "weight_div1e9": w / 1e9,
                "dw_div1e6": dw / 1e6,
                "dw_div1e9": dw / 1e9,
                "dw_div1e12": dw / 1e12,
                "free_formula1": max(0, w/1e6*5 - dw/1e9),
                "free_formula2": max(0, w/1e9*5 - dw/1e9),
                "free_formula3": max(0, (w*5 - dw) / 1e9),
                "free_formula4": max(0, (w*5 - dw) / 1e6),
                "delegationFee": v.get("delegationFee"),
                "uptime": v.get("uptime"),
                "delegatorCount": v.get("delegatorCount"),
                "endTime": v.get("endTime"),
            }
    return {"error": f"nodeId {nodeId} not found"}
