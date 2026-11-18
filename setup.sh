#!/usr/bin/env bash
# Installe la boîte à outils de montage Opti' FITNESS (gratuit, à relancer au début de chaque session).
set -u
D="$(cd "$(dirname "$0")" && pwd)"; K="${OPTI_HOME:-$HOME/opti}"; export OPTI_HOME="$K"; mkdir -p "$K/bin" "$K/models" "$K/sfx"; cp "$D"/*.py "$K"/; cd "$K"
pip install -q --break-system-packages numpy scipy soundfile pyloudnorm pedalboard librosa pillow sherpa-onnx gradio_client requests 2>&1 | grep -v WARNING | tail -1
G=https://github.com; S=$G/k2-fsa/sherpa-onnx/releases/download
[ -x bin/deep-filter ] || { curl -sL -o bin/deep-filter $G/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-x86_64-unknown-linux-musl; chmod +x bin/deep-filter; }
cd models
[ -d sherpa-onnx-whisper-small ] || curl -sL $S/asr-models/sherpa-onnx-whisper-small.tar.bz2 | tar xj
ls -d sherpa-onnx-ced-mini* >/dev/null 2>&1 || curl -sL $S/audio-tagging-models/sherpa-onnx-ced-mini-audio-tagging-2024-04-19.tar.bz2 | tar xj
[ -d sherpa-onnx-spleeter-2stems-int8 ] || curl -sL $S/source-separation-models/sherpa-onnx-spleeter-2stems-int8.tar.bz2 | tar xj
cd "$K"; python3 opti.py sfx >/dev/null; python3 studio.py looks >/dev/null; python3 bank.py sync; echo "OK $K"
