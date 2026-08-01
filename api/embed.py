import open_clip
import torch
from PIL import Image
import requests
from io import BytesIO

# Load CLIP model once when this file is imported
MODEL_NAME = 'ViT-B-32'
PRETRAINED = 'openai'

print("Loading CLIP model...")
model, _, preprocess = open_clip.create_model_and_transforms(
    MODEL_NAME, pretrained=PRETRAINED
)
tokenizer = open_clip.get_tokenizer(MODEL_NAME)
model.eval()

# Use GPU if available, otherwise CPU
device = 'cuda' if torch.cuda.is_available() else 'cpu'
model = model.to(device)
print(f"CLIP model loaded on {device}")

def embed_image_from_url(url: str) -> list[float] | None:
    """Download an image from a URL and return its CLIP vector."""
    try:
        r = requests.get(url, timeout=8)
        img = Image.open(BytesIO(r.content)).convert('RGB')
        tensor = preprocess(img).unsqueeze(0).to(device)
        with torch.no_grad():
            vec = model.encode_image(tensor)
            vec = vec / vec.norm(dim=-1, keepdim=True)
        return vec.squeeze().cpu().tolist()
    except Exception as e:
        print(f"Image embed failed: {e}")
        return None

def embed_text(text: str) -> list[float]:
    """Embed a text query into the same vector space as images."""
    tokens = tokenizer([text]).to(device)
    with torch.no_grad():
        vec = model.encode_text(tokens)
        vec = vec / vec.norm(dim=-1, keepdim=True)
    return vec.squeeze().cpu().tolist()

def embed_image(img: Image.Image) -> list[float]:
    """Embed a PIL Image object directly."""
    tensor = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        vec = model.encode_image(tensor)
        vec = vec / vec.norm(dim=-1, keepdim=True)
    return vec.squeeze().cpu().tolist()