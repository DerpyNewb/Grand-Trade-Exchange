#!/usr/bin/env python3
"""Catch typo'd / wrong-separator CA API calls in mod Lua before packing.

Pairs with luac -p (which only catches syntax). Reads the mirrored CA docs in
Modding Files/reference/ca_script_docs_wh3/ as the source of truth.

  py tools/check_lua_api.py           # scan Modding Files/pack/script/
  py check_lua_api.py foo.lua bar.lua # scan named files
  py check_lua_api.py --selftest
"""
import glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ -> workspace root
DOCS = os.path.join(ROOT, "Modding Files", "reference", "ca_script_docs_wh3")
DEFAULT_SCAN = os.path.join(ROOT, "Modding Files", "pack", "script")

# receiver as written in mod Lua -> doc page receivers that define its members
SINGLETONS = {
    "cm":     {"cm", "campaign_manager"},
    "core":   {"core"},
    "bm":     {"bm", "battle_manager"},
    "common": {"common"},
}
SIG = re.compile(r'class="function_name"><strong><code>(.*?)</code>')
CALL = re.compile(r"\b(%s)\s*([:.])\s*(\w+)\s*\(" % "|".join(SINGLETONS))

# cm:<accessor>() returns an OBJECT whose members live on another doc page, and the
# receiver of the chained call is a CALL EXPRESSION - so CALL above cannot see it, which
# is the "cannot resolve non-singleton receivers" limit this tool has always carried.
# The Great Guilds panel shipped cm:get_campaign_ui_manager():get_char_selected(), which
# campaign_ui_manager does not have - CA's lib_campaign_ui.lua declares get_char_selected_cqi
# and nothing else beginning get_char - inside a pcall, so it answered nil forever and three
# things were dead from the day they shipped: Appoint Patron, Hire the Immortals and The
# Khan's Price. Found 2026-09-16 by reading CA's own lib, not by any check.
#
# Each entry is accessor -> the doc receiver named on that accessor's own "Returns:" line.
CHAINED = {
    "get_campaign_ui_manager": "campaign_ui_manager",
}
CHAINED_CALL = re.compile(
    r"\bcm\s*:\s*(%s)\s*\(\s*\)\s*([:.])\s*(\w+)\s*\(" % "|".join(CHAINED))


def index_docs():
    """doc receiver -> {member: separator}"""
    out = {}
    for f in glob.glob(os.path.join(DOCS, "**", "*.html"), recursive=True):
        with open(f, encoding="utf-8", errors="replace") as fh:
            for sig in SIG.findall(fh.read()):
                m = re.match(r"(\w+)([:.])(\w+)", re.sub(r"<.*?>", "", sig))
                if m:
                    out.setdefault(m.group(1), {})[m.group(3)] = m.group(2)
    return out


# string.find(s, pattern, init, PLAIN) and s:find(pattern, init, PLAIN).
# The 4th / 3rd argument being anything but nil or false is the plain flag, and ONE such call
# corrupts WH3's string subsystem process-wide: string.sub and string.find return garbage for
# every script in the game afterwards, nothing throws, and only restarting recovers it.
# Measured live 2026-09-08 (before=OK, after=BROKEN from a single call) and independently found
# 2026-08-21 by the wh3-mcp bridge, whose strings_ok() tripwire exists for this and nothing else.
# It broke the Zharr Exchange panel for four builds: the call sat in a MEMOISED accessor, so it
# fired on whichever name a session had not yet resolved, and the panel died at a different row
# every run while CA's own find_uicomponent began missing silently.
PLAIN_FIND = re.compile(
    r"""\bstring\s*\.\s*find\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)"""
    r"""|(?<![\w.])[\w\]\)"']\s*:\s*find\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)""")


def _plain_flag(call_args, dotted):
    """True when the plain argument is present and not nil/false.

    Split on top-level commas only - a pattern like "%(%d+,%d+%)" contains commas of its own,
    and a naive split would read one of those as the plain flag.
    """
    depth, parts, cur = 0, [], []
    for ch in call_args:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    want = 4 if dotted else 3
    if len(parts) < want:
        return False
    flag = parts[want - 1].strip()
    return flag not in ("", "nil", "false")


def _has_init(call_args, dotted):
    """True when an init (start offset) argument is present at all.

    WH3's string.find is not stock Lua's. Its FOURTH argument corrupts the string
    subsystem process-wide (above), and its THIRD silently finds nothing: the Iron
    Court walked its save string with string.find(packed, "%|", from) and every
    load in game came back with the whole string as the first field, so offices,
    governors, terms, standing, the record and the provinces were empty from turn
    one. Nothing threw, and the houses parsed, so it read as "the court forgets
    everything except who is in it". Shipped 2026-09-14.

    Walk the string with string.gmatch instead - `([^|]*)|` over `s .. "|"` yields
    every field, empty ones included.
    """
    depth, parts, cur = 0, [], []
    for ch in call_args:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    want = 3 if dotted else 2
    if len(parts) < want:
        return False
    return parts[want - 1].strip() not in ("", "nil")


# CALLS THAT DO NOT EXIST, but read as if they should. CA's own docs are the trap
# here: each of these appears ONLY inside a code EXAMPLE for a differently-named
# function, so grepping the docs "finds" it. Nothing in data_script.pack defines
# them, and there is no module page for the receiver, so the index below cannot
# reason about them at all - hence an explicit list.
#
# effect.get_localised_string: shown in the example on common.html, where the
# function actually being documented is common.get_localised_string. Called through
# a pcall - as any loc lookup must be - it fails silently and the caller falls back,
# so the symptom is raw loc keys drawn on screen rather than an error. Cost a live
# round trip on The Great Guilds panel, 2026-09-10.
NONEXISTENT = {
    "effect.get_localised_string": "does not exist; use common.get_localised_string",
}


def check(path, docs):
    hits = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            line = line.split("--", 1)[0]  # ponytail: naive, "--" inside a string literal wins
            for recv, sep, member in CALL.findall(line):
                seps = {docs.get(p, {}).get(member) for p in SINGLETONS[recv]}
                seps.discard(None)
                if not seps:
                    hits.append((n, "unknown", "%s%s%s()" % (recv, sep, member)))
                elif sep not in seps:
                    hits.append((n, "separator", "%s%s%s() -> use '%s'"
                                 % (recv, sep, member, seps.pop())))
            for acc, sep, member in CHAINED_CALL.findall(line):
                recv = CHAINED[acc]
                want = docs.get(recv, {}).get(member)
                if want is None:
                    hits.append((n, "unknown", "cm:%s()%s%s() - %s has no such member"
                                 % (acc, sep, member, recv)))
                elif sep != want:
                    hits.append((n, "separator", "cm:%s()%s%s() -> use '%s'"
                                 % (acc, sep, member, want)))
            for bad, fix in NONEXISTENT.items():
                if bad + "(" in line:
                    hits.append((n, "nonexistent", "%s() %s" % (bad, fix)))
            for dotted_args, method_args in PLAIN_FIND.findall(line):
                args, dotted = (dotted_args, True) if dotted_args else (method_args, False)
                if _plain_flag(args, dotted):
                    hits.append((n, "string-corruption",
                                 "string.find plain flag - corrupts the string subsystem "
                                 "process-wide for the whole game; drop it and escape the "
                                 "pattern instead"))
                elif _has_init(args, dotted):
                    hits.append((n, "find-init",
                                 "string.find init argument - WH3's find silently returns "
                                 "nil from an offset; walk the string with string.gmatch "
                                 "(\"([^|]*)|\" over s .. \"|\") instead"))
    return hits


def _detag(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def explain(member):
    """Every doc entry for a member name, as CA wrote it. [(file, text), ...]"""
    out = []
    for f in sorted(glob.glob(os.path.join(DOCS, "**", "*.html"), recursive=True)):
        with open(f, encoding="utf-8", errors="replace") as fh:
            html = fh.read()
        rel = os.path.relpath(f, DOCS)

        # Shape 1: a method page. The entry runs from its signature to the next
        # function_name, so the parameter text CANNOT be cut off the bottom -
        # which is the half that was being missed.
        for m in re.finditer(r'class="function_name"><strong><code>([^<]*?\b'
                             + re.escape(member) + r'\s*\()', html):
            start = m.start()
            nxt = html.find('class="function_name"', m.end())
            body = _detag(html[start:nxt if nxt > 0 else start + 3000])
            # the anchor attribute we matched on, and the next heading
            body = body.split(">", 1)[-1].split("<h3", 1)[0].strip()
            out.append((rel, body))

        # Shape 2: scripting_doc.html's flat table.
        flat = _detag(html)
        for m in re.finditer(r"Function: " + re.escape(member) + r" Description:", flat):
            nxt = flat.find("Function: ", m.end())
            out.append((rel, flat[m.start():nxt if nxt > 0 else m.start() + 1200]))
    return out


def selftest():
    docs = index_docs()
    assert docs["campaign_manager"].get("get_faction") == ":", "docs index missed cm:get_faction"
    assert docs["common"].get("get_localised_string") == ".", "missed common."
    tmp = os.path.join(ROOT, "_selftest.lua")
    open(tmp, "w").write(
        "cm:get_faction('x')\ncm:get_factionn('x')\ncm.get_faction('x')\n"
        "-- cm:bogus_in_comment()\n")
    try:
        got = [(n, k) for n, k, _ in check(tmp, docs)]
    finally:
        os.remove(tmp)
    assert got == [(2, "unknown"), (3, "separator")], got

    # THE CHAINED RECEIVER. Both halves watched - the real member must pass and the
    # shipped typo must fail, or the rule is decoration.
    tmp3 = os.path.join(ROOT, "_selftest_chain.lua")
    open(tmp3, "w").write(
        "local a = cm:get_campaign_ui_manager():get_char_selected_cqi()\n"           # 1 clean
        "local b = cm:get_campaign_ui_manager():get_char_selected()\n"               # 2 caught
        "local c = cm:get_campaign_ui_manager().get_char_selected_cqi()\n"           # 3 separator
        "local d = cm:get_campaign_ui_manager():get_selected_settlement_region()\n"  # 4 clean
    )
    try:
        chain = [(n, k) for n, k, _ in check(tmp3, docs)]
    finally:
        os.remove(tmp3)
    assert chain == [(2, "unknown"), (3, "separator")], chain

    # The plain flag, in both spellings, and the shapes that must NOT trip it.
    tmp2 = os.path.join(ROOT, "_selftest_find.lua")
    open(tmp2, "w").write(
        'local a = string.find(s, p, 1, true)\n'          # 1 caught, dotted
        'local b = s:find(p, 1, true)\n'                  # 2 caught, method
        'local c = string.find(s, p)\n'                   # 3 clean
        'local d = s:find(p)\n'                           # 4 clean
        'local e = string.find(s, p, 1)\n'                # 5 caught, init
        'local f = string.find(s, p, 1, false)\n'         # 6 caught, init
        'local g = string.find(s, "%%(%%d+,%%d+%%)", 1)\n'  # 7 caught, commas in the pattern
        'local h = string.find(s, "%%|")\n'               # 8 clean, no init
    )
    try:
        found = [(n, k) for n, k, _ in check(tmp2, docs)]
    finally:
        os.remove(tmp2)
    # 5, 6 and 7 WERE the clean cases and are findings now: the Iron Court's save
    # walk was case 7 exactly - a pattern and an offset - and it found nothing in
    # game for every load the mod ever did.
    assert found == [(1, "string-corruption"), (2, "string-corruption"),
                     (5, "find-init"), (6, "find-init"), (7, "find-init")], found

    # explain() must reach BOTH doc shapes, and must carry the parameter text -
    # the half a signature-only read drops.
    img = explain("SetImagePath")
    assert img, "explain() found no entry for SetImagePath"
    assert any("take the size of the old" in t for _, t in img), \
        "explain() cut off the parameter text, which is the whole reason it exists"
    prov = explain("province_name")
    assert any("Key of the province" in t for _, t in prov), \
        "explain() missed scripting_doc.html's flat-table shape"
    assert not explain("no_such_member_anywhere"), "explain() invented an entry"
    print("selftest ok (%d doc receivers indexed, plain-find and init detectors live, "
          "explain reaches both doc shapes)" % len(docs))


def main(argv):
    if "--selftest" in argv:
        selftest()
        return 0
    if "--explain" in argv:
        names = argv[argv.index("--explain") + 1:]
        if not names:
            print("usage: check_lua_api.py --explain <member> [<member> ...]")
            return 2
        missing = 0
        for name in names:
            found = explain(name)
            if not found:
                print("%s: NOT DOCUMENTED - if a CA doc does not define it, "
                      "nothing does" % name)
                missing += 1
                continue
            for rel, text in found:
                print("== %s  [%s]" % (name, rel))
                print("   " + text.replace(". ", ".\n   "))
                print()
        return 1 if missing else 0
    docs = index_docs()
    files = [a for a in argv if not a.startswith("--")] or glob.glob(os.path.join(DEFAULT_SCAN, "**", "*.lua"), recursive=True)
    bad = 0
    for f in files:
        for n, kind, what in check(f, docs):
            print("%s:%d: %s %s" % (f, n, kind, what))
            bad += 1
    print("%d file(s), %d suspect call(s)" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
