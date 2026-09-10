"""Read a .pack file index, and pull files out of it, WITHOUT RPFM.

RPFM (and its MCP server) is the only way to *decode* a DB table, but it is not needed to
answer "which packs ship this path" or "what is in this mod's Lua". The pack index is plain
bytes at a fixed offset, and mod packs from the Workshop ship uncompressed, so a file's data
can be sliced straight out by offset. CA's own packs compress their DB, so
`read()` on those returns compressed bytes for db/ paths - see
docs/sessions/COMPAT_ANCILLARIES_20260828.md and the `wh3-byte-grep-reaches-text-not-db`
memory. `.twui.xml` and `.lua` are plain text in both.

Format (PFH5/PFH6): 4-byte magic, u32 bitmask, u32 pack-file count, u32 pack-file index
size, u32 file count, u32 file index size, u32 timestamp. Bit 0x100 adds a 20-byte big
header; bit 0x40 puts a u32 timestamp on every index entry; bit 0x80 encrypts the index and
is refused here. Each index entry is u32 size, [u32 timestamp], u8 compression, then a
NUL-terminated path. File data follows the index in index order.

    py tools/read_pack_index.py <pack>                 list every path
    py tools/read_pack_index.py <pack> <substring>     dump matching files to stdout
    py tools/read_pack_index.py --selftest

Built 2026-08-28 for the Workshop compatibility survey - 527 packs, 93 GB, all readable.
"""
import os
import struct
import sys

BACKSLASH = chr(92)
NUL = bytes([0])


def entries(fp):
    """Yield (path, size, data_offset, compression_flag) for every file in the pack.

    Returns (open_handle, list). The handle is left open so read() can seek into it.
    """
    f = open(fp, "rb")
    magic = f.read(4)
    if magic not in (b"PFH5", b"PFH6"):
        f.close()
        raise ValueError("%s is not a PFH5/PFH6 pack (magic %r)" % (fp, magic))
    bitmask, _pack_count, pack_index_size, file_count, file_index_size = struct.unpack(
        "<5I", f.read(20))
    f.read(4)                                   # timestamp
    if bitmask & 0x100:                         # HAS_BIG_HEADER
        f.read(20)
    if bitmask & 0x80:                          # HAS_ENCRYPTED_INDEX
        f.close()
        raise ValueError("%s has an encrypted index" % fp)
    f.read(pack_index_size)                     # dependency pack names
    index = f.read(file_index_size)
    stamped = bool(bitmask & 0x40)              # HAS_INDEX_WITH_TIMESTAMPS

    out = []
    offset = f.tell()
    pos = 0
    for _ in range(file_count):
        size = struct.unpack_from("<I", index, pos)[0]
        pos += 4
        if stamped:
            pos += 4
        compression = index[pos]
        pos += 1
        end = index.index(NUL, pos)
        path = index[pos:end].decode("utf-8", "replace").replace(BACKSLASH, "/")
        pos = end + 1
        out.append((path, size, offset, compression))
        offset += size
    return f, out


def paths(fp):
    """Every path in the pack, forward-slashed. Closes the handle."""
    f, es = entries(fp)
    f.close()
    return [e[0] for e in es]


def read(fp, substring):
    """[(path, compression, data)] for every path containing `substring` (case-insensitive).

    compression != 0 means the bytes are compressed and need RPFM to decode.
    """
    f, es = entries(fp)
    hits = []
    needle = substring.lower()
    for path, size, offset, compression in es:
        if needle in path.lower():
            f.seek(offset)
            hits.append((path, compression, f.read(size)))
    f.close()
    return hits


def _selftest():
    """Round-trip against a pack in this workspace, and against a CA pack."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ours = os.path.join(root, "Modding Files", "Modpacks",
                        "derpy_chd_house_ancillaries.pack")
    assert os.path.exists(ours), "expected %s" % ours

    ps = paths(ours)
    # Index sanity: the pack ships DB fragments, loc, Lua and our own twui files.
    assert "db/ancillaries_tables/derpy_chd_house_anc_items" in ps, "DB fragment missing"
    assert "script/campaign/mod/zzz_derpy_chd_commission.lua" in ps, "commission Lua missing"
    assert "ui/campaign ui/derpy_chd_rite_costs.twui.xml" in ps, "rite costs twui missing"
    assert not any(p.startswith("/") or BACKSLASH in p for p in ps), "path separators wrong"

    # Extraction sanity: our own Lua is uncompressed and parses as text we recognise.
    hits = read(ours, "zzz_derpy_chd_commission.lua")
    assert len(hits) == 1, "expected one match, got %d" % len(hits)
    path, compression, data = hits[0]
    assert compression == 0, "our pack should be uncompressed, got flag %d" % compression
    text = data.decode("utf-8")
    assert "button_rituals" in text, "extracted bytes are not the commission Lua"
    assert len(data) > 10000, "suspiciously short extraction: %d bytes" % len(data)

    # Offsets must be contiguous and land inside the file.
    f, es = entries(ours)
    f.close()
    size_on_disk = os.path.getsize(ours)
    last_path, last_size, last_offset, _ = es[-1]
    assert last_offset + last_size == size_on_disk, (
        "index offsets do not reach the end of the file: %d + %d != %d"
        % (last_offset, last_size, size_on_disk))

    # A CA pack must open too - only its DB comes back compressed.
    ca = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III\data\ui3.pack"
    if os.path.exists(ca):
        ca_paths = paths(ca)
        assert any(p.endswith(".twui.xml") for p in ca_paths), "no twui in ui3.pack"
    else:
        print("  (skipped ui3.pack check - not at %s)" % ca)

    print("selftest ok - %d paths, extraction and offsets verified" % len(ps))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif len(sys.argv) == 2:
        for p in paths(sys.argv[1]):
            print(p)
    elif len(sys.argv) == 3:
        for path, compression, data in read(sys.argv[1], sys.argv[2]):
            print("### %s  compression=%d  bytes=%d" % (path, compression, len(data)))
            if compression:
                print("    (compressed - open it in RPFM)")
            else:
                sys.stdout.write(data.decode("utf-8", "replace"))
    else:
        print(__doc__)
        sys.exit(1)
