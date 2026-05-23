# Parked — exact snippets to add to db.py when activating the web player.
#
# 1. Add both migrations to _run_migrations() (inside the `with _connect() as conn:` block,
#    alongside the existing region migration at line ~376)
#
# 2. Update list_users(), update_user() and create_user() as shown below.

# ── Migrations ────────────────────────────────────────────────────────────────
#
# Paste into _run_migrations(), after the existing region migration block:
#
#   user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
#   if "webplayer_enabled" not in user_cols:
#       conn.execute("ALTER TABLE users ADD COLUMN webplayer_enabled INTEGER NOT NULL DEFAULT 0")
#       conn.execute("UPDATE users SET webplayer_enabled = 1 WHERE role = 'admin'")
#       log.info("Migration: added users.webplayer_enabled (admin=1, users=0)")


# ── list_users() ──────────────────────────────────────────────────────────────
# Add webplayer_enabled to the SELECT (line ~1243):
#
# Old:
#   rows = conn.execute("SELECT id, username, role, quota_monthly, auto_approve, enabled, region, created_at, last_login FROM users ORDER BY id").fetchall()
#
# New:
#   rows = conn.execute("SELECT id, username, role, quota_monthly, auto_approve, enabled, region, webplayer_enabled, created_at, last_login FROM users ORDER BY id").fetchall()


# ── update_user() ─────────────────────────────────────────────────────────────
# Add webplayer_enabled to the allowed set (line ~1250):
#
# Old:
#   allowed = {"password_hash", "role", "quota_monthly", "auto_approve", "enabled", "region"}
#
# New:
#   allowed = {"password_hash", "role", "quota_monthly", "auto_approve", "enabled", "region", "webplayer_enabled"}


# ── create_user() ─────────────────────────────────────────────────────────────
# Admins get webplayer_enabled=1 by default.
# Change the INSERT at line ~1222:
#
# Old:
#   """INSERT INTO users (username, password_hash, role, quota_monthly, auto_approve)
#      VALUES (?, ?, ?, ?, ?)"""
#   (username, password_hash, role, quota_monthly, 1 if auto_approve else 0)
#
# New:
#   """INSERT INTO users (username, password_hash, role, quota_monthly, auto_approve, webplayer_enabled)
#      VALUES (?, ?, ?, ?, ?, ?)"""
#   (username, password_hash, role, quota_monthly,
#    1 if auto_approve else 0,
#    1 if role == "admin" else 0)
