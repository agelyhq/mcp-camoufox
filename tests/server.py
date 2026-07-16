"""Minimal Flask server providing test pages for each MCP tool."""

from __future__ import annotations

import time

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/click")
def click_page():
    return render_template("click.html")


@app.route("/fill")
def fill_page():
    return render_template("fill.html")


@app.route("/evaluate")
def evaluate_page():
    return render_template("evaluate.html")


@app.route("/press-key")
def press_key_page():
    return render_template("press_key.html")


@app.route("/scroll")
def scroll_page():
    return render_template("scroll.html")


@app.route("/upload")
def upload_page():
    return render_template("upload.html")


@app.route("/wait-for")
def wait_for_page():
    return render_template("wait_for.html")


@app.route("/dialog")
def dialog_page():
    return render_template("dialog.html")


@app.route("/screenshot")
def screenshot_page():
    return render_template("screenshot.html")


@app.route("/snapshot")
def snapshot_page():
    return render_template("snapshot.html")


@app.route("/network")
def network_page():
    return render_template("network.html")


@app.route("/profile")
def profile_page():
    return render_template("profile.html")


@app.route("/fingerprint")
def fingerprint_page():
    return render_template("fingerprint.html")


@app.route("/console")
def console_page():
    return render_template("console.html")


@app.route("/infinite-scroll")
def infinite_scroll_page():
    return render_template("infinite_scroll.html")


@app.route("/hover")
def hover_page():
    return render_template("hover.html")


@app.route("/drag")
def drag_page():
    return render_template("drag.html")


@app.route("/fill-form")
def fill_form_page():
    return render_template("fill_form.html")


@app.route("/type-text")
def type_text_page():
    return render_template("type_text.html")


@app.route("/click-at")
def click_at_page():
    return render_template("click_at.html")


@app.route("/get-html")
def get_html_page():
    return render_template("get_html.html")


# ---------------------------------------------------------------------------
# API endpoints (for AJAX / network testing)
# ---------------------------------------------------------------------------


CATEGORIES = ["tech", "science", "health", "travel", "food"]
TOTAL_ITEMS = 50


@app.route("/api/items")
def api_items():
    page = int(request.args.get("page", 0))
    per_page = int(request.args.get("per_page", 10))
    start = page * per_page
    end = min(start + per_page, TOTAL_ITEMS)
    items = [
        {
            "id": i + 1,
            "title": f"Item #{i + 1}",
            "body": f"This is the description for item {i + 1}. It belongs to the {CATEGORIES[i % len(CATEGORIES)]} category.",
            "category": CATEGORIES[i % len(CATEGORIES)],
        }
        for i in range(start, end)
    ]
    return jsonify(
        {"items": items, "has_more": end < TOTAL_ITEMS, "page": page, "total": TOTAL_ITEMS}
    )


@app.route("/api/echo", methods=["POST"])
def api_echo():
    data = request.get_json(silent=True) or {}
    return jsonify({"echo": data, "timestamp": time.time()})


@app.route("/api/data")
def api_data():
    return jsonify(
        {
            "items": [
                {"id": 1, "name": "Alpha"},
                {"id": 2, "name": "Beta"},
                {"id": 3, "name": "Gamma"},
            ],
            "total": 3,
        }
    )


@app.route("/api/slow")
def api_slow():
    delay = float(request.args.get("seconds", 2))
    time.sleep(delay)
    return jsonify({"waited": delay})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    return jsonify(
        {
            "filename": f.filename,
            "content_type": f.content_type,
            "size": len(f.read()),
        }
    )


@app.route("/api/form", methods=["POST"])
def api_form():
    data = {k: v for k, v in request.form.items()}
    return jsonify({"received": data})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5123, debug=True)
