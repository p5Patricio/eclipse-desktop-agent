#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ECLIPSE_PYTHON="${ECLIPSE_PYTHON:-${REPO_ROOT}/.venv-wake/bin/python}"
ECLIPSE_WAKE_THRESHOLD="${ECLIPSE_WAKE_THRESHOLD:-0.5}"
ECLIPSE_WAKE_TIMEOUT_SECONDS="${ECLIPSE_WAKE_TIMEOUT_SECONDS:-}"
ECLIPSE_COMMAND_SECONDS="${ECLIPSE_COMMAND_SECONDS:-5}"
ECLIPSE_WHISPER_MODEL="${ECLIPSE_WHISPER_MODEL:-small}"
ECLIPSE_LANGUAGE="${ECLIPSE_LANGUAGE:-es}"
ECLIPSE_BUILTIN_WAKEWORD="${ECLIPSE_BUILTIN_WAKEWORD:-hey_jarvis}"
ECLIPSE_WAKEWORD_MODEL="${ECLIPSE_WAKEWORD_MODEL:-}"
ECLIPSE_STORE="${ECLIPSE_STORE:-}"

if [[ ! -x "${ECLIPSE_PYTHON}" ]]; then
  {
    echo "Configured Python environment is missing or not executable: ${ECLIPSE_PYTHON}"
    echo "Set ECLIPSE_PYTHON to the wake runtime Python, or create ${REPO_ROOT}/.venv-wake."
  } >&2
  exit 2
fi

command=(
  "${ECLIPSE_PYTHON}"
  -m eclipse_agent
  wake-efficient
  --iterations 0
  --wake-threshold "${ECLIPSE_WAKE_THRESHOLD}"
  --builtin-wakeword "${ECLIPSE_BUILTIN_WAKEWORD}"
  --command-seconds "${ECLIPSE_COMMAND_SECONDS}"
  --model "${ECLIPSE_WHISPER_MODEL}"
  --language "${ECLIPSE_LANGUAGE}"
  --execute
  --speak
  --route-execute
  --confirmed
)

if [[ -n "${ECLIPSE_WAKE_TIMEOUT_SECONDS}" ]]; then
  command+=(--wake-timeout-seconds "${ECLIPSE_WAKE_TIMEOUT_SECONDS}")
fi

if [[ -n "${ECLIPSE_WAKEWORD_MODEL}" ]]; then
  command+=(--wakeword-model "${ECLIPSE_WAKEWORD_MODEL}")
fi

if [[ -n "${ECLIPSE_STORE}" ]]; then
  command+=(--store "${ECLIPSE_STORE}")
fi

echo "Eclipse startup: builtin wakeword fallback ${ECLIPSE_BUILTIN_WAKEWORD} is active."
if [[ -n "${ECLIPSE_WAKEWORD_MODEL}" ]]; then
  echo "Eclipse startup: preferred custom wakeword model ${ECLIPSE_WAKEWORD_MODEL} configured."
else
  echo "Eclipse startup: no custom wakeword model configured."
fi
echo "PYTHONPATH=${REPO_ROOT}/src"
printf 'Command:'
printf ' %q' "${command[@]}"
printf '\n'

if [[ "${ECLIPSE_START_DRY_RUN:-0}" == "1" ]]; then
  exit 0
fi

cd "${REPO_ROOT}"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${command[@]}"
