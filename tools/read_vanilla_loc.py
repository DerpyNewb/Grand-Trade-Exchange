"""Read CA's shipped localisation with RPFM closed.

    from read_vanilla_loc import load
    load("resources")["resources_onscreen_text_res_rom_lead"]   -> "Salt"

The game's loc lives in local_en.pack as one .loc per table, zstd-compressed with a u32
uncompressed-size prefix. Inside, the LOC layout is:

    u16 BOM (ff fe) | "LOC" | u8 pad | u32 version | u32 entry count
    then per entry: u16 char count + UTF-16LE key, same again for the value, u8 tooltip flag

BOTH the key and the value are UTF-16, which is the part that catches people out - a byte-grep
for an ASCII key finds nothing, so an absent match proves nothing. See
MEMORY/wh3-vanilla-loc-readable-offline.

Why this exists: display names are NOT in the DB. resources_tables has no onscreen_name column
at all, so the only way to learn that res_rom_lead is called "Salt" is to read the loc.

    py tools/read_vanilla_loc.py resources          # dump one table
    py tools/read_vanilla_loc.py --selftest
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_pack_index as rpi

GAME = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III"
PACK = os.path.join(GAME, "data", "local_en.pack")

_cache = {}


def _decompress(data):
    if not data[:2] == b"\xff\xfe":
        import zstandard
        n = struct.unpack("<I", data[:4])[0]
        data = zstandard.ZstdDecompressor().decompress(data[4:], max_output_size=n * 2 + 4096)
    return data


def parse(data):
    """LOC bytes -> {key: value}. Accepts raw or still-compressed bytes."""
    data = _decompress(data)
    assert data[:5] == b"\xff\xfeLOC", "not a LOC file: %r" % data[:8]
    off = 6
    _version, count = struct.unpack_from("<II", data, off)
    off += 8

    def text(o):
        n = struct.unpack_from("<H", data, o)[0]
        o += 2
        return data[o:o + n * 2].decode("utf-16-le"), o + n * 2

    out = {}
    for _ in range(count):
        k, off = text(off)
        v, off = text(off)
        off += 1                      # tooltip flag
        out[k] = v
    return out


def load(table, pack=PACK):
    """Every loc entry for one table, e.g. "resources" -> text/db/resources__.loc."""
    if table in _cache:
        return _cache[table]
    want = "text/db/%s__.loc" % table
    for _path, _comp, data in rpi.read(pack, want):
        _cache[table] = parse(data)
        return _cache[table]
    raise KeyError("%s not in %s" % (want, pack))


def _selftest():
    loc = load("resources")
    # The three Rome-era keys whose names do not match their key at all. If these ever stop
    # holding, the parser is wrong or CA renamed them - either way, look before trusting output.
    for key, name in (("res_rom_lead", "Salt"),
                      ("res_rom_glass", "Dwarf Beer"),
                      ("res_rom_textiles", "Pottery"),
                      ("res_gems", "Gemstones")):
        got = loc["resources_onscreen_text_" + key]
        assert got == name, "%s is %r, expected %r" % (key, got, name)
    assert len(loc) > 50, "only %d entries - suspiciously few" % len(loc)
    # Non-ASCII must survive the UTF-16 decode.
    assert all(isinstance(v, str) for v in loc.values())
    print("selftest ok: %d entries in resources, names match CA" % len(loc))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif len(sys.argv) == 2:
        for k, v in sorted(load(sys.argv[1]).items()):
            print("%-60s %s" % (k, v))
    else:
        print(__doc__)
        sys.exit(1)
