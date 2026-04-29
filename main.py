from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import json
import time

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
    return {"status": "ok", "version": "2.0"}

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.get("/validators")
async def get_validators():
    """Fetch live validator data from Flare P-chain API"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "platform.getCurrentValidators",
        "params": {}
    }
    headers = {"Content-Type": "application/json"}
    
    last_error = None
    async with httpx.AsyncClient(timeout=20) as client:
        for endpoint in P_CHAIN_ENDPOINTS:
            try:
                r = await client.post(endpoint, json=payload, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    validators = data.get("result", {}).get("validators", [])
                    if validators:
                        now = int(time.time())
                        result = []
                        for v in validators:
                            node_id = v.get("nodeID", "")
                            end_time = int(v.get("endTime", 0))
                            start_time = int(v.get("startTime", 0))
                            stake_nflr = int(v.get("stakeAmount", 0))
                            stake_flr = stake_nflr / 1e9
                            
                            # Delegators
                            delegators = v.get("delegators") or []
                            delegated_nflr = sum(int(d.get("stakeAmount", 0)) for d in delegators)
                            delegated_flr = delegated_nflr / 1e9
                            delegator_count = len(delegators)
                            
                            # Fee (delegationFee is in units of 10000ths of a percent)
                            fee_raw = float(v.get("delegationFee", "0"))
                            fee_pct = fee_raw / 10000 if fee_raw > 100 else fee_raw
                            
                            # Uptime (0-1)
                            uptime = float(v.get("uptime", "0"))
                            
                            # Days remaining
                            days_left = max(0, round((end_time - now) / 86400))
                            
                            # Free space: capacity = stake * 15, free = capacity - delegated
                            capacity_flr = stake_flr * 15
                            free_flr = max(0, capacity_flr - delegated_flr)
                            
                            result.append({
                                "nodeId": node_id,
                                "stakeFlr": round(stake_flr, 2),
                                "delegatedFlr": round(delegated_flr, 2),
                                "freeFlr": round(free_flr, 2),
                                "capacityFlr": round(capacity_flr, 2),
                                "delegatorCount": delegator_count,
                                "feePct": round(fee_pct, 2),
                                "uptime": round(uptime * 100, 2),
                                "endTime": end_time,
                                "daysLeft": days_left,
                                "startTime": start_time,
                            })
                        
                        return {
                            "source": "p-chain",
                            "endpoint": endpoint,
                            "count": len(result),
                            "fetchedAt": now,
                            "validators": result
                        }
            except Exception as e:
                last_error = str(e)
                continue
    
    return {"error": f"All endpoints failed: {last_error}", "validators": []}
