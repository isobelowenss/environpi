import os
import csv
import io
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort, send_from_directory, Response

# API Key for security (Render environment variable or default)
API_KEY = os.environ.get("API_KEY", "table_varnish")

def _has_key() -> bool:
    # Supports header for Pi/AJAX and URL param for CSV downloads
    return (
        request.headers.get("X-API-Key") == API_KEY
        or request.args.get("key") == API_KEY
    )

def require_key():
    if not _has_key():
        abort(401)

app = Flask(__name__, static_folder=".", static_url_path="")

# --------- In-memory state ----------
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
        "excessive_rocking": False  # New Alert
    }
}

# Rolling logs for tables
MAX_ROWS = 2000
LOGS = {
    "water": [],
    "birds": [],
    "depth": [],
    "motion": []  # New log for accelerometer data
}

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def append_log(kind: str, row: dict):
    if kind in LOGS:
        LOGS[kind].append(row)
        if len(LOGS[kind]) > MAX_ROWS:
            LOGS[kind].pop(0)

def to_float(x):
    try: return float(x)
    except (TypeError, ValueError): return None

# --------- Routes ----------

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/telemetry", methods=["POST"])
def telemetry():
    require_key()
    data = request.get_json(force=True) or {}

    # Update Pi Heartbeat
    STATE["last_seen_pi"] = now_iso()

    # Merge basic status fields
    for field in ["battery", "stuck", "submerged", "excessive_rocking"]:
        if field in data:
            STATE["telemetry"][field] = data[field]

    # Process GPS
    gps = data.get("gps", STATE["telemetry"].get("gps", {}))
    lat, lon = to_float(gps.get("lat")), to_float(gps.get("lon"))
    STATE["telemetry"]["gps"] = {"lat": lat, "lon": lon}

    ts = now_iso()

    # 1. Water Quality Log
    w = data.get("water")
    if isinstance(w, dict):
        row = {"ts": ts, "lat": lat, "lon": lon, **w}
        append_log("water", row)
        STATE["telemetry"]["water"] = w

    # 2. Bird Detection Log
    b = data.get("birds")
    if isinstance(b, dict):
        row = {"ts": ts, "lat": lat, "lon": lon, **b}
        append_log("birds", row)
        STATE["telemetry"]["birds"] = b

    # 3. Depth Log
    d = data.get("depth")
    depth_val = to_float(d.get("m") if isinstance(d, dict) else d)
    if depth_val is not None:
        append_log("depth", {"ts": ts, "lat": lat, "lon": lon, "depth_m": depth_val})
        STATE["telemetry"]["depth"] = {"m": depth_val}

    # 4. Accelerometer/Motion Log (New)
    acc = data.get("accel")
    if isinstance(acc, dict):
        append_log("motion", {"ts": ts, "lat": lat, "lon": lon, **acc})

    return jsonify({"status": "ok", "time": ts})

@app.route("/status", methods=["GET"])
def get_status():
    require_key()
    # Combine telemetry with the last seen timestamp for the UI
    response = dict(STATE["telemetry"])
    response["last_seen_pi"] = STATE["last_seen_pi"]
    return jsonify(response)

@app.route("/rows/<kind>", methods=["GET"])
def get_rows(kind):
    require_key()
    if kind not in LOGS: abort(404)
    return jsonify(LOGS[kind][-50:])

@app.route("/download/<kind>.csv", methods=["GET"])
def download_csv(kind):
    require_key()
    if kind not in LOGS: abort(404)

    headers_map = {
        "water": ["ts", "lat", "lon", "tds", "turbidity", "ph", "temp"],
        "birds": ["ts", "lat", "lon", "species", "count"],
        "depth": ["ts", "lat", "lon", "depth_m"],
        "motion": ["ts", "lat", "lon", "x", "y", "z"]
    }

    fieldnames = headers_map.get(kind, ["ts"])
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in LOGS[kind]:
        writer.writerow({k: r.get(k, "") for k in fieldnames})

    return Response(
        buf.getvalue().encode("utf-8"),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'}
    )

# Control routes (Manual, Target, Route) remain standard
@app.route("/manual", methods=["POST"])
def manual():
    require_key(); data = request.get_json(force=True) or {}
    STATE["command"].update({"mode": "manual", "dir": data.get("dir", "stop")})
    return jsonify({"ok": True})

@app.route("/route", methods=["POST"])
def set_route():
    require_key(); data = request.get_json(force=True) or {}
    STATE["route"] = data.get("waypoints", [])
    STATE["command"]["mode"] = "auto"
    return jsonify({"ok": True})

@app.route("/commands", methods=["GET"])
def get_commands():
    require_key()
    return jsonify({"mode": STATE["command"]["mode"], "manual": STATE["command"], "route": STATE["route"]})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)