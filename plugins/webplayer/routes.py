import db
import auth
from flask import Blueprint, abort, jsonify, request, send_file
from flask import session as flask_session
from . import web_player

bp = Blueprint("webplayer_routes", __name__)


def _check_enabled():
    rec = auth.current_user_record()
    if not rec or not rec.get("webplayer_enabled"):
        abort(403)
    return rec


@bp.post("/ui/api/web-player/prepare")
def web_player_prepare():
    _check_enabled()
    d = request.json or {}
    job_id = web_player.start_prepare_job(
        imdb_id    = d["imdb_id"],
        media_type = d["media_type"],
        season     = d.get("season"),
        episode    = d.get("episode"),
    )
    return jsonify(job_id=job_id)


@bp.get("/ui/api/web-player/status/<job_id>")
def web_player_status(job_id: str):
    job = web_player.get_job(job_id)
    if not job:
        abort(404)
    return jsonify(
        status     = job.status.value,
        message    = job.message,
        token      = job.token,
        stream_url = job.stream_url,
        file_info  = job.file_info,
        error      = job.error,
    )


@bp.get("/stream/<token>/hls/playlist.m3u8")
def stream_hls_playlist(token: str):
    s = web_player.get_session(token)
    if not s:
        abort(404)
    s.touch()
    return send_file(s.tmp_dir / "playlist.m3u8",
                     mimetype="application/vnd.apple.mpegurl")


@bp.get("/stream/<token>/hls/<segment>")
def stream_hls_segment(token: str, segment: str):
    if "/" in segment or not segment.endswith(".ts"):
        abort(400)
    s = web_player.get_session(token)
    if not s:
        abort(404)
    p = s.tmp_dir / segment
    if not p.exists():
        abort(404)
    s.touch()
    return send_file(p, mimetype="video/mp2t")


@bp.get("/stream/<token>/subtitles")
def stream_subtitles_list(token: str):
    return jsonify(subtitles=web_player.list_subtitles(token))


@bp.get("/stream/<token>/subtitles/<filename>")
def stream_subtitle_file(token: str, filename: str):
    if "/" in filename or not filename.endswith(".vtt"):
        abort(400)
    s = web_player.get_session(token)
    if not s:
        abort(404)
    p = s.tmp_dir / filename
    if not p.exists():
        abort(404)
    return send_file(p, mimetype="text/vtt")


@bp.post("/stream/<token>/position")
def stream_save_position(token: str):
    d = request.json or {}
    user_id = flask_session.get("user_id")
    if not user_id:
        abort(401)
    db.save_playback_position(
        user_id    = user_id,
        token      = token,
        position_s = float(d.get("position_s", 0)),
        duration_s = d.get("duration_s"),
    )
    return jsonify(ok=True)
