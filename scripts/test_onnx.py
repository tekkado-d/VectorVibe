import onnxruntime as ort
import open_clip
import numpy as np
import os

model_path = os.path.join(
    os.path.dirname(__file__), '..', 'api', 'clip_text_encoder_int8.onnx'
)

print("Loading ONNX model...")
session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
tokenizer = open_clip.get_tokenizer('ViT-B-32')

def embed(text):
    tokens = tokenizer([text]).numpy().astype(np.int64)
    result = session.run(None, {'tokens': tokens})[0]
    return result[0]

# Test with a few queries
for query in ["american psycho", "looks like a dog", "cosy sunday morning"]:
    vec = embed(query)
    print(f"'{query}' -> {len(vec)} dims, first 3: {vec[:3]}, norm: {np.linalg.norm(vec):.4f}")