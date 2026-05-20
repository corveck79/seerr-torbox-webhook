#!/usr/bin/env python3
"""Set Mycelium runtime settings from the command line.

Runtime settings live in the SQLite `settings` table (overriding .env). This
helper lets you set them without clicking through the Settings tab — handy for
scripting a fresh deploy.

Usage:
    python configure.py KEY=VALUE [KEY=VALUE ...]
    python configure.py --list
    python configure.py --recommended TORBOX_API_KEY=xxx REALDEBRID_API_KEY=yyy

Examples:
    # Set a couple of values
    python configure.py TORBOX_API_KEY=abc123 MULTI_DEBRID_ENABLED=true

    # Apply the recommended large-library preset, supplying your keys inline
    python configure.py --recommended \
        TORBOX_API_KEY=abc123 \
        REALDEBRID_API_KEY=J456...

Booleans accept true/false/1/0/yes/no. Empty value (KEY=) clears the override
and falls back to the .env default.
"""
import sys

import db
import settings

db.init()  # idempotent — ensures the settings table exists when run standalone

# Recommended defaults for a large library with TorBox + RealDebrid, lazy
# materialization and no idle eviction. Keys are NOT included — pass those
# inline on the command line.
RECOMMENDED = {
    "MULTI_DEBRID_ENABLED": "true",
    "ZILEAN_ENABLED": "true",
    "CATBOX_MODE": "true",
    "CATBOX_LAZY_ADD": "true",
    "CATBOX_IDLE_MINUTES": "43200",  # 30 days — no eviction within TorBox retention
    "TORRENTIO_BASE_URL":
        "https://torrentio.strem.fun/qualityfilter=brremux,threed,other,480p,scr,cam,unknown",
}

_BOOL = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False}


def _coerce(value: str):
    low = value.strip().lower()
    if low in _BOOL:
        return _BOOL[low]
    if value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return value


def _apply(pairs: dict) -> None:
    for key, raw in pairs.items():
        if raw == "":
            settings.set(key, None)
            print(f"  cleared {key} (falls back to .env)")
            continue
        settings.set(key, _coerce(raw))
        shown = "********" if "KEY" in key or "TOKEN" in key or "SECRET" in key else raw
        print(f"  set {key} = {shown}")


def _list() -> None:
    import db
    overrides = db.get_all_settings()
    if not overrides:
        print("(no runtime overrides set)")
        return
    for key in sorted(overrides):
        val = overrides[key]
        shown = "********" if any(s in key for s in ("KEY", "TOKEN", "SECRET")) else val
        print(f"  {key} = {shown}")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if argv[0] == "--list":
        _list()
        return 0

    recommended = False
    args = argv
    if argv[0] == "--recommended":
        recommended = True
        args = argv[1:]

    pairs: dict[str, str] = {}
    if recommended:
        pairs.update(RECOMMENDED)

    for arg in args:
        if "=" not in arg:
            print(f"error: expected KEY=VALUE, got {arg!r}", file=sys.stderr)
            return 2
        key, value = arg.split("=", 1)
        pairs[key.strip()] = value

    if not pairs:
        print("Nothing to set.")
        return 0

    print("Applying settings:")
    _apply(pairs)
    print("Done. Hot-reload settings take effect immediately; schedule/interval "
          "settings need a container restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
