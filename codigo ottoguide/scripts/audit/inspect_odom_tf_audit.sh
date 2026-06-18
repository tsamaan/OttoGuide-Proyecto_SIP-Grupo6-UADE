#!/usr/bin/env bash
# Read-only inspection of the OttoGuide ODOM/TF audit artifact.
# No ROS runtime required. No robot connection. No topic publication.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if git -C "${SCRIPT_DIR}" rev-parse --show-toplevel >/dev/null 2>&1; then
  REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel)"
else
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
fi
ARTIFACT_NAME="ottoguide_odom_tf_audit_20260618_081438.tar.gz"
ARTIFACT_PATH="${REPO_ROOT}/artifacts/_audit/${ARTIFACT_NAME}"
EXPECTED_SHA256="DB0C2CC33AB77FBEC4B056EABE9551B32D9BC5F16680920689FE92FE9F295AA5"
EXTRACT_ROOT="${TMPDIR:-/tmp}/ottoguide_odom_tf_audit_inspect_$$"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

if [[ ! -f "${ARTIFACT_PATH}" ]]; then
  die "missing artifact: ${ARTIFACT_PATH}"
fi

if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  die "sha256sum or shasum required"
fi

if command -v sha256sum >/dev/null 2>&1; then
  OBSERVED_SHA256="$(sha256sum "${ARTIFACT_PATH}" | awk '{print toupper($1)}')"
else
  OBSERVED_SHA256="$(shasum -a 256 "${ARTIFACT_PATH}" | awk '{print toupper($1)}')"
fi

echo "artifact=${ARTIFACT_PATH}"
echo "sha256_expected=${EXPECTED_SHA256}"
echo "sha256_observed=${OBSERVED_SHA256}"

if [[ "${OBSERVED_SHA256}" != "${EXPECTED_SHA256}" ]]; then
  die "SHA256 mismatch"
fi

mkdir -p "${EXTRACT_ROOT}"
trap 'rm -rf "${EXTRACT_ROOT}"' EXIT

tar -xzf "${ARTIFACT_PATH}" -C "${EXTRACT_ROOT}"

PRIORITY_FILES=(
  "ODOM_TF_NEXT_STEPS.md"
  "unitree_sdk_state_references.txt"
  "repo_files_tf_odom_candidates.txt"
  "critical_topics_info.txt"
  "cyclonedds_configs.txt"
  "ros_graph_overview.txt"
  "topic_candidates_odom_tf_state.txt"
  "processes_tf_odom_candidates.txt"
  "grep_tf_odom_references.txt"
)

echo ""
echo "=== archive listing (top level) ==="
tar -tzf "${ARTIFACT_PATH}"

FOUND_ROOT="$(find "${EXTRACT_ROOT}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [[ -z "${FOUND_ROOT}" ]]; then
  die "could not locate extracted audit directory"
fi

echo ""
echo "=== priority summaries ==="
for name in "${PRIORITY_FILES[@]}"; do
  file_path="$(find "${FOUND_ROOT}" -name "${name}" -print -quit)"
  if [[ -z "${file_path}" ]]; then
    echo "--- ${name}: MISSING ---"
    continue
  fi
  echo "--- ${name} (${file_path}) ---"
  sed -n '1,40p' "${file_path}"
  echo ""
done

echo "inspect_ok artifact_verified extract_root=${EXTRACT_ROOT}"
