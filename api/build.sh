#!/bin/bash
set -e

echo "Downloading CLIP ONNX text encoder..."

curl -L -o clip_text_encoder.onnx \
  https://github.com/tekkado-d/VectorVibe/releases/download/onnx-vitb16/clip_text_encoder.onnx

#curl -L -o clip_text_encoder.onnx.data \
#  https://github.com/tekkado-d/VectorVibe/releases/download/onnx-vitb16/clip_text_encoder.onnx.data

echo "Model files downloaded:"
ls -lh clip_text_encoder.onnx*

