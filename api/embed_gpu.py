"""
api/embed_gpu.py -- PyTorch CLIP, LOCAL GPU ONLY. Never imported on Railway.

Model config is read from .env so this file, embed_products.py,
export_text_encoder.py and search.py cannot silently disagree about which
model is in use. Previously each hardcoded its own copy.

load_dotenv() is called here rather than relying on the caller: a module that
reads env vars at import time cannot assume the importer has already loaded
the .env file. That exact bug silently disabled QUERY_TEMPLATE in query.py.
"""

import os
from io import BytesIO
from pathlib import Path

import requests
import torch
from dotenv import load_dotenv
from PIL import Image

import open_clip

load_dotenv(Path(__file__).resolve().parent / ".env")

MODEL_NAME = os.getenv("CLIP_MODEL", "ViT-B-16")
PRETRAINED = os.getenv("CLIP_PRETRAINED", "laion2b_s34b_b88k")
MODEL_TAG = f"{MODEL_NAME}/{PRETRAINED}"

print(f"Loading CLIP for GPU work: {MODEL_TAG}")
model, _, preprocess = open_clip.create_model_and_transforms(
    MODEL_NAME, pretrained=PRETRAINED
)
tokenizer = open_clip.get_tokenizer(MODEL_NAME)
model.eval()

device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)
print(f"CLIP loaded on {device} ({model.visual.output_dim} dims)")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def embed_image_from_url(url: str) -> list[float] | None:
    """Download an image and return its CLIP vector, or None on failure."""
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
        return embed_image(img)
    except Exception as e:
        print(f"Image embed failed: {type(e).__name__}: {e}")
        return None


def embed_image(img: Image.Image) -> list[float]:
    """Embed a PIL Image directly."""
    tensor = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        vec = model.encode_image(tensor)
        vec = vec / vec.norm(dim=-1, keepdim=True)
    return vec.squeeze().cpu().tolist()


def embed_text(text: str) -> list[float]:
    """Text embedding, PyTorch path. Local testing and encoder_check only --
    production uses the ONNX export in embed_text_onnx.py."""
    tokens = tokenizer([text]).to(device)
    with torch.no_grad():
        vec = model.encode_text(tokens)
        vec = vec / vec.norm(dim=-1, keepdim=True)
    return vec.squeeze().cpu().tolist()