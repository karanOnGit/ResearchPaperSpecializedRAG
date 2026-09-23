#!/usr/bin/env bash
# ==============================================================================
# Download Kokoro ONNX neural speech model files
# Used by Research Knowledge Engine for Research Studio dialogue narration.
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
KOKORO_DIR="${BASE_DIR}/data/models/kokoro"

mkdir -p "${KOKORO_DIR}"

VOICES_FILE="${KOKORO_DIR}/voices-v1.0.bin"
ONNX_FILE="${KOKORO_DIR}/kokoro-v1.0.onnx"

echo "==> Checking Kokoro neural TTS model assets in ${KOKORO_DIR}..."

if [ ! -f "${VOICES_FILE}" ]; then
    echo "==> Downloading Kokoro voices (voices-v1.0.bin ~27MB)..."
    curl -L --progress-bar "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" -o "${VOICES_FILE}"
else
    echo "==> Kokoro voices file already present: $(ls -lh "${VOICES_FILE}" | awk '{print $5}')"
fi

if [ ! -f "${ONNX_FILE}" ]; then
    echo "==> Downloading Kokoro ONNX model (kokoro-v1.0.onnx ~310MB)..."
    curl -L --progress-bar "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" -o "${ONNX_FILE}"
else
    echo "==> Kokoro ONNX model already present: $(ls -lh "${ONNX_FILE}" | awk '{print $5}')"
fi

echo "==> Kokoro ONNX TTS assets ready."
