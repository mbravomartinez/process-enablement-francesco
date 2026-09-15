#!/usr/bin/env python3
"""pe-splice.py — build a page by splicing small blocks into a copy of the reference mock.

Why this exists: the rendered page is ~120 KB. Emitting it in one tool call keeps a
stream silent long enough for the client's idle timeout (observed: 180 s) to drop it,
losing the whole render. The mock already holds the CSS, the JS and both base64 images,
and a render only ever changes the data blocks and a little markup — so copy the mock
once on disk and replace those blocks one at a time, each a few KB.

    pe-splice.py --base assets/reference-mock.html --out index.html \
                 --const STEPS=.blocks/steps.js \
                 --const PROBS=.blocks/probs.js \
                 --region flowchain=.blocks/flow.html \
                 --check

--const NAME=FILE   replaces the initializer of a top-level `const NAME = …;`
                    (or `let`/`var`) with FILE's contents, matching brackets so
                    nested objects and arrays are handled correctly.
--region NAME=FILE  replaces everything between `<!-- PE:NAME -->` and
                    `<!-- /PE:NAME -->` with FILE's contents.
--set NAME=VALUE    replaces a scalar const with a literal (e.g. CURRENT_LANG='en').
--check             extracts every <script> body and runs `node --check` on it.

Every anchor must appear exactly once. A missing or duplicated anchor is a hard error
and nothing is written, so a half-spliced page can never reach the library.
"""
import argparse, os, re, subprocess, sys, tempfile

OPEN, CLOSE = "{[(", "}])"


def scan_literal(src, i):
    """From the first char of a const's initializer at src[i], return the index of the
    terminating semicolon.

    Scanning to the depth-0 semicolon rather than to a matched bracket pair is what makes
    arrow functions work: `const f = (a, b) => …;` opens with a paren whose match closes
    after the parameter list, long before the value ends. Strings, template literals and
    comments are tracked so a semicolon inside any of them is not mistaken for the end.
    """
    depth, j, quote, line_comment, block_comment = 0, i, None, False, False
    while j < len(src):
        c = src[j]
        nxt = src[j + 1] if j + 1 < len(src) else ""
        if line_comment:
            if c == "\n":
                line_comment = False
        elif block_comment:
            if c == "*" and nxt == "/":
                block_comment = False
                j += 1
        elif quote:
            if c == "\\":
                j += 2
                continue
            if c == quote:
                quote = None
        elif c == "/" and nxt == "/":
            line_comment = True
            j += 1
        elif c == "/" and nxt == "*":
            block_comment = True
            j += 1
        elif c in "\"'`":
            quote = c
        elif c in OPEN:
            depth += 1
        elif c in CLOSE:
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced closing bracket before the initializer ended")
        elif c == ";" and depth == 0:
            return j
        j += 1
    raise ValueError("initializer never terminated — no semicolon found at depth 0")


def replace_const(src, name, body):
    pat = re.compile(r"^([ \t]*)(const|let|var)([ \t]+)" + re.escape(name) + r"([ \t]*)=([ \t]*)", re.M)
    hits = list(pat.finditer(src))
    if not hits:
        raise SystemExit(f"ERROR\tconst {name}\tanchor not found")
    if len(hits) > 1:
        raise SystemExit(f"ERROR\tconst {name}\tanchor found {len(hits)} times — must be unique")
    m = hits[0]
    start = m.end()
    end = scan_literal(src, start)
    return src[:start] + body.strip() + src[end:], end - start, len(body.strip())


def replace_region(src, name, body):
    o, c = f"<!-- PE:{name} -->", f"<!-- /PE:{name} -->"
    if src.count(o) != 1 or src.count(c) != 1:
        raise SystemExit(
            f"ERROR\tregion {name}\tmarkers must appear exactly once "
            f"(open={src.count(o)}, close={src.count(c)})"
        )
    a = src.index(o) + len(o)
    b = src.index(c)
    if b < a:
        raise SystemExit(f"ERROR\tregion {name}\tclose marker precedes open marker")
    return src[:a] + "\n" + body.strip("\n") + "\n" + src[b:], b - a, len(body)


def check_js(html):
    if not any(os.access(os.path.join(p, "node"), os.X_OK) for p in os.environ.get("PATH", "").split(":")):
        return "SKIP\tnode not on PATH — JS not syntax-checked"
    bodies = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    if not bodies:
        return "SKIP\tno inline <script> found"
    for n, body in enumerate(bodies, 1):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(body)
            path = fh.name
        try:
            r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        finally:
            os.unlink(path)
        if r.returncode != 0:
            first = (r.stderr.strip().splitlines() or ["unknown error"])
            return "FAIL\tscript %d: %s" % (n, " / ".join(first[:4]))
    return "OK\t%d inline script block(s) parse" % len(bodies)


def main():
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--const", action="append", default=[], metavar="NAME=FILE")
    ap.add_argument("--region", action="append", default=[], metavar="NAME=FILE")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = open(a.base, encoding="utf-8").read()
    before = len(src)
    report = []

    for spec in a.const:
        name, _, path = spec.partition("=")
        src, old, new = replace_const(src, name, open(path, encoding="utf-8").read())
        report.append(f"const\t{name}\t{old} -> {new} bytes")
    for spec in a.region:
        name, _, path = spec.partition("=")
        src, old, new = replace_region(src, name, open(path, encoding="utf-8").read())
        report.append(f"region\t{name}\t{old} -> {new} bytes")
    for spec in a.set:
        name, _, value = spec.partition("=")
        src, old, new = replace_const(src, name, value)
        report.append(f"set\t{name}\t= {value}")

    verdict = check_js(src) if a.check else "SKIP\t--check not requested"
    if verdict.startswith("FAIL"):
        print("\n".join(report))
        print("JS\t" + verdict)
        raise SystemExit("ABORTED\tnothing written — fix the block and re-run")

    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(src)
    os.replace(tmp, a.out)

    print("\n".join(report))
    print("JS\t" + verdict)
    print(f"WROTE\t{a.out}\t{before} -> {len(src)} bytes")


if __name__ == "__main__":
    main()
