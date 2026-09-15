#!/usr/bin/env bash
# Fast library front-end for /process-enablement:library.
# Resolves LIB, validates the registry against disk, and opens a page — no
# exploring by the model, minimal output.
#
#   library.sh list [filter]        compact, machine-readable listing
#   library.sh open [id|latest] [lang]  start the chat bridge, open in Chrome
#                                   (no id = newest usable entry)
#
# list output (tab-separated, newest `updated` first):
#   LIB<TAB><resolved library dir>
#   ALSO<TAB><other candidate dirs holding entries>          (0+ lines)
#   E<TAB>id<TAB>process<TAB>industry<TAB>companies<TAB>langs-ok<TAB>langs-stale<TAB>steps/deviations/kpis/terms<TAB>created<TAB>updated<TAB>grounded|ungrounded
#   STALE<TAB>id<TAB>reason                                  (0+ lines)
#   NOMATCH<TAB><filter>   filter matched nothing; all entries follow anyway
#   EMPTY                                                    (no usable entry)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

resolve_lib() {
  local first="" c seen=""
  for c in "${PE_HOME:-$HOME/.process-enablement}/output" \
           "$root/output"; do
    c="$(cd "$c" 2>/dev/null && pwd -P)" || continue
    case " $seen " in *" $c "*) continue ;; esac
    seen="$seen $c"
    [ -s "$c/registry.json" ] || continue
    python3 -c "import json,sys;sys.exit(0 if json.load(open(sys.argv[1]))['explorations'] else 1)" \
      "$c/registry.json" 2>/dev/null || continue
    if [ -z "$first" ]; then first="$c"; echo "LIB	$c"; else echo "ALSO	$c"; fi
  done
  [ -n "$first" ] || { echo "EMPTY"; return 1; }
  printf '%s' "$first" > /dev/null
}

lib_dir() {
  local c
  for c in "${PE_HOME:-$HOME/.process-enablement}/output" \
           "$root/output"; do
    c="$(cd "$c" 2>/dev/null && pwd -P)" || continue
    [ -s "$c/registry.json" ] || continue
    python3 -c "import json,sys;sys.exit(0 if json.load(open(sys.argv[1]))['explorations'] else 1)" \
      "$c/registry.json" 2>/dev/null || continue
    echo "$c"; return 0
  done
  return 1
}

cmd_list() {
  local filter="${1:-}"
  resolve_lib || return 0
  local lib; lib="$(lib_dir)"
  LIB="$lib" FILTER="$filter" python3 - <<'PY'
import json, os
lib, filt = os.environ["LIB"], os.environ["FILTER"].strip().lower()
reg = json.load(open(os.path.join(lib, "registry.json")))
rows, stale = [], []
for e in reg.get("explorations", []):
    d = os.path.join(lib, e.get("path", ""))
    if not os.path.isdir(d):
        stale.append((e.get("id", "?"), "directory missing")); continue
    ok, bad = [], []
    for l in e.get("languages", []):
        (ok if os.path.isfile(os.path.join(d, l.get("file", ""))) else bad).append(l.get("code", "?"))
    if bad:
        stale.append((e.get("id", "?"), "no file for: " + ",".join(bad)))
    if not ok:
        continue
    hay = " ".join([e.get("process", ""), e.get("industry", "")] + e.get("companies", [])).lower()
    rows.append((e, ok, bad, bool(filt) and filt in hay))
rows.sort(key=lambda r: r[0].get("updated", ""), reverse=True)

# A filter that matches nothing is NOT an empty library: report the miss and
# fall back to every usable entry, so the caller can still open one.
if filt:
    hits = [r for r in rows if r[3]]
    if hits:
        rows = hits
    elif rows:
        print("\t".join(["NOMATCH", filt]))

for e, ok, bad, _hit in rows:
    print("\t".join([
        "E", e.get("id", ""), e.get("process", ""), e.get("industry", ""),
        ",".join(e.get("companies", [])) or "-",
        ",".join(ok), ",".join(bad) or "-",
        "/".join(str(e.get(k, "?")) for k in ("steps", "problems", "kpis", "terms")),
        e.get("created", "?"), e.get("updated", "?"),
        "grounded" if e.get("context") else "ungrounded",
    ]))
for i, why in stale:
    print("\t".join(["STALE", i, why]))
if not rows:
    print("EMPTY")
PY
}

# Make sure exactly one usable bridge serves $1, and leave $port/$health set.
# Both entry points use this -- the generator must not start bridges by hand, which
# is how three processes ended up on three ports serving two directories.
ensure_bridge() {
# One probe of all three ports decides everything: reuse the bridge already
# serving this exact directory (compared as a resolved path, not as a string),
# retire any bridge whose exploration is gone -- it can only ever answer
# no-source-page, and while it holds the lowest port the page finds it first --
# and otherwise report the first genuinely free port.
local out="$1" plan line reaped
port=""; health=""
plan="$(OUT="$out" python3 - <<'PROBE'
import json, os, signal, subprocess, urllib.request

want = os.path.realpath(os.environ["OUT"])
free, reuse = [], None
for port in (8787, 8788, 8789):
  try:
      with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=1) as r:
          h = json.load(r)
  except Exception:
      free.append(port); continue
  d = h.get("dir", "")
  usable = bool(d) and os.path.isfile(os.path.join(d, "index.html"))
  if usable and os.path.realpath(d) == want:
      reuse = (port, json.dumps(h)); break
  if not usable:
      try:
          pids = subprocess.run(["lsof", "-ti", "tcp:%d" % port, "-sTCP:LISTEN"],
                                capture_output=True, text=True, timeout=5).stdout.split()
          for pid in pids:
              os.kill(int(pid), signal.SIGTERM)
      except Exception:
          continue
      free.append(port)
      print("REAPED\t%d\t%s" % (port, d or "?"))
if reuse:
  print("REUSE\t%d\t%s" % reuse)
elif free:
  print("FREE\t%d" % free[0])
else:
  print("FULL")
PROBE
)"
reaped="$(printf '%s\n' "$plan" | grep '^REAPED' || true)"
if [ -n "$reaped" ]; then printf '%s\n' "$reaped"; fi
line="$(printf '%s\n' "$plan" | grep -E '^(REUSE|FREE|FULL)' | head -1 || true)"
case "$line" in
  REUSE*)
    port="$(printf '%s' "$line" | cut -f2)"
    health="$(printf '%s' "$line" | cut -f3-)"
    ;;
  FREE*)
    port="$(printf '%s' "$line" | cut -f2)"
    nohup python3 "$root/scripts/chat-bridge.py" --dir "$out" --port "$port" \
      > "$out/.chat-bridge.log" 2>&1 &
    # Retry: a single probe after 1s reports a false "unreachable" on slow starts.
    for i in 1 2 3 4 5; do
      health="$(curl -sf --max-time 2 "http://127.0.0.1:$port/health" || true)"
      [ -n "$health" ] && break
      sleep 1
    done
    ;;
  *)
    echo "PORTS-FULL	8787,8788,8789 all serve other explorations"
    ;;
esac
}

cmd_open() {
  # No id (or "latest") means: open the newest usable entry. The page has its
  # own library switcher, so landing on one real process is always better than
  # asking which one.
  local id="${1:-latest}" lang="${2:-}"
  local lib; lib="$(lib_dir)" || { echo "EMPTY"; return 1; }
  local out file resolved
  resolved="$(LIB="$lib" ID="$id" LANG_="$lang" python3 - <<'PY'
import json, os, sys
lib, wid, want = os.environ["LIB"], os.environ["ID"], os.environ["LANG_"]
reg = json.load(open(os.path.join(lib, "registry.json")))
cands = reg.get("explorations", [])
if wid and wid != "latest":
    cands = [e for e in cands if wid in (e.get("id"), e.get("path"))]
else:
    cands = sorted(cands, key=lambda e: e.get("updated", ""), reverse=True)
for e in cands:
    langs = [l for l in e.get("languages", [])
             if os.path.isfile(os.path.join(lib, e.get("path", ""), l.get("file", "")))]
    if want:
        langs = [l for l in langs if l.get("code") == want]
    if langs:
        print(e["path"] + "\t" + langs[0]["file"]); sys.exit(0)
sys.exit(1)
PY
)" || { echo "NOFILE	$id	$lang"; return 1; }
  out="$lib/${resolved%%$'\t'*}"
  file="${resolved##*$'\t'}"

  local port="" health=""
  ensure_bridge "$out"
  echo "LIB	$lib"
  echo "OPENED	$out/$file"
  echo "PORT	${port:-none}"
  echo "HEALTH	${health:-unreachable}"
  # Chrome by preference; fall back to the default browser if it is absent.
  if open -a "Google Chrome" "$out/$file" 2>/dev/null; then
    echo "BROWSER	Google Chrome"
  else
    open "$out/$file"
    echo "BROWSER	default"
  fi
}

cmd_bridge() {
  local out="${1:?usage: library.sh bridge <exploration-dir>}"
  out="$(cd "$out" && pwd -P)" || { echo "NODIR	$1"; return 1; }
  local port="" health=""
  ensure_bridge "$out"
  echo "PORT	${port:-none}"
  echo "HEALTH	${health:-unreachable}"
}

case "${1:-list}" in
  list) shift || true; cmd_list "${1:-}" ;;
  open) shift; cmd_open "$@" ;;
  bridge) shift; cmd_bridge "$@" ;;
  *) echo "usage: library.sh list [filter] | open [id|latest] [lang] | bridge <dir>" >&2; exit 2 ;;
esac
