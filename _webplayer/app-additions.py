# Parked — exact snippets to add to app.py when activating the web player.

# ── 1. Import (top of app.py, with other imports) ─────────────────────────────
#
#   import _webplayer.web_player as web_player


# ── 2. Session endpoint — add webplayer_enabled (line ~1777) ──────────────────
#
# Old:
#   return jsonify(authenticated=True, user={
#       "id": rec.get("id"),
#       "username": rec.get("username"),
#       "role": rec.get("role"),
#       "auto_approve": bool(rec.get("auto_approve")),
#       "region": rec.get("region", "NL"),
#   })
#
# New:
#   return jsonify(authenticated=True, user={
#       "id": rec.get("id"),
#       "username": rec.get("username"),
#       "role": rec.get("role"),
#       "auto_approve": bool(rec.get("auto_approve")),
#       "region": rec.get("region", "NL"),
#       "webplayer_enabled": bool(rec.get("webplayer_enabled")),
#   })


# ── 3. Update user route — handle webplayer_enabled (line ~1832) ───────────────
#
# Add after the existing `if "enabled" in p:` line:
#
#   if "webplayer_enabled" in p:
#       fields["webplayer_enabled"] = 1 if p["webplayer_enabled"] else 0


# ── 4. Web player routes (paste after the existing /stream/<token> route) ──────
#
# @app.post("/ui/api/web-player/prepare")
# def web_player_prepare():
#     if not bool(auth.current_user_record().get("webplayer_enabled")):
#         return jsonify(error="Web player not enabled for your account"), 403
#     d = request.json or {}
#     job_id = web_player.start_prepare_job(
#         imdb_id=d["imdb_id"], media_type=d["media_type"],
#         season=d.get("season"), episode=d.get("episode"),
#     )
#     return jsonify(job_id=job_id)
#
# @app.get("/ui/api/web-player/status/<job_id>")
# def web_player_status(job_id):
#     job = web_player.get_job(job_id)
#     if not job: abort(404)
#     return jsonify(status=job.status.value, message=job.message, token=job.token,
#                    stream_url=job.stream_url, file_info=job.file_info, error=job.error)
#
# @app.get("/stream/<token>/hls/playlist.m3u8")
# def stream_hls_playlist(token):
#     s = web_player.get_session(token)
#     if not s: abort(404)
#     s.touch()
#     return send_file(s.tmp_dir / "playlist.m3u8", mimetype="application/vnd.apple.mpegurl")
#
# @app.get("/stream/<token>/hls/<segment>")
# def stream_hls_segment(token, segment):
#     if "/" in segment or not segment.endswith(".ts"): abort(400)
#     s = web_player.get_session(token)
#     if not s: abort(404)
#     p = s.tmp_dir / segment
#     if not p.exists(): abort(404)
#     s.touch()
#     return send_file(p, mimetype="video/mp2t")
#
# @app.get("/stream/<token>/subtitles")
# def stream_subtitles_list(token):
#     return jsonify(subtitles=web_player.list_subtitles(token))
#
# @app.get("/stream/<token>/subtitles/<filename>")
# def stream_subtitle_file(token, filename):
#     if "/" in filename or not filename.endswith(".vtt"): abort(400)
#     s = web_player.get_session(token)
#     if not s: abort(404)
#     p = s.tmp_dir / filename
#     if not p.exists(): abort(404)
#     return send_file(p, mimetype="text/vtt")
#
# @app.post("/stream/<token>/position")
# @_csrf.exempt
# def stream_save_position(token):
#     d = request.json or {}
#     db.save_playback_position(flask_session["user_id"], token,
#                               float(d.get("position_s", 0)), d.get("duration_s"))
#     return jsonify(ok=True)
#
# # In scheduler setup:
# # scheduler.add_job(web_player.cleanup_idle_sessions, "interval", minutes=15, id="wp_cleanup")
