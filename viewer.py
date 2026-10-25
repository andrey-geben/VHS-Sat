"""VHS-Sat viewer app — runs on a separate port (default 8301).

Public by default (home LAN). Set viewer.public=false to require auth;
the session cookie is shared with the admin app because both use the
same SECRET_KEY (cookies are port-agnostic on the same host).

Shows only enabled channels. The grid page polls /api/channels every
10 s, so newly created channels appear automatically.
"""
from __future__ import annotations
from channel_utils import enrich_channel
from pathlib import Path

from flask import (
    Flask, abort, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)

from config import config
from db import get_channel, list_channels
from event_writer import events
from frozen_utils import APP_ROOT, RESOURCE_ROOT
from supervisor import supervisor


DATA_DIR = APP_ROOT / "data"


def _channel_view(ch: dict) -> dict:
    st = supervisor.get_state(ch["id"])
    base = {**ch, **st, "running": bool(st.get("running"))}
    return enrich_channel(base)


def _admin_base() -> str:
    admin_port = config.get("server", "port", default=8300)
    host = request.host.split(":")[0]
    return f"http://{host}:{admin_port}"


def _auth_redirect():
    if config.get("viewer", "public", default=True):
        return None
    if session.get("user"):
        return None
    target = f"{_admin_base()}/login?next={request.url}"
    return redirect(target)


def create_viewer_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(RESOURCE_ROOT / "templates"),
        static_folder=str(RESOURCE_ROOT / "static"),
    )
    app.config["SECRET_KEY"] = config.get("server", "secret_key")

    @app.context_processor
    def inject():
        return {
            "title": config.get("viewer", "title", default="Домашнее ТВ"),
            "viewer_port": config.get("viewer", "port", default=8301),
            "admin_url": _admin_base(),
            "about": config.get("about", default={}),
        }

    @app.before_request
    def _gate():
        r = _auth_redirect()
        if r:
            return r
        return None

    @app.route("/")
    @app.route("/watch")
    def watch():
        channels = [_channel_view(c) for c in list_channels() if c.get("enabled")]
        return render_template("watch.html", channels=channels)

    @app.route("/watch/<int:cid>")
    def watch_player(cid):
        ch = get_channel(cid)
        if not ch or not ch.get("enabled"):
            abort(404)
        return render_template("watch_player.html", channel=_channel_view(ch))

    @app.route("/about")
    def about():
        return render_template("about_viewer.html")

    @app.route("/hls/<int:cid>/<path:filename>")
    def hls_file(cid, filename):
        hls_root = DATA_DIR / "hls" / str(cid)
        if not hls_root.is_dir():
            abort(404)
        return send_from_directory(hls_root, filename, mimetype=None)

    @app.route("/api/channels")
    def api_channels():
        from epg_utils import now_next
        result = []
        for ch in list_channels():
            if not ch.get("enabled"):
                continue
            cv = _channel_view(ch)
            if ch.get("source_type") == "folder" and cv.get("running"):
                try:
                    cv["epg_now"], cv["epg_next"] = now_next(
                        ch, supervisor.get_state(ch["id"]),
                    )
                except Exception:  # noqa: BLE001
                    cv["epg_now"] = cv["epg_next"] = None
            result.append(cv)
        return jsonify(result)

    @app.route("/api/channels/<int:cid>")
    def api_channel(cid):
        ch = get_channel(cid)
        if not ch or not ch.get("enabled"):
            return jsonify({"error": "not found"}), 404
        return jsonify(_channel_view(ch))

    return app


def _log_startup():
    port = config.get("viewer", "port", default=8301)
    public = config.get("viewer", "public", default=True)
    events.info("viewer", f"viewer on http://0.0.0.0:{port} (public={public})")