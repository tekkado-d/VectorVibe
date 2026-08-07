import os
from onnxruntime.quantization import quantize_dynamic, QuantType

api_dir = os.path.join(os.path.dirname(__file__), '..', 'api')
input_path = os.path.join(api_dir, 'clip_text_encoder.onnx')
output_path = os.path.join(api_dir, 'clip_text_encoder_int8.onnx')

print("Quantising ONNX model to INT8...")
quantize_dynamic(
    model_input=input_path,
    model_output=output_path,
    weight_type=QuantType.QUInt8
)

orig_mb = os.path.getsize(input_path) / (1024 * 1024)
new_mb = os.path.getsize(output_path) / (1024 * 1024)

print(f"Original: {orig_mb:.1f} MB")
print(f"Quantised: {new_mb:.1f} MB")
print(f"Reduction: {(1 - new_mb/orig_mb) * 100:.0f}%")