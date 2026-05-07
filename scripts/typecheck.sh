#!/usr/bin/env bash
# v1.1.29 — local mypy strict run.
#
# This script exists so the strict-mode triage is reproducible across
# machines. Run it BEFORE every release, not on every commit (that's
# what pre-commit's mypy hook is for, and it's currently advisory).
#
# Usage:
#     ./scripts/typecheck.sh           # full strict pass
#     ./scripts/typecheck.sh core/     # just one package
#     ./scripts/typecheck.sh --report  # save findings to scripts/typecheck.log
#
# Expect ~50–150 findings on the first run. Triage in batches:
#   - "Function is missing a type annotation" → add `-> None` etc.
#   - "Argument 1 has incompatible type" → real bug, fix it
#   - "Need type annotation for variable" → add the annotation

set -u

if ! command -v mypy >/dev/null 2>&1; then
    echo "[ERROR] mypy not installed. Run:"
    echo "    pip install -r requirements-dev.txt"
    exit 1
fi

TARGETS=(core/ runtime/ infra/ state/ config/ cli/)
REPORT_FILE=""
ARGS=()

for arg in "$@"; do
    case "$arg" in
        --report)
            REPORT_FILE="scripts/typecheck.log"
            ;;
        *)
            ARGS+=("$arg")
            ;;
    esac
done

# Override defaults if user passed package paths
if [ ${#ARGS[@]} -gt 0 ]; then
    TARGETS=("${ARGS[@]}")
fi

echo "[INFO] mypy --strict on: ${TARGETS[*]}"
if [ -n "$REPORT_FILE" ]; then
    mypy "${TARGETS[@]}" 2>&1 | tee "$REPORT_FILE"
    echo "[INFO] Saved to $REPORT_FILE"
else
    mypy "${TARGETS[@]}"
fi
