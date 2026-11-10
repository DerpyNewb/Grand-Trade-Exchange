"""Minimal raw-HTTP client for RPFM's MCP server, v2 API (RPFM 5.3.0+). Every tool here
that talks to RPFM goes through call().

Since 5.3.0 all MCP clients share ONE RPFM session - the selected game, the schema, the
dependencies and the open packs - kept while it has open packs or a running job. So
ensure_game() checks session_status before touching the game, and every pack opened or
created through this module is closed when the script exits: a pack left open keeps the
shared session alive, and its unsaved edits are visible to every other client.

call() returns the tool's structured result, waits out jobs, and RAISES on a failed call.
A v2 failure is `isError` with a {code, message, data} body; v1's {"Error": ...} payload
is gone, and a check for that key reads every v2 failure as success.

The MCP transport session (Mcp-Session-Id) can expire and then answers HTTP 404; call()
re-initialises it and retries once. The RPFM session behind it is shared and survives.
"""
import atexit
import json
import os
import re
import urllib.error
import urllib.request

URL = "http://127.0.0.1:45127/mcp"
GAME = "warhammer_3"
_sid = [None]
_n = [0]
_opened = []          # pack keys this process opened or created; closed at exit


def _post(body):
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": "2025-11-25"}
    if _sid[0]:
        headers["Mcp-Session-Id"] = _sid[0]
    req = urllib.request.Request(URL, json.dumps(body).encode("utf-8"), headers)
    with urllib.request.urlopen(req, timeout=1800) as r:
        _sid[0] = r.headers.get("Mcp-Session-Id") or _sid[0]
        raw = r.read().decode("utf-8", "replace")
    if "id" not in body:
        return None
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    out = None
    for line in raw.splitlines():            # SSE: the last data line carries the reply
        if re.match(r"^data:\s*\{", line):
            out = json.loads(line.split("data:", 1)[1])
    if out is None:
        raise RuntimeError("no reply from RPFM: " + raw[:400])
    return out


def _rpc(method, params):
    _n[0] += 1
    return _post({"jsonrpc": "2.0", "id": _n[0], "method": method, "params": params})


def _connect():
    _sid[0] = None
    try:
        _rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                            "clientInfo": {"name": "derpy-tools", "version": "2"}})
    except urllib.error.URLError:
        raise SystemExit("RPFM is not running - its MCP server only exists while RPFM is open")
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"})


def _call_once(tool, args):
    r = _rpc("tools/call", {"name": tool, "arguments": args})
    if "error" in r:
        raise RuntimeError("RPFM %s: %s" % (tool, r["error"].get("message", r["error"])))
    res = r["result"]
    txt = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
    if res.get("isError"):
        try:
            txt = json.loads(txt).get("message", txt)
        except (ValueError, AttributeError):
            pass
        raise RuntimeError("RPFM %s: %s" % (tool, txt[:600]))
    if "structuredContent" in res:
        return res["structuredContent"]
    try:
        return json.loads(txt)
    except ValueError:
        return txt


def call(tool, args=None, quiet=True):
    """One tool call. Returns its structured result; a job's result once it finishes."""
    args = args or {}
    if _sid[0] is None:
        _connect()
    try:
        out = _call_once(tool, args)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        _connect()
        out = _call_once(tool, args)
    if isinstance(out, dict) and "job" in out and "state" in out:
        while out["state"] == "running":
            out = _call_once("wait_for_job", {"job": out["job"], "timeout_secs": 600})
        if out["state"] != "finished":
            raise RuntimeError("RPFM %s job %s: %s" % (tool, out["state"], out))
        out = out.get("result", out)
    if tool in ("open_pack", "new_pack") and isinstance(out, dict) and out.get("key"):
        _opened.append(out["key"])
    if not quiet:
        print("  %-32s ok" % tool)
    return out


def ensure_game(deps=False):
    """Select warhammer_3 unless the shared session already has it. deps=True also needs
    the vanilla data: set_game loads it from the on-disk cache in ~3 s, and an outdated
    cache (after an RPFM or game update) is rebuilt here, once, ~85 s."""
    st = call("session_status")
    loaded = st["dependencies"]["vanilla_loaded"]
    if st["game"] != GAME or not st["schema_loaded"] or (deps and not loaded):
        st = call("set_game", {"game": GAME})
    if not st["schema_loaded"]:
        call("update_schemas")
        st = call("set_game", {"game": GAME})
    if deps and not st["dependencies"]["vanilla_loaded"]:
        print("  RPFM dependencies cache: %s - rebuilding (~85 s)"
              % st["dependencies"].get("error", "not loaded"))
        st = call("generate_dependencies_cache")
        if not st["dependencies"]["vanilla_loaded"]:
            raise SystemExit("RPFM could not load the vanilla data: %s" % st["dependencies"])
    return st


def open_pack(path):
    """Open a pack from disk; returns its key (a UUID, NOT the path as in v1).

    v2 refuses to open a path that is already open ("Close it first"). That is the normal
    case right after save_pack(path=...), when a script reopens what it saved to verify it:
    if the open copy is one THIS process opened or created, it is closed and the file
    reopened from disk. A copy someone else has open is left alone and the error stands -
    closing it would throw away their unsaved edits."""
    path = os.path.abspath(path)
    try:
        return call("open_pack", {"paths": [path]})["key"]
    except RuntimeError as e:
        if "already open" not in str(e):
            raise
        same = lambda p: p and os.path.normcase(os.path.normpath(p)) == os.path.normcase(path)
        mine = [p["key"] for p in call("session_status")["packs"]
                if same(p.get("path")) and p["key"] in _opened]
        if not mine:
            raise
        for key in mine:
            call("close_pack", {"pack": key})
        return call("open_pack", {"paths": [path]})["key"]


def new_pack(name=None):
    """A new empty pack; returns its key. `name` must end in .pack."""
    return call("new_pack", {"name": name} if name else {})["key"]


def exists(pack, path):
    """True if the open pack holds a file at exactly `path`."""
    files = call("list_files", {"source": {"pack": pack}, "path_prefix": path})["files"]
    return any(f["path"] == path for f in files)


def db(table, version):
    """create_file kind for a DB table at an explicit version."""
    return {"type": "db", "table_name": table, "version": version}


def vanilla_table(table):
    """Every game-files fragment of `table` ("..._tables"), decoded, in v1's
    get_tables_from_dependencies shape - {"VecRFile": [{"path", "data": {"Decoded": ...}}]} -
    which the .skilltree_cache/*.json files and read_vanilla_cache.py are written in.
    v2's decoded file wraps that same {"DB": {...}} one level down, in contents.data."""
    files = call("list_files", {"source": "game_files", "path_prefix": "db/%s/" % table,
                                "limit": 1000})["files"]
    out = []
    for f in files:
        d = call("read_file", {"file": {"source": "game_files", "path": f["path"]},
                               "format": "decoded"})
        out.append({"path": f["path"], "data": {"Decoded": d["contents"]["data"]}})
    return {"VecRFile": out}


@atexit.register
def _close_opened():
    for key in _opened:
        try:
            _call_once("close_pack", {"pack": key})
        except Exception:
            pass
