import os
import csv
import io
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort, send_from_directory, Response

# API Key for security (Render environment variable or default)
API_KEY = os.environ.get("API_KEY", "table_varnish")

def _has_key() -> bool:
    return (
        request.headers.get("X-API-Key") == API_KEY
        or request.args.get("key") == API_KEY
    )

def require_key():
    if not _has_key():
        abort(401)

app = Flask(__name__, static_folder=".", static_url_path="")

# --------- In-memory state ----------
INITIAL_STATE = {
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

STATE = dict(INITIAL_STATE)
LOGS = {"water": [], "birds": [], "depth": [], "motion": []}

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/clear_all", methods=["POST"])
def clear_all():
    require_key()
    global LOGS, STATE
    LOGS = {"water": [], "birds": [], "depth": [], "motion": []}
    STATE = dict(INITIAL_STATE)
    return jsonify({"status": "cleared"})

@app.route("/telemetry", methods=["POST"])
def telemetry():
    require_key()
    data = request.get_json(force=True) or {}
    STATE["last_seen_pi"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for field in ["battery", "stuck", "submerged", "excessive_rocking"]:
        if field in data:
            STATE["telemetry"][field] = data[field]

    gps = data.get("gps", STATE["telemetry"].get("gps", {}))
    lat, lon = gps.get("lat"), gps.get("lon")
    STATE["telemetry"]["gps"] = {"lat": lat, "lon": lon}

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if "water" in data:
        LOGS["water"].append({"ts": ts, "lat": lat, "lon": lon, **data["water"]})
    if "birds" in data:
        LOGS["birds"].append({"ts": ts, "lat": lat, "lon": lon, **data["birds"]})
    if "depth" in data:
        depth_val = data["depth"].get("m") if isinstance(data["depth"], dict) else data["depth"]
        LOGS["depth"].append({"ts": ts, "lat": lat, "lon": lon, "depth_m": depth_val})
    
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
    return jsonify(LOGS.get(kind, [])[-100:])

@app.route("/manual", methods=["POST"])
def manual():
    require_key(); data = request.get_json(force=True)
    STATE["command"].update({"mode": "manual", "dir": data.get("dir", "stop")})
    return jsonify({"ok": True})

@app.route("/commands")
def get_commands():
    require_key()
    return jsonify({"mode": STATE["command"]["mode"], "manual": STATE["command"], "route": STATE["route"]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
