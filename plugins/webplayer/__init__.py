from flask import Blueprint
from . import routes as _routes

blueprint = Blueprint("webplayer", __name__)
blueprint.register_blueprint(_routes.bp)

PLUGIN_META = {
    "label":             "Web Player",
    "version":           "1.0.0",
    "description":       "Browser-native video playback with catbox support",
    "user_fields":       ["webplayer_enabled"],
    "user_field_labels": {"webplayer_enabled": "Web Player"},
}


def run_migrations() -> None:
    import db
    with db._connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        if "webplayer_enabled" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN webplayer_enabled INTEGER NOT NULL DEFAULT 0")
            c.execute("UPDATE users SET webplayer_enabled = 1 WHERE role = 'admin'")


def session_data(user_record: dict) -> dict:
    return {"webplayer_enabled": bool(user_record.get("webplayer_enabled"))}


def register_jobs(scheduler) -> None:
    from . import web_player
    scheduler.add_job(
        web_player.cleanup_idle_sessions,
        "interval", minutes=15,
        id="webplayer_cleanup",
        replace_existing=True,
    )
