"""Decode any DB table out of a .pack with RPFM shut - CA's compressed db.pack included.

    py tools/read_vanilla_db.py <table>_tables [pack]      print every row (default pack: db.pack)
    py tools/read_vanilla_db.py --selftest

    from read_vanilla_db import load
    for path, version, rows in load(pack, "cai_construction_system_building_values_tables"): ...

A byte-GREP of db.pack finds nothing (memory wh3-byte-grep-reaches-text-not-db), but a decode
works: CA's entry is a u32 uncompressed size then a zstd frame (Workshop packs are usually raw),
then the DB binary - optional GUID marker, optional version marker, one u8, a u32 row count, and
rows in the field order of the matching version block in RPFM's schema_wh3.ron. The decoder
asserts it lands on the last byte, because a wrong version block otherwise misaligns silently.

Reaches tables .skilltree_cache never cached. Built 2026-09-24 to read
cai_construction_system_building_values (docs/sessions/HANDOFF_20260924_AI_BUILDING_VALUES.md).
"""
import os
import re
import struct
import sys

import zstandard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_pack_index import read  # noqa: E402

SCHEMA = os.path.join(os.environ.get("APPDATA", ""), "FrodoWazEre", "rpfm", "config",
                      "schemas", "schema_wh3.ron")
DB_PACK = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III\data\db.pack"
_schema = []


def defs(table):
    """{version: [(field, type), ...]} for one table, in binary (not ca_order) order."""
    if not _schema:
        _schema.append(open(SCHEMA, encoding="utf-8").read())
    s = _schema[0]
    i = s.find('"%s": [' % table)
    if i < 0:
        raise SystemExit("%s is not in %s" % (table, SCHEMA))
    blk = s[i:s.find('_tables": [', i + len(table) + 5)]
    out = {}
    for m in re.finditer(r"version: (\d+),\s*fields: \[(.*?)\n {16}\],", blk, re.S):
        out[int(m.group(1))] = re.findall(r'name: "([^"]+)",\s*field_type: ([A-Za-z0-9]+)',
                                          m.group(2))
    return out


def _unwrap(data):
    try:
        n = struct.unpack_from("<I", data)[0]
        return zstandard.ZstdDecompressor().decompress(data[4:], max_output_size=n)
    except zstandard.ZstdError:
        return data                                  # uncompressed (a Workshop pack)


FIXED = {"I32": ("<i", 4), "F32": ("<f", 4), "I16": ("<h", 2), "I64": ("<q", 8),
         "Boolean": ("<?", 1), "F64": ("<d", 8), "ColourRGB": ("<I", 4)}


def decode(data, table):
    p, ver = 0, 0
    if data[p:p + 4] == b"\xfd\xfe\xfc\xff":
        p += 6 + struct.unpack_from("<H", data, p + 4)[0] * 2
    if data[p:p + 4] == b"\xfc\xfd\xfe\xff":
        ver = struct.unpack_from("<I", data, p + 4)[0]
        p += 8
    p += 1
    count = struct.unpack_from("<I", data, p)[0]
    p += 4
    fields = defs(table)[ver]
    rows = []
    for _ in range(count):
        r = {}
        for name, t in fields:
            if t == "OptionalStringU8":
                p += 1
                if not data[p - 1]:
                    r[name] = ""
                    continue
                t = "StringU8"
            if t == "StringU8":
                n = struct.unpack_from("<H", data, p)[0]
                r[name] = data[p + 2:p + 2 + n].decode("utf-8")
                p += 2 + n
            elif t == "StringU16":
                n = struct.unpack_from("<H", data, p)[0] * 2
                r[name] = data[p + 2:p + 2 + n].decode("utf-16-le")
                p += 2 + n
            elif t in FIXED:
                fmt, size = FIXED[t]
                r[name] = struct.unpack_from(fmt, data, p)[0]
                p += size
            else:
                raise SystemExit("%s: field type %s not handled" % (table, t))
        rows.append(r)
    if p != len(data):
        raise SystemExit("%s v%d: decoded %d of %d bytes - wrong version block?"
                         % (table, ver, p, len(data)))
    return ver, rows


def load(pack, table):
    """[(path, version, rows)] for every fragment of `table` in `pack`."""
    return [(path,) + decode(_unwrap(data), table)
            for path, _comp, data in read(pack, "db/%s/" % table)]


def _selftest():
    # Two CA tables with OptionalStringU8, I32, StringU8 and F32 fields - counts as of 2026-09-24.
    (_, v, rows), = load(DB_PACK, "cai_construction_system_building_values_tables")
    assert v == 0 and len(rows) > 2000, (v, len(rows))
    war = [r for r in rows if r["building_chain"] == "wh3_dlc23_chd_military_war_machines"]
    assert war and war[0]["score_or_score_start_inclusive"] == 2500, war
    (_, _, lv), = load(DB_PACK, "cai_construction_system_synergy_levels_tables")
    med = [r for r in lv if r["key"] == "cai_cs_negative_level_medium"]
    assert med and abs(med[0]["relative_effect"] + 0.75) < 1e-6, med
    try:
        decode(_unwrap(read(DB_PACK, "db/cai_construction_system_building_values_tables/")[0][2])[:-1],
               "cai_construction_system_building_values_tables")
    except (SystemExit, struct.error, IndexError):
        pass
    else:
        raise AssertionError("a truncated table decoded without complaint")
    print("selftest ok - %d building values rows, truncation caught" % len(rows))


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        _selftest()
    elif len(sys.argv) in (2, 3):
        for path, v, rows in load(sys.argv[2] if len(sys.argv) == 3 else DB_PACK, sys.argv[1]):
            print("== %s v%d, %d rows" % (path, v, len(rows)))
            for r in rows:
                print("  " + "\t".join(str(x) for x in r.values()))
    else:
        raise SystemExit(__doc__)
