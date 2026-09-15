#!/usr/bin/env bash
# pe-parts.sh — assemble a large Markdown artifact from small, individually written parts.
#
# Why this exists: emitting a 40–60 KB file in one tool call keeps a stream silent long
# enough for the client's idle timeout (observed: 180 s) to drop it, losing the whole
# file. Writing one section at a time keeps every call short, and makes a retry cost one
# section instead of everything.
#
#   pe-parts.sh new      <target>                 # start (or reset) the part set
#   pe-parts.sh put      <target> <NN-name>       # body on stdin -> one part
#   pe-parts.sh list     <target>                 # what exists so far, with sizes
#   pe-parts.sh assemble <target>                 # concatenate in NN order -> target
#   pe-parts.sh drop     <target>                 # delete the part set (after assemble)
#
# Parts live in <dir>/.parts/<basename>/ and are joined in lexical order, so name them
# with a two-digit prefix: 01-purpose, 02-landscape, 03-objects, … A single lowercase
# letter may follow the digits to split one long section across calls: 08a-steps-1-5,
# 08b-steps-6-9 — lexical order keeps them together and in sequence.
# `put` overwrites the part of the same name, so re-running a failed section is safe and
# never duplicates content.
set -euo pipefail

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 2 ] || usage

cmd=$1; target=$2
dir=$(cd "$(dirname "$target")" && pwd)
base=$(basename "$target")
parts="$dir/.parts/$base"

case "$cmd" in
  new)
    rm -rf "$parts"; mkdir -p "$parts"
    echo "PARTS	$parts	reset"
    ;;
  put)
    [ $# -eq 3 ] || usage
    name=$3
    case "$name" in
      [0-9][0-9]-*|[0-9][0-9][a-z]-*) ;;
      *) echo "ERROR	part name must start NN- or NNx- (got '$name')" >&2; exit 1 ;;
    esac
    mkdir -p "$parts"
    cat > "$parts/$name.md"
    printf 'PUT\t%s\t%s bytes\n' "$name" "$(wc -c < "$parts/$name.md" | tr -d ' ')"
    ;;
  list)
    [ -d "$parts" ] || { echo "NONE	no part set for $base"; exit 0; }
    for f in "$parts"/*.md; do
      [ -e "$f" ] || { echo "EMPTY	part set exists but holds nothing"; exit 0; }
      printf '%s\t%s bytes\t%s lines\n' "$(basename "${f%.md}")" \
        "$(wc -c < "$f" | tr -d ' ')" "$(wc -l < "$f" | tr -d ' ')"
    done
    ;;
  assemble)
    [ -d "$parts" ] || { echo "ERROR	no part set for $base — run 'new' first" >&2; exit 1; }
    set -- "$parts"/*.md
    [ -e "$1" ] || { echo "ERROR	part set is empty, refusing to write an empty $base" >&2; exit 1; }
    python3 - "$target" "$@" <<'PY'
import sys
target, parts = sys.argv[1], sys.argv[2:]
blocks = []
for f in parts:
    body = open(f, encoding='utf-8').read().rstrip('\n')
    if body.strip():
        blocks.append(body)
open(target, 'w', encoding='utf-8').write('\n\n'.join(blocks) + '\n')
PY
    printf 'ASSEMBLED\t%s\t%s parts\t%s bytes\t%s lines\n' "$target" "$#" \
      "$(wc -c < "$target" | tr -d ' ')" "$(wc -l < "$target" | tr -d ' ')"
    ;;
  drop)
    rm -rf "$parts"; rmdir "$dir/.parts" 2>/dev/null || true
    echo "DROPPED	$parts"
    ;;
  *) usage ;;
esac
