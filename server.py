"""VHS-Sat — satellite TV relay server (Flask admin front-end).

Viewer runs on a separate port (default 8301) via viewer.py.
"""
from __future__ import annotations

import platform
import threading
from pathlib import Path

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template,
    request, url_for,
)

from auth import auth_bp, current_user, hash_password, login_required
from config import config
from db import (
    create_channel, delete_channel, find_channels_by_folder,
    find_channels_by_stream_url, get_channel, init_db, list_channels,
    update_channel,
)
from event_writer import events
from hardware import backend
from hardware.tools import detect_tools
from iptv_parser import fetch_playlist, parse_m3u
from settings_page import settings_bp
from supervisor import supervisor


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def _to_int(value, default=None):
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value) -> bool:
    return str(value).lower() in ("1", "true", "on", "yes")


def _hw_summary(result: dict) -> str:
    if not result:
        return "нет данных"
    if result.get("ok"):
        return "применено"
    if result.get("reason"):
        return f"не применено: {result['reason']}"
    details = result.get("details") or {}
    failed = [k for k, v in details.items() if v.get("rc") not in (0, None)]
    if failed:
        return f"ошибки: {', '.join(failed)}"
    return "применено с предупреждениями"


def _channel_view(ch: dict) -> dict:
    st = supervisor.get_state(ch["id"])
    return {**ch, **st, "running": bool(st.get("running"))}


def _validate_channel_payload(data: dict, exclude_id: int | None = None) -> str | None:
    name = (data.get("name") or "").strip()
    if not name:
        return "название канала обязательно"

    source_type = (data.get("source_type") or "folder").lower()

    if source_type == "folder":
        folder = (data.get("folder") or "").strip()
        if not folder:
            return "путь к папке обязателен"
        p = Path(folder)
        if not p.is_dir():
            return f"папка не существует: {folder}"
        dup = find_channels_by_folder(folder, exclude_id=exclude_id)
        if dup:
            return f"эта папка уже используется каналом «{dup[0]['name']}» (id={dup[0]['id']})"
        exts = (data.get("file_extensions") or "").lower()
        if not any(p.suffix.lower().lstrip(".") in exts for p in p.iterdir() if p.is_file()):
            return "в папке нет видеофайлов с указанными расширениями"

    elif source_type in ("iptv", "camera"):
        url = (data.get("stream_url") or "").strip()
        if not url:
            return "URL потока обязателен"
        if not url.startswith(("http://", "https://", "rtsp://", "rtmp://", "udp://", "rtp://")):
            return "URL должен начинаться с http://, https://, rtsp://, rtmp://, udp:// или rtp://"
        dup = find_channels_by_stream_url(url)
        dup = [d for d in dup if d["id"] != exclude_id]
        if dup:
            return f"этот URL уже используется каналом «{dup[0]['name']}» (id={dup[0]['id']})"

    else:
        return f"неизвестный source_type: {source_type}"

    if not (data.get("hls_enabled") or data.get("multicast_enabled")):
        return "включите хотя бы один вывод (HLS или multicast)"
    return None


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.get("server", "secret_key")
    init_db()

    for sub in ("hls", "bumpers", "playlists"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)

    app.register_blueprint(auth_bp)
    app.register_blueprint(settings_bp)

    @app.context_processor
    def inject_globals():
        admin_port = config.get("server", "port", default=8300)
        viewer_port = config.get("viewer", "port", default=8301)
        viewer_enabled = config.get("viewer", "enabled", default=True)
        host = request.host.split(":")[0]
        return {
            "title": config.get("server", "title", default="VHS-Sat"),
            "current_user": current_user(),
            "backend_name": backend.name,
            "platform": platform.system(),
            "viewer_enabled": viewer_enabled,
            "viewer_port": viewer_port,
            "viewer_url": f"http://{host}:{viewer_port}/",
            "admin_port": admin_port,
            "admin_url": f"http://{host}:{admin_port}/",
            "about": config.get("about", default={}),
            "edition": "full",
        }

    @app.before_request
    def _force_setup():
        allowed = {"setup", "static", "auth.login", "api_status"}
        if request.endpoint in allowed:
            return None
        if not config.has_users():
            return redirect(url_for("setup"))
        return None

    # ---------- setup ----------
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if config.has_users() and request.method == "GET":
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            password2 = request.form.get("password2", "")
            if not username or len(password) < 6:
                flash("Имя пользователя обязательно, пароль ≥ 6 символов", "error")
                return render_template("setup.html"), 400
            if password != password2:
                flash("Пароли не совпадают", "error")
                return render_template("setup.html"), 400
            config.set("security", "users", value=[{
                "username": username,
                "password": hash_password(password),
                "role": "admin",
            }])
            events.info("setup", f"admin user '{username}' created")
            flash("Администратор создан. Войдите.", "info")
            return redirect(url_for("auth.login"))
        return render_template("setup.html")

    # ---------- dashboard ----------
    @app.route("/")
    @login_required
    def dashboard():
        adapters = _safe(backend.discover_adapters, [])
        ci_slots = _safe(backend.list_ci_slots, [])
        tools = detect_tools()
        channels = [_channel_view(c) for c in list_channels()]
        return render_template("dashboard.html", adapters=adapters,
                               ci_slots=ci_slots, tools=tools,
                               channels=channels)

    # ---------- adapters / hardware ----------
    @app.route("/adapters")
    @login_required
    def adapters_page():
        discovered = _safe(backend.discover_adapters, [])
        config.sync_adapters(discovered)
        by_id = {a["id"]: a for a in (config.get("adapters") or [])}
        view = []
        for disc in discovered:
            cfg = by_id.get(disc["id"], {})
            merged = {**disc}
            if cfg.get("lnb"):
                merged["lnb"] = {**disc.get("lnb", {}), **cfg["lnb"]}
            if cfg.get("diseqc"):
                merged["diseqc"] = {**disc.get("diseqc", {}), **cfg["diseqc"]}
            view.append(merged)
        tools = detect_tools()
        return render_template("adapters.html", adapters=view, tools=tools)

    @app.route("/hardware")
    @login_required
    def hardware_page():
        adapters = _safe(backend.discover_adapters, [])
        ci_slots = _safe(backend.list_ci_slots, [])
        tools = detect_tools()
        return render_template("hardware.html", adapters=adapters,
                               ci_slots=ci_slots, tools=tools)

    # ---------- channels ----------
    @app.route("/channels")
    @login_required
    def channels_page():
        channels = [_channel_view(c) for c in list_channels()]
        tools = detect_tools()
        return render_template("channels.html", channels=channels, tools=tools)

    @app.route("/channels/create", methods=["POST"])
    @login_required
    def channels_create():
        data = {
            "name": request.form.get("name", "").strip(),
            "source_type": "folder",
            "folder": request.form.get("folder", "").strip(),
            "rotation": request.form.get("rotation", "random"),
            "reshuffle_on_loop": 1 if _to_bool(request.form.get("reshuffle_on_loop")) else 0,
            "file_extensions": request.form.get("file_extensions", "mp4,mkv,avi,ts,mov,m4v,webm"),
            "codec_strategy": request.form.get("codec_strategy", "auto"),
            "bumper_enabled": 1 if _to_bool(request.form.get("bumper_enabled")) else 0,
            "bumper_duration_sec": _to_int(request.form.get("bumper_duration_sec"), 5),
            "stream_url": None,
            "stream_user": None,
            "stream_pass": None,
            "hls_enabled": 1 if _to_bool(request.form.get("hls_enabled", "on")) else 0,
            "multicast_enabled": 1 if _to_bool(request.form.get("multicast_enabled")) else 0,
            "multicast_addr": request.form.get("multicast_addr", "239.1.1.1").strip(),
            "multicast_port": _to_int(request.form.get("multicast_port"), 5000),
            "enabled": 1,
        }
        err = _validate_channel_payload(data)
        if err:
            flash(err, "error")
            return redirect(url_for("channels_page"))
        try:
            cid = create_channel(data)
        except Exception as exc:  # noqa: BLE001
            flash(f"Ошибка создания канала: {exc}", "error")
            return redirect(url_for("channels_page"))
        events.info("channels", f"created channel {cid} '{data['name']}'")
        flash(f"Канал «{data['name']}» создан", "info")
        return redirect(url_for("channels_page"))

    @app.route("/channels/create-stream", methods=["POST"])
    @login_required
    def channels_create_stream():
        source_type = request.form.get("source_type", "camera").lower()
        if source_type not in ("iptv", "camera"):
            source_type = "camera"
        data = {
            "name": request.form.get("name", "").strip(),
            "source_type": source_type,
            "folder": None,
            "rotation": "random",
            "reshuffle_on_loop": 0,
            "file_extensions": "mp4,mkv,avi,ts,mov,m4v,webm",
            "codec_strategy": request.form.get("codec_strategy", "auto"),
            "bumper_enabled": 0,
            "bumper_duration_sec": 5,
            "stream_url": request.form.get("stream_url", "").strip(),
            "stream_user": request.form.get("stream_user", "").strip() or None,
            "stream_pass": request.form.get("stream_pass", "").strip() or None,
            "hls_enabled": 1 if _to_bool(request.form.get("hls_enabled", "on")) else 0,
            "multicast_enabled": 1 if _to_bool(request.form.get("multicast_enabled")) else 0,
            "multicast_addr": request.form.get("multicast_addr", "239.1.1.1").strip(),
            "multicast_port": _to_int(request.form.get("multicast_port"), 5000),
            "enabled": 1,
        }
        err = _validate_channel_payload(data)
        if err:
            flash(err, "error")
            return redirect(url_for("channels_page"))
        cid = create_channel(data)
        events.info("channels",
                    f"created {source_type} channel {cid} '{data['name']}'")
        flash(f"Канал «{data['name']}» создан", "info")
        return redirect(url_for("channels_page"))

    @app.route("/channels/iptv/import", methods=["GET", "POST"])
    @login_required
    def channels_iptv_import():
        url = (request.values.get("url") or "").strip()
        uploaded = request.files.get("file")

        playlist_text = ""
        if uploaded and uploaded.filename:
            playlist_text = uploaded.read().decode("utf-8", errors="replace")
        elif url:
            try:
                playlist_text = fetch_playlist(url)
            except Exception as exc:  # noqa: BLE001
                flash(f"Не удалось загрузить плейлист: {exc}", "error")
                return redirect(url_for("channels_page"))

        if not playlist_text:
            flash("Укажите URL плейлиста или загрузите файл", "error")
            return redirect(url_for("channels_page"))

        entries = parse_m3u(playlist_text)
        if not entries:
            flash("В плейлисте не найдено ни одного канала", "warn")
            return redirect(url_for("channels_page"))

        groups = sorted({e["group"] for e in entries if e.get("group")})
        return render_template("iptv_import.html",
                               entries=entries, groups=groups, source_url=url)

    @app.route("/channels/iptv/bulk-import", methods=["POST"])
    @login_required
    def channels_iptv_bulk_import():
        names = request.form.getlist("name")
        urls = request.form.getlist("url")
        strategy = request.form.get("codec_strategy", "auto")
        hls = 1 if _to_bool(request.form.get("hls_enabled", "on")) else 0
        mcast = 1 if _to_bool(request.form.get("multicast_enabled")) else 0
        mcast_addr = request.form.get("multicast_addr", "239.1.1.1").strip()
        mcast_port = _to_int(request.form.get("multicast_port"), 5000)

        created, skipped = 0, 0
        next_port = mcast_port
        for i, u in enumerate(urls):
            u = u.strip()
            if not u:
                continue
            nm = (names[i].strip() if i < len(names) else "") or f"IPTV {i+1}"
            data = {
                "name": nm,
                "source_type": "iptv",
                "folder": None,
                "rotation": "random",
                "reshuffle_on_loop": 0,
                "file_extensions": "mp4,mkv,avi,ts,mov,m4v,webm",
                "codec_strategy": strategy,
                "bumper_enabled": 0,
                "bumper_duration_sec": 5,
                "stream_url": u,
                "stream_user": None,
                "stream_pass": None,
                "hls_enabled": hls,
                "multicast_enabled": mcast,
                "multicast_addr": mcast_addr,
                "multicast_port": next_port,
                "enabled": 1,
            }
            err = _validate_channel_payload(data)
            if err:
                skipped += 1
                continue
            try:
                create_channel(data)
                created += 1
                if mcast:
                    next_port += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                events.warn("channels", f"IPTV import: skip {nm}: {exc}")

        events.info("channels",
                    f"IPTV import: created={created}, skipped={skipped}")
        flash(f"Импортировано {created} канал(ов)"
              + (f", пропущено {skipped}" if skipped else ""),
              "info" if created else "warn")
        return redirect(url_for("channels_page"))

    @app.route("/channels/<int:cid>/edit", methods=["POST"])
    @login_required
    def channels_edit(cid):
        ch = get_channel(cid)
        if not ch:
            abort(404)
        st = ch["source_type"]
        data = {
            "name": request.form.get("name", "").strip() or ch["name"],
            "rotation": request.form.get("rotation", ch["rotation"]),
            "reshuffle_on_loop": 1 if _to_bool(request.form.get("reshuffle_on_loop")) else 0,
            "file_extensions": request.form.get("file_extensions", ch["file_extensions"]),
            "codec_strategy": request.form.get("codec_strategy", ch["codec_strategy"]),
            "bumper_enabled": 1 if _to_bool(request.form.get("bumper_enabled")) else 0,
            "bumper_duration_sec": _to_int(request.form.get("bumper_duration_sec"), ch["bumper_duration_sec"]),
            "hls_enabled": 1 if _to_bool(request.form.get("hls_enabled")) else 0,
            "multicast_enabled": 1 if _to_bool(request.form.get("multicast_enabled")) else 0,
            "multicast_addr": request.form.get("multicast_addr", ch["multicast_addr"]).strip(),
            "multicast_port": _to_int(request.form.get("multicast_port"), ch["multicast_port"]),
        }
        if st == "folder":
            data["folder"] = request.form.get("folder", "").strip() or ch["folder"]
        else:
            data["stream_url"] = (request.form.get("stream_url", "").strip()
                                  or ch["stream_url"])
            if request.form.get("stream_user") is not None:
                data["stream_user"] = request.form.get("stream_user", "").strip() or None
            if request.form.get("stream_pass"):
                data["stream_pass"] = request.form.get("stream_pass", "").strip() or None

        err = _validate_channel_payload({**ch, **data}, exclude_id=cid)
        if err:
            flash(err, "error")
            return redirect(url_for("channels_page"))
        was_running = supervisor.get_state(cid).get("running")
        if was_running:
            supervisor.stop(cid)
        update_channel(cid, data)
        if was_running:
            supervisor.start(get_channel(cid))
        flash(f"Канал «{data['name']}» обновлён", "info")
        return redirect(url_for("channels_page"))

    @app.route("/channels/<int:cid>/delete", methods=["POST"])
    @login_required
    def channels_delete(cid):
        ch = get_channel(cid)
        if not ch:
            abort(404)
        supervisor.stop(cid)
        delete_channel(cid)
        events.info("channels", f"deleted channel {cid}")
        flash(f"Канал «{ch['name']}» удалён", "info")
        return redirect(url_for("channels_page"))

    @app.route("/channels/<int:cid>/start", methods=["POST"])
    @login_required
    def channels_start(cid):
        ch = get_channel(cid)
        if not ch:
            abort(404)
        if supervisor.start(ch):
            events.info("channels", f"channel {cid} started")
            flash(f"Канал «{ch['name']}» запущен", "info")
        else:
            flash(f"Канал «{ch['name']}» уже работает", "warn")
        return redirect(url_for("channels_page"))

    @app.route("/channels/<int:cid>/stop", methods=["POST"])
    @login_required
    def channels_stop(cid):
        ch = get_channel(cid)
        if not ch:
            abort(404)
        supervisor.stop(cid)
        events.info("channels", f"channel {cid} stopped")
        flash(f"Канал «{ch['name']}» остановлен", "info")
        return redirect(url_for("channels_page"))

    # ---------- events ----------
    @app.route("/events")
    @login_required
    def events_page():
        limit = int(request.args.get("limit", 200))
        return render_template("events.html", events=events.read_tail(limit))

    # ---------- placeholders (stage 5) ----------
    @app.route("/epg")
    @login_required
    def epg_page():
        return render_template("placeholder.html",
                               page_title="EPG", message="Stage 5")

    @app.route("/recordings")
    @login_required
    def recordings_page():
        return render_template("placeholder.html",
                               page_title="Записи", message="Stage 5")

    # ---------- about ----------
    @app.route("/about")
    @login_required
    def about_page():
        return render_template("about.html")

    # ---------- admin preview of viewer pages ----------
    @app.route("/watch")
    @login_required
    def watch():
        channels = [_channel_view(c) for c in list_channels()]
        return render_template("watch.html", channels=channels)

    @app.route("/watch/<int:cid>")
    @login_required
    def watch_player(cid):
        ch = get_channel(cid)
        if not ch:
            abort(404)
        return render_template("watch_player.html", channel=_channel_view(ch))

    # ---------- REST API ----------
    @app.route("/api/status")
    def api_status():
        return jsonify({
            "title": config.get("server", "title"),
            "backend": backend.name,
            "platform": platform.system(),
            "edition": "full",
            "auth_enabled": config.get("security", "auth_enabled"),
            "users_configured": config.has_users(),
        })

    @app.route("/api/tools")
    @login_required
    def api_tools():
        return jsonify(detect_tools())

    @app.route("/api/adapters")
    @login_required
    def api_adapters():
        return jsonify(backend.discover_adapters())

    @app.route("/api/adapters/<adapter_id>")
    @login_required
    def api_adapter(adapter_id):
        try:
            return jsonify(backend.get_adapter_status(adapter_id))
        except KeyError:
            return jsonify({"error": "adapter not found"}), 404

    @app.route("/api/adapters/<adapter_id>/lnb", methods=["POST"])
    @login_required
    def api_adapter_set_lnb(adapter_id):
        is_json = request.is_json or request.form.get("_format") == "json"
        if is_json:
            payload = request.get_json(silent=True) or {}
        else:
            payload = {
                "lnb": {
                    "type": request.form.get("lnb_type") or None,
                    "low": _to_int(request.form.get("lnb_low")),
                    "high": _to_int(request.form.get("lnb_high")),
                    "voltage": (request.form.get("lnb_voltage") or "").lower() or None,
                    "tone": (request.form.get("lnb_tone") or "").lower() or None,
                },
                "diseqc": {
                    "version": request.form.get("diseqc_version") or None,
                    "port": _to_int(request.form.get("diseqc_port")),
                },
            }
        lnb_payload = {k: v for k, v in (payload.get("lnb") or {}).items() if v not in (None, "")}
        diseqc_payload = {k: v for k, v in (payload.get("diseqc") or {}).items() if v not in (None, "")}

        cfg_adapters = config.get("adapters") or []
        entry = next((a for a in cfg_adapters if a["id"] == adapter_id), None)
        if entry is None:
            try:
                disc = backend.get_adapter_status(adapter_id)
            except KeyError:
                if is_json:
                    return jsonify({"ok": False, "error": "adapter not found"}), 404
                flash(f"Адаптер {adapter_id} не найден", "error")
                return redirect(url_for("adapters_page"))
            entry = {"id": adapter_id, "device": disc["device"],
                     "frontend": disc["frontend"], "lnb": {}, "diseqc": {}}
            cfg_adapters.append(entry)
        entry["lnb"] = {**entry.get("lnb", {}), **lnb_payload}
        entry["diseqc"] = {**entry.get("diseqc", {}), **diseqc_payload}
        config.set("adapters", value=cfg_adapters)

        try:
            hw_lnb = backend.set_lnb(adapter_id, entry["lnb"])
        except NotImplementedError as exc:
            hw_lnb = {"ok": False, "reason": str(exc)}
        try:
            hw_diseqc = backend.apply_diseqc(adapter_id, entry.get("diseqc", {}))
        except NotImplementedError as exc:
            hw_diseqc = {"ok": False, "reason": str(exc)}

        events.info("adapters", f"{adapter_id}: config updated",
                    lnb=entry["lnb"], diseqc=entry.get("diseqc"),
                    hw_lnb=hw_lnb, hw_diseqc=hw_diseqc)

        if is_json:
            return jsonify({"ok": True,
                            "config": {"lnb": entry["lnb"], "diseqc": entry.get("diseqc")},
                            "hardware": {"lnb": hw_lnb, "diseqc": hw_diseqc}})
        flash(f"{adapter_id}: LNB — {_hw_summary(hw_lnb)}; DiSEqC — {_hw_summary(hw_diseqc)}",
              "info" if hw_lnb.get("ok") else "warn")
        return redirect(url_for("adapters_page"))

    @app.route("/api/ci-slots")
    @login_required
    def api_ci_slots():
        return jsonify(backend.list_ci_slots())

    @app.route("/api/ci-slots/<ci_id>/status")
    @login_required
    def api_ci_status(ci_id):
        try:
            return jsonify(backend.get_ci_status(ci_id))
        except KeyError:
            return jsonify({"error": "ci slot not found"}), 404

    @app.route("/api/hardware")
    @login_required
    def api_hardware():
        return jsonify({
            "backend": backend.name, "platform": platform.system(),
            "adapters": backend.discover_adapters(),
            "ci_slots": backend.list_ci_slots(),
            "tools": detect_tools(),
        })

    @app.route("/api/events")
    @login_required
    def api_events():
        limit = int(request.args.get("limit", 100))
        return jsonify(events.read_tail(limit))

    @app.route("/api/channels", methods=["GET"])
    @login_required
    def api_channels():
        return jsonify([_channel_view(c) for c in list_channels()])

    @app.route("/api/channels", methods=["POST"])
    @login_required
    def api_channels_create():
        data = request.get_json(silent=True) or {}
        data.setdefault("source_type", "folder")
        data.setdefault("rotation", "random")
        data.setdefault("file_extensions", "mp4,mkv,avi,ts,mov,m4v,webm")
        data.setdefault("codec_strategy", "auto")
        data.setdefault("bumper_duration_sec", 5)
        data.setdefault("stream_url", None)
        data.setdefault("stream_user", None)
        data.setdefault("stream_pass", None)
        data.setdefault("multicast_addr", "239.1.1.1")
        data.setdefault("multicast_port", 5000)
        data.setdefault("enabled", 1)
        for k in ("reshuffle_on_loop", "bumper_enabled", "hls_enabled", "multicast_enabled"):
            if k in data:
                data[k] = 1 if data[k] else 0
        err = _validate_channel_payload(data)
        if err:
            return jsonify({"ok": False, "error": err}), 400
        cid = create_channel(data)
        return jsonify({"ok": True, "id": cid}), 201

    @app.route("/api/channels/<int:cid>", methods=["GET"])
    @login_required
    def api_channel_get(cid):
        ch = get_channel(cid)
        if not ch:
            return jsonify({"error": "not found"}), 404
        return jsonify(_channel_view(ch))

    @app.route("/api/channels/<int:cid>", methods=["PATCH"])
    @login_required
    def api_channel_patch(cid):
        ch = get_channel(cid)
        if not ch:
            return jsonify({"error": "not found"}), 404
        data = request.get_json(silent=True) or {}
        err = _validate_channel_payload({**ch, **data}, exclude_id=cid)
        if err:
            return jsonify({"ok": False, "error": err}), 400
        was_running = supervisor.get_state(cid).get("running")
        if was_running:
            supervisor.stop(cid)
        update_channel(cid, data)
        if was_running:
            supervisor.start(get_channel(cid))
        return jsonify({"ok": True, "channel": _channel_view(get_channel(cid))})

    @app.route("/api/channels/<int:cid>", methods=["DELETE"])
    @login_required
    def api_channel_delete(cid):
        if not get_channel(cid):
            return jsonify({"error": "not found"}), 404
        supervisor.stop(cid)
        delete_channel(cid)
        return jsonify({"ok": True})

    @app.route("/api/channels/<int:cid>/start", methods=["POST"])
    @login_required
    def api_channel_start(cid):
        ch = get_channel(cid)
        if not ch:
            return jsonify({"error": "not found"}), 404
        started = supervisor.start(ch)
        return jsonify({"ok": started, "state": supervisor.get_state(cid)})

    @app.route("/api/channels/<int:cid>/stop", methods=["POST"])
    @login_required
    def api_channel_stop(cid):
        if not get_channel(cid):
            return jsonify({"error": "not found"}), 404
        stopped = supervisor.stop(cid)
        return jsonify({"ok": stopped, "state": supervisor.get_state(cid)})

    @app.route("/api/channels/<int:cid>/state")
    @login_required
    def api_channel_state(cid):
        if not get_channel(cid):
            return jsonify({"error": "not found"}), 404
        return jsonify(supervisor.get_state(cid))

    return app


def _safe(fn, default):
    try:
        return fn()
    except NotImplementedError:
        return default
    except Exception as exc:  # noqa: BLE001
        events.error("hardware", f"{fn.__name__} failed: {exc}")
        return default


def _run_viewer() -> None:
    from werkzeug.serving import make_server
    from viewer import create_viewer_app, _log_startup

    port = int(config.get("viewer", "port", default=8301))
    host = config.get("server", "host", default="0.0.0.0")
    viewer_app = create_viewer_app()
    server = make_server(host, port, viewer_app, threaded=True)
    _log_startup()
    server.serve_forever()


app = create_app()


if __name__ == "__main__":
    import atexit
    atexit.register(supervisor.shutdown_all)

    events.info("server", f"VHS-Sat admin starting (backend={backend.name}, "
                          f"platform={platform.system()})")

    if config.get("viewer", "enabled", default=True):
        viewer_thread = threading.Thread(
            target=_run_viewer, daemon=True, name="viewer-server",
        )
        viewer_thread.start()
    else:
        events.info("server", "viewer disabled (viewer.enabled=false)")

    app.run(
        host=config.get("server", "host", default="0.0.0.0"),
        port=int(config.get("server", "port", default=8300)),
        debug=bool(config.get("server", "debug", default=False)),
        threaded=True,
    )