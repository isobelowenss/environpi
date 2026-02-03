import os
import csv
import io
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort, send_from_directory, Response

# API Key for security (Render environment variable or default)
API_KEY = os.environ.get("API_KEY", "table_varnish")

def require_key():
    key = request.headers.get("X-API-Key") or request.args.get("key")
    if key != API_KEY:
        abort(401)

app = Flask(__name__, static_folder=".", static_url_path="")

# --------- In-memory state (Restored to your original structure) ----------
STATE = {
    "command": {"mode": "manual", "dir": "stop", "speed": 50},
    "target": {"lat": "", "lon": ""},
    "route": [],
    "last_seen_pi": "Never",
    "telemetry": {
        "gps": {"lat": 52.0, "lon": 1.0},
        "water": {"tds": 0, "turbidity": 0, "ph": 7.0, "temp": 0.0},
        "depth": {"m": 0.0},
        "birds": {"species": "None", "count": 0},
        "battery": "Unknown",
        "stuck": False,
        "submerged": False,
        "excessive_rocking": False
    }
}

LOGS = {"water": [], "birds": [], "depth": [], "motion": []}

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/clear_all", methods=["POST"])
def clear_all():
    require_key()
    global LOGS
    LOGS = {"water": [], "birds": [], "depth": [], "motion": []}
    return jsonify({"status": "cleared"})

@app.route("/telemetry", methods=["POST"])
def telemetry():
    require_key()
    data = request.get_json(force=True) or {}
    STATE["last_seen_pi"] = datetime.now(timezone.utc).isoformat()

    # Update state fields
    for field in ["battery", "stuck", "submerged", "excessive_rocking"]:
        if field in data: STATE["telemetry"][field] = data[field]

    gps = data.get("gps", {})
    lat, lon = gps.get("lat"), gps.get("lon")
    if lat and lon: STATE["telemetry"]["gps"] = {"lat": lat, "lon": lon}

    ts = datetime.now(timezone.utc).isoformat()

    # Log incoming data for tables/map
    if "water" in data:
        LOGS["water"].append({"ts": ts, "lat": lat, "lon": lon, **data["water"]})
    if "birds" in data:
        LOGS["birds"].append({"ts": ts, "lat": lat, "lon": lon, **data["birds"]})
    if "depth" in data:
        LOGS["depth"].append({"ts": ts, "lat": lat, "lon": lon, "depth_m": data["depth"].get("m")})
    
    return jsonify({"status": "ok"})

@app.route("/status")
def get_status():
    require_key()
    res = dict(STATE["telemetry"])
    res["last_seen_pi"] = STATE["last_seen_pi"]
    return jsonify(res)

@app.route("/rows/<kind>")
def get_rows(kind):
    require_key()
    return jsonify(LOGS.get(kind, []))

@app.route("/manual", methods=["POST"])
def manual():
    require_key(); data = request.get_json(force=True)
    STATE["command"].update({"mode": "manual", "dir": data.get("dir", "stop")})
    return jsonify({"ok": True})

@app.route("/commands")
def get_commands():
    require_key()
    return jsonify({"mode": STATE["command"]["mode"], "manual": STATE["command"]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
