import os
import numpy as np
import onnxruntime as ort
import open_clip
from functools import lru_cache

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'clip_text_encoder.onnx')')

print("Loading ONNX text encoder...")
_session = ort.InferenceSession(
    MODEL_PATH,
    providers=['CPUExecutionProvider']
)
_tokenizer = open_clip.get_tokenizer('ViT-B-32')
print("ONNX text encoder ready")


@lru_cache(maxsize=1024)
def cached_embed_text(query: str) -> tuple:
    """Embed a text query into a 512-dim CLIP-compatible vector."""
    tokens = _tokenizer([query]).numpy().astype(np.int64)
    result = _session.run(None, {'tokens': tokens})[0]
    return tuple(float(x) for x in result[0])


def embed_text(text: str) -> list[float]:
    return list(cached_embed_text(text))