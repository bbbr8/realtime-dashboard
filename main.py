from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import httpx
from pathlib import Path

app = FastAPI()

# Determine the base path and static directory
base_path = Path(__file__).resolve().parent
static_dir = base_path / "static"

# Mount static directory to serve HTML and assets
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Shared data structure for storing feed results
data_store = {
    "earthquakes": [],
    "weather": {},
    "crypto": {}
}

# Set of connected WebSocket clients
clients = set()

async def fetch_feeds():
    """
    Background task to periodically fetch data from public APIs.
    """
    while True:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Fetch latest earthquakes (past hour)
                eq_resp = await client.get("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson")
                if eq_resp.status_code == 200:
                    eq_json = eq_resp.json()
                    # Extract a simple list of strings: "Magnitude Place"
                    quakes = []
                    for feature in eq_json.get("features", []):
                        mag = feature["properties"].get("mag")
                        place = feature["properties"].get("place")
                        quakes.append(f"M{mag} - {place}")
                    data_store["earthquakes"] = quakes

                # Fetch current weather for Salt Lake City
                weather_resp = await client.get("https://wttr.in/Salt%20Lake%20City?format=j1")
                if weather_resp.status_code == 200:
                    w_json = weather_resp.json()
                    current = w_json["current_condition"][0]
                    data_store["weather"] = {
                        "temp_F": current.get("temp_F"),
                        "description": current["weatherDesc"][0]["value"]
                    }

                # Fetch bitcoin price in USD from Coindesk
                crypto_resp = await client.get("https://api.coindesk.com/v1/bpi/currentprice/USD.json")
                if crypto_resp.status_code == 200:
                    c_json = crypto_resp.json()
                    usd_info = c_json["bpi"]["USD"]
                    data_store["crypto"] = {
                        "BTC_USD": usd_info.get("rate")
                    }
        except Exception as e:
            print("Error fetching feeds:", e)

        # Broadcast the updated data to all connected clients
        for ws in list(clients):
            try:
                await ws.send_json(data_store)
            except Exception:
                clients.remove(ws)

        # Wait 60 seconds before the next update
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    # Launch the background task on startup
    asyncio.create_task(fetch_feeds())

@app.get("/")
async def root():
    """
    Serve the main dashboard HTML.
    """
    index_file = static_dir / "index.html"
    html = index_file.read_text()
    return HTMLResponse(html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for pushing real-time updates to the client.
    """
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            # Keep the connection alive; messages from client are ignored
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.remove(websocket)
