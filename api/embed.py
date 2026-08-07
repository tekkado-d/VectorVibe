import os
import torch
import open_clip
from functools import lru_cache

# Text-only CLIP — much lighter than full model
print("Loading CLIP text encoder...")
model, _, _ = open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')
tokenizer = open_clip.get_tokenizer('ViT-B-32')
model.eval()

# Text encoder only — strip image encoder to save memory
model.visual = None

device = 'cpu'
model = model.to(device)
print("CLIP text encoder ready")

@lru_cache(maxsize=512)
def cached_embed_text(query: str) -> tuple:
    tokens = tokenizer([query]).to(device)
    with torch.no_grad():
        vec = model.encode_text(tokens)
        vec = vec / vec.norm(dim=-1, keepdim=True)
    return tuple(vec.squeeze().cpu().tolist())

def embed_text(text: str) -> list[float]:
    return list(cached_embed_text(text))

def embed_image_from_url(url: str) -> list[float] | None:
    """Image embedding runs locally on GPU machine only."""
    raise NotImplementedError("Image embedding runs on local GPU machine")

def embed_image(img) -> list[float]:
    """Image embedding runs locally on GPU machine only."""
    raise NotImplementedError("Image embedding runs on local GPU machine")

def load_model():
    pass  # Already loaded at module level