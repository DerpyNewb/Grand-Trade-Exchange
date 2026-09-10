# -*- coding: utf-8 -*-
"""Load the vanilla RPFM VecRFile JSON dumps in .skilltree_cache as dicts.

    from read_vanilla_cache import load
    rows, fields = load("unit_abilities")

Rows come back as list[dict] keyed by column name. Cell values in RPFM's dump are
one-key wrappers ({"StringU8": "x"} / {"Boolean": true} / ...), so unwrap them.
"""
import io, json, os

CACHE = r"G:\Modding for resources\.skilltree_cache"
_cache = {}


def _unwrap(cell):
    if isinstance(cell, dict) and len(cell) == 1:
        return next(iter(cell.values()))
    return cell


def load(name):
    """name without .json, e.g. 'unit_abilities'. Returns (rows, field_names)."""
    if name in _cache:
        return _cache[name]
    path = os.path.join(CACHE, name + ".json")
    blob = json.load(io.open(path, encoding="utf-8"))
    tbl = blob["VecRFile"][0]["data"]["Decoded"]["DB"]["table"]
    fields = [f["name"] for f in tbl["definition"]["fields"]]
    raw = tbl.get("table_data")
    if raw is None:  # structure drifted - show what is there rather than guessing
        raise SystemExit("no row key in table; keys=%s" % list(tbl))
    rows = [dict(zip(fields, [_unwrap(c) for c in r])) for r in raw]
    _cache[name] = (rows, fields)
    return rows, fields


def have(name):
    return os.path.exists(os.path.join(CACHE, name + ".json"))


if __name__ == "__main__":
    rows, fields = load("unit_abilities")
    assert len(rows) > 1000, len(rows)
    assert "key" in fields and "type" in fields, fields[:10]
    print("unit_abilities: %d rows, %d cols" % (len(rows), len(fields)))
    print("fields:", fields)
    print("sample:", json.dumps(rows[0], default=str)[:600])
