#!/usr/bin/env bash
#
# Validate one TypeScript documentation example.
#
# Invoked by `selfdoc check` for every fenced ```typescript block marked
# `validate`, via the "examples" key in selfdoc.json. selfdoc assembles the
# block into a scratch file and substitutes its path for {file}; that path
# arrives as $1.
#
# The example imports the package by its published name ("strictcli"), so it is
# validated against typescript/dist -- the exact files npm ships -- and not
# against src/. Resolution is arranged with a single node_modules/strictcli
# symlink into the checkout, which makes both tsc and node take the package's
# own "exports"/"types" entry points, the same path a real consumer takes.
#
# Type-checking alone is insufficient: strictcli's registration guardrails are
# runtime throws, so the snippet is compiled and then executed (with no
# arguments, which prints help and exits 0).
#
# Any failure is a hard error -- no skips, no warnings.

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $(basename "$0") <snippet.ts>" >&2
    exit 2
fi

snippet=$1
if [ ! -f "$snippet" ]; then
    echo "validate-example-ts: no such snippet: $snippet" >&2
    exit 2
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ts_root="$repo_root/typescript"

if [ ! -f "$ts_root/package.json" ]; then
    echo "validate-example-ts: no TypeScript package at $ts_root" >&2
    exit 2
fi
for tool in npm node; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "validate-example-ts: $tool is not installed" >&2
        exit 2
    fi
done

tsc="$ts_root/node_modules/.bin/tsc"
if [ ! -x "$tsc" ]; then
    echo "validate-example-ts: installing TypeScript dependencies..." >&2
    (cd "$ts_root" && npm ci) >&2
fi
if [ ! -x "$tsc" ]; then
    echo "validate-example-ts: $tsc still missing after npm ci" >&2
    exit 2
fi

# Build on demand so a fresh checkout validates without a separate setup step.
if [ ! -f "$ts_root/dist/index.js" ] || [ ! -f "$ts_root/dist/index.d.ts" ]; then
    echo "validate-example-ts: building typescript/dist..." >&2
    (cd "$ts_root" && npm run build) >&2
fi
if [ ! -f "$ts_root/dist/index.js" ] || [ ! -f "$ts_root/dist/index.d.ts" ]; then
    echo "validate-example-ts: typescript/dist is still missing after build" >&2
    exit 2
fi

work=$(mktemp -d -t strictcli-example-ts-XXXXXX)
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/node_modules"
ln -s "$ts_root" "$work/node_modules/strictcli"
cp "$snippet" "$work/example.ts"
printf '%s\n' '{"name":"strictcli-example","private":true,"type":"module"}' \
    > "$work/package.json"

# Mirrors typescript/tsconfig.json's strictness: an example that only survives
# looser settings than the library's own is not a working example. typeRoots
# points back at the checkout because the scratch project has no @types of its
# own.
cat > "$work/tsconfig.json" <<EOF
{
  "compilerOptions": {
    "module": "nodenext",
    "moduleResolution": "nodenext",
    "target": "es2023",
    "lib": ["es2023"],
    "types": ["node"],
    "typeRoots": ["$ts_root/node_modules/@types"],
    "strict": true,
    "skipLibCheck": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "isolatedModules": true,
    "verbatimModuleSyntax": true,
    "forceConsistentCasingInFileNames": true,
    "noEmit": true
  },
  "files": ["example.ts"]
}
EOF
cat > "$work/tsconfig.emit.json" <<'EOF'
{
  "extends": "./tsconfig.json",
  "compilerOptions": {
    "noEmit": false,
    "noEmitOnError": true,
    "outDir": "out"
  }
}
EOF

set +e
check_output=$(cd "$work" && "$tsc" --noEmit -p tsconfig.json 2>&1)
check_status=$?
set -e
if [ $check_status -ne 0 ]; then
    echo "typescript example failed to type-check (exit $check_status):" >&2
    echo "$check_output" >&2
    exit 1
fi

set +e
emit_output=$(cd "$work" && "$tsc" -p tsconfig.emit.json 2>&1)
emit_status=$?
set -e
if [ $emit_status -ne 0 ]; then
    echo "typescript example failed to compile (exit $emit_status):" >&2
    echo "$emit_output" >&2
    exit 1
fi

set +e
run_output=$(cd "$work" && node out/example.js 2>&1)
run_status=$?
set -e
if [ $run_status -ne 0 ]; then
    echo "typescript example compiled but exited $run_status when run with no arguments:" >&2
    echo "$run_output" >&2
    exit 1
fi
