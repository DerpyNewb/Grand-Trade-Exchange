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
            for dotted_args, method_args in PLAIN_FIND.findall(line):
                args, dotted = (dotted_args, True) if dotted_args else (method_args, False)
                if _plain_flag(args, dotted):
                    hits.append((n, "string-corruption",
                                 "string.find plain flag - corrupts the string subsystem "
                                 "process-wide for the whole game; drop it and escape the "
                                 "pattern instead"))
    return hits


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

    # The plain flag, in both spellings, and the shapes that must NOT trip it.
    tmp2 = os.path.join(ROOT, "_selftest_find.lua")
    open(tmp2, "w").write(
        'local a = string.find(s, p, 1, true)\n'          # 1 caught, dotted
        'local b = s:find(p, 1, true)\n'                  # 2 caught, method
        'local c = string.find(s, p)\n'                   # 3 clean
        'local d = s:find(p)\n'                           # 4 clean
        'local e = string.find(s, p, 1)\n'                # 5 clean, no flag
        'local f = string.find(s, p, 1, false)\n'         # 6 clean, explicit false
        'local g = string.find(s, "%%(%%d+,%%d+%%)", 1)\n'  # 7 clean, commas in the pattern
    )
    try:
        found = [(n, k) for n, k, _ in check(tmp2, docs)]
    finally:
        os.remove(tmp2)
    assert found == [(1, "string-corruption"), (2, "string-corruption")], found
    print("selftest ok (%d doc receivers indexed, plain-find detector live)" % len(docs))


def main(argv):
    if "--selftest" in argv:
        selftest()
        return 0
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
