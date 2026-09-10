"""Find ALL_CAPS Lua names that are read but never declared.

Flow B shipped dead because BINDING and BINDING_RITE were Python constants in
gen_commission_dilemmas.py, used to build the DB rows but never interpolated into the
Lua template. In Lua an undeclared global is nil, not an error, so every branch that
compared against them was silently unreachable - luac -p passes, check_lua_api.py
passes, and the game logs nothing at all.
"""
import io
import os
import re
import sys
import glob

BS = chr(92)
STRING = '"(?:[^"' + BS + BS + ']|' + BS + BS + '.)*"'
KNOWN = {"RITUAL_STATUS"}


LONG_OPEN = re.compile(r"\[(=*)\[")


def _blank(src):
    """Strings and comments out, in ONE left-to-right pass.

    IT HAS TO BE ONE PASS, and a regex sequence cannot be. Stripping comments first eats the
    `--` inside a string literal - `EX.emit("---- state dump ----")` becomes `EX.emit("` and
    the unterminated quote then swallows the rest of the file, so every ALL_CAPS word after it
    is reported as an undeclared global. Stripping strings first has the mirror fault: an
    apostrophe in a comment opens a string that never closes. Both are false positives on
    correct code, on a check that REFUSES TO PACK - and this file's own comment already says
    what happens then: the next person bypasses the gate.

    Found 2026-09-08, when the Exchange's debug dump added `"---- state dump ----"`.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == "-" and src.startswith("--", i):
            m = LONG_OPEN.match(src, i + 2)
            if m:                                   # --[[ ... ]] / --[==[ ... ]==]
                close = "]" + m.group(1) + "]"
                k = src.find(close, m.end())
                i = n if k < 0 else k + len(close)
            else:                                   # -- to end of line; the newline stays
                k = src.find("\n", i + 2)
                i = n if k < 0 else k
            out.append(" ")
            continue
        if c in "\"'":                              # short string, backslash escapes, no
            j = i + 1                               # raw newline
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            out.append('""')
            i = j + 1
            continue
        m = LONG_OPEN.match(src, i)
        if m:                                       # [[ ... ]] through [==[ ... ]==]. The
            close = "]" + m.group(1) + "]"          # level has to match the opening one: the
            k = src.find(close, m.end())            # victory routes hold mission blocks as
            out.append('""')                        # [==[ ]==], and DESTROY_FACTION inside
            i = n if k < 0 else k + len(close)      # one is parsed by the ENGINE, never Lua
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip(src):
    code = _blank(src)
    declared = set()
    for m in re.finditer(r"\blocal\s+(?:function\s+)?([A-Za-z0-9_,\s]+?)\s*(?:=|\()", code):
        for n in m.group(1).split(","):
            declared.add(n.strip())
    # A name followed by a single '=' is an assignment TARGET, not a read: a table
    # constructor key (`BINDING_MSG = { UNIQUE = "..." }`) and a plain global assignment
    # both land here, and neither is the bug this looks for. Without it every ALL_CAPS
    # table key is reported and the packer refuses to build on a false positive - which
    # is worse than not checking, because the next person just bypasses the gate.
    declared |= set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\s*=(?!=)", code))
    used = set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", code))
    return code, declared, used


def undeclared(src, elsewhere=()):
    """ALL_CAPS names this source reads that nothing declares.

    `elsewhere` is what the REST OF THE PACK declares. A pack global legitimately crosses
    files - the Zharr Exchange ships its 781-entry EX_PRODUCTION map as its own generated
    script, because it is data - and a per-file check calls that a finding on every run.
    The bug this exists for is a name declared NOWHERE, so nowhere is what it has to mean;
    flagging a real cross-file global instead just teaches people to bypass the gate.
    """
    _code, declared, used = _strip(src)
    return sorted(u for u in used - declared - set(elsewhere) - KNOWN
                  if not u.startswith("_"))


def declared_in(src):
    """What this source declares, for the cross-file union."""
    return _strip(src)[1]


def main(paths):
    bad = 0
    srcs = dict((p, io.open(p, encoding="utf-8").read()) for p in paths)
    decl = dict((p, declared_in(src)) for p, src in srcs.items())
    for path in paths:
        # The union over the OTHER files. A file's own declarations are already handled, so
        # including it in its own "elsewhere" would change nothing.
        elsewhere = set()
        for other, names in decl.items():
            if other != path:
                elsewhere |= names
        found = undeclared(srcs[path], elsewhere)
        if found:
            bad += 1
            print("%-46s %s" % (os.path.basename(path), ", ".join(found)))
    print("%d file(s), %d with undeclared names" % (len(paths), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        # the exact shape that shipped: read in a comparison, never declared
        assert undeclared('local A = 1\nif rk == BINDING then end') == ["BINDING"]
        assert undeclared('local BINDING = "x"\nif rk == BINDING then end') == []
        # an ALL_CAPS table-constructor key is a write, not a read
        assert undeclared('local T = { UNIQUE = "a" }\nreturn T[k]') == []
        # ...but a real missing declaration still fires next to one
        assert undeclared(
            'local T = { UNIQUE = "a" }\nif x == MISSING then end') == ["MISSING"]
        # a name that only ever appears inside a string is not a read
        assert undeclared('local a = "BINDING"') == []
        # a global declared in ANOTHER pack file is not a finding...
        assert undeclared('if x == EX_PRODUCTION then end',
                          declared_in('EX_PRODUCTION = { }')) == []
        # ...and one no file anywhere declares still is
        assert undeclared('if x == EX_MISSING then end',
                          declared_in('EX_PRODUCTION = { }')) == ["EX_MISSING"]
        # A '--' INSIDE A STRING IS NOT A COMMENT. Stripping comments first ate the rest
        # of the line, left an unterminated quote, and reported every ALL_CAPS word after
        # it as undeclared - on a check that refuses to pack.
        assert undeclared('local a = "---- MISSING ----"') == []
        assert undeclared('EX.emit("---- dump ----")\nif x == REAL then end') == ["REAL"]
        # ...and the mirror fault, which is why strings-first is not the fix either: an
        # apostrophe in a COMMENT must not open a string.
        assert undeclared("-- don't strip this\nif x == REAL then end") == ['REAL']
        # A long comment still goes, and a long string still shields what is inside it.
        assert undeclared('--[[ MISSING ]]\nlocal s = [==[ ALSO_MISSING ]==]') == []
        assert undeclared('--[[' + chr(10) + 'MISSING' + chr(10) + ']]' + chr(10) + 'local x = 1') == []
        # AN ESCAPED QUOTE DOES NOT END THE STRING. Without the escape skip the scanner
        # closes at the backslash-quote and reads the rest of the literal as code.
        assert undeclared('local a = "A \\\" MISSING"') == []
        print("selftest ok")
        sys.exit(0)
    sys.exit(main(args or sorted(glob.glob("Modding Files/pack/script/campaign/mod/*.lua"))))
