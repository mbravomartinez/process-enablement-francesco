#!/usr/bin/env bash
# First-run setup / preflight for the process-enablement plugin.
# Idempotent: safe to run before every command, and safe to re-run by hand.
#
#   setup.sh                  full report
#   setup.sh --quiet          only what changed or is wrong (CREATED / MISSING / BLOCKED)
#   setup.sh --status         report only — creates nothing, changes nothing
#   setup.sh --reset          show what a reset would destroy, then stop (never destroys)
#   setup.sh --reset --yes    do it: library moved aside to output.backup-<stamp>
#   setup.sh --reset --yes --purge   delete outright, no backup
#
# Output is tab-separated, one fact per line:
#   LIB<TAB><library dir>                       always — the exploration library root
#   CREATED<TAB>lib|registry                    0+ — what this run had to create
#   OK<TAB><tool><TAB><version>                 a required tool is present
#   MISSING<TAB><tool><TAB><what breaks + fix>  a needed tool is absent, not fatal
#   OPTIONAL<TAB><tool><TAB><when you need it>  absent and only sometimes needed
#   CORRUPT<TAB>registry<TAB><what was done>     an unreadable registry was moved aside
#   EXISTING<TAB><n><TAB><ids>                  --reset/--status: what is in the library now
#   WOULD-DESTROY<TAB><n> explorations<TAB>dir  --reset without --yes: nothing was touched
#   CONFIRM-REQUIRED                            --reset refused; re-run with --yes
#   RESET<TAB>backup<TAB><dir>                  library moved aside, recoverable
#   RESET<TAB>purged<TAB><dir>                  library deleted outright
#   READY                                       usable
#   BLOCKED<TAB><reason>                        not usable until fixed
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
quiet=0; status=0; reset=0; yes=0; purge=0
for a in "$@"; do
  case "$a" in
    --quiet)  quiet=1 ;;
    --status) status=1 ;;
    --reset)  reset=1 ;;
    --yes)    yes=1 ;;
    --purge)  purge=1 ;;
    *) echo "setup.sh: unknown option $a" >&2; exit 2 ;;
  esac
done

say() { [ "$quiet" -eq 1 ] || printf '%s\n' "$*"; }   # suppressed by --quiet
always() { printf '%s\n' "$*"; }                       # always printed

# --- the library: per-user, outside the plugin so a plugin update cannot wipe it ---
pe_home="${PE_HOME:-$HOME/.process-enablement}"
lib="$pe_home/output"
dry=0; { [ "$status" -eq 1 ] || { [ "$reset" -eq 1 ] && [ "$yes" -eq 0 ]; }; } && dry=1

if [ ! -d "$lib" ]; then
  if [ "$dry" -eq 1 ]; then always "LIB	$lib"; always "EXISTING	0	-"
                            [ "$reset" -eq 1 ] && always "RESET	nothing	no library to reset"
                            exit 0
  fi
  mkdir -p "$lib"; always "CREATED	lib"
fi
lib="$(cd "$lib" && pwd -P)"
always "LIB	$lib"

# --- what is in there right now (needed by --status and --reset) ---
# Sets INV_N / INV_IDS and prints the EXISTING line itself, so nothing is captured
# through a subshell (that once made the count read back as 0).
INV_N=0; INV_IDS="-"
inventory() {
  INV_N=0; INV_IDS="-"
  if [ -s "$lib/registry.json" ] && command -v python3 >/dev/null 2>&1; then
    local out
    out="$(REG="$lib/registry.json" python3 -c '
import json, os, sys
try:
    e = json.load(open(os.environ["REG"]))["explorations"]
except Exception:
    e = []
print(len(e))
print(",".join(x.get("id", "?") for x in e) or "-")
' 2>/dev/null || true)"
    if [ -n "$out" ]; then
      INV_N="$(printf '%s\n' "$out" | sed -n 1p)"
      INV_IDS="$(printf '%s\n' "$out" | sed -n 2p)"
    fi
  fi
  # Directories are the ground truth when there is no parser and no readable registry.
  # Pure bash — this path exists precisely because tooling may be missing.
  if [ "${INV_N:-0}" = "0" ]; then
    local d n=0 ids=""
    for d in "$lib"/*/; do
      [ -d "$d" ] || continue                 # no match: the glob stayed literal
      d="${d%/}"; d="${d##*/}"
      case "$d" in .*) continue ;; esac
      n=$((n + 1)); ids="${ids:+$ids,}$d"
    done
    if [ "$n" -gt 0 ]; then INV_N="$n"; INV_IDS="$ids"; fi
  fi
  [ -n "$INV_N" ] || INV_N=0
  always "EXISTING	$INV_N	$INV_IDS"
}

if [ "$reset" -eq 1 ]; then
  inventory
  if [ "$yes" -eq 0 ]; then
    always "WOULD-DESTROY	${INV_N} explorations	$lib"
    always "CONFIRM-REQUIRED"
    exit 3                                  # nothing was touched
  fi
  if [ "$purge" -eq 1 ]; then
    rm -rf "$lib"
    always "RESET	purged	$lib"
  else
    stamp="$(date +%Y%m%d-%H%M%S)"
    backup="$pe_home/output.backup-$stamp"
    mv "$lib" "$backup"
    always "RESET	backup	$backup"
  fi
  mkdir -p "$lib"
  printf '{\n  "schema_version": 1,\n  "explorations": []\n}\n' > "$lib/registry.json"
  always "CREATED	lib"
  always "CREATED	registry"
  say "READY"
  exit 0
fi

if [ "$status" -eq 1 ]; then inventory; fi

# Create the registry only when there is nothing to lose. An existing non-empty file is
# never rewritten: if python3 is absent we cannot parse it, and "unparseable" must never be
# inferred from "no parser" — that would clobber a real library. Corruption is reported.
reg="$lib/registry.json"
if [ "$status" -eq 1 ]; then
  [ -s "$reg" ] || always "MISSING	registry	no registry yet — run setup.sh (without --status) to create it"
elif [ ! -s "$reg" ]; then
  printf '{\n  "schema_version": 1,\n  "explorations": []\n}\n' > "$reg"
  always "CREATED	registry"
elif command -v python3 >/dev/null 2>&1 \
     && ! python3 -c 'import json,sys;json.load(open(sys.argv[1]))' "$reg" 2>/dev/null; then
  always "CORRUPT	registry	$reg is not valid JSON — moved aside, rebuild by re-running an exploration"
  mv "$reg" "$reg.corrupt.$$"
  printf '{\n  "schema_version": 1,\n  "explorations": []\n}\n' > "$reg"
  always "CREATED	registry"
fi

# --- the plugin's own scripts must be runnable (a zip/clone can lose the bits) ---
[ "$status" -eq 1 ] || chmod +x "$root"/scripts/*.sh "$root"/scripts/*.py "$root"/bin/* 2>/dev/null || true

# --- dependencies ---
blocked=""

if command -v python3 >/dev/null 2>&1; then
  say "OK	python3	$(python3 -c 'import platform;print(platform.python_version())' 2>/dev/null || echo '?')"
else
  always "MISSING	python3	required — it runs the chat bridge and the library index. Install Python 3 (brew install python)"
  blocked="python3 is required and not on PATH"
fi

if command -v claude >/dev/null 2>&1; then
  say "OK	claude	$(claude --version 2>/dev/null | head -1 || echo '?')"
else
  always "MISSING	claude	the chat on generated pages will not work — install Claude Code and reopen the shell"
fi

for t in "pdftotext:needed only to ingest scanned PDFs — brew install poppler" \
         "node:used to syntax-check a generated page's JS — optional"; do
  tool="${t%%:*}"; why="${t#*:}"
  if command -v "$tool" >/dev/null 2>&1; then say "OK	$tool	present"; else say "OPTIONAL	$tool	$why"; fi
done

if [ -n "$blocked" ]; then always "BLOCKED	$blocked"; exit 1; fi
say "READY"
