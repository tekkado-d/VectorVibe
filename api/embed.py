import os
import requests

HF_TOKEN = os.getenv('HF_TOKEN')
HF_API_URL = "https://api-inference.huggingface.co/models/openai/clip-vit-base-patch32"

headers = {"Authorization": f"Bearer {HF_TOKEN}"}

def embed_text(text: str) -> list[float]:
    """Send text to Hugging Face CLIP API and get embedding back."""
    response = requests.post(
        HF_API_URL,
        headers=headers,
        json={"inputs": {"source_sentence": text, "sentences": [text]}}
    )
    # HF feature extraction endpoint
    response2 = requests.post(
        "https://api-inference.huggingface.co/pipeline/feature-extraction/openai/clip-vit-base-patch32",
        headers=headers,
        json={"inputs": text}
    )
    if response2.status_code == 200:
        return response2.json()[0]
    raise Exception(f"HF API error: {response2.status_code} {response2.text}")

def embed_image_from_url(url: str) -> list[float] | None:
    """Download image and embed via Hugging Face CLIP API."""
    try:
        img_response = requests.get(url, timeout=8)
        response = requests.post(
            "https://api-inference.huggingface.co/pipeline/feature-extraction/openai/clip-vit-base-patch32",
            headers={**headers, "Content-Type": "application/octet-stream"},
            data=img_response.content
        )
        if response.status_code == 200:
            return response.json()[0]
        return None
    except Exception as e:
        print(f"Image embed failed: {e}")
        return None

def embed_image(img) -> list[float]:
    """Embed a PIL image via Hugging Face."""
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format='JPEG')
    response = requests.post(
        "https://api-inference.huggingface.co/pipeline/feature-extraction/openai/clip-vit-base-patch32",
        headers={**headers, "Content-Type": "application/octet-stream"},
        data=buf.getvalue()
    )
    if response.status_code == 200:
        return response.json()[0]
    raise Exception(f"HF API error: {response.status_code}")

def load_model():
    """No-op — model lives on Hugging Face, not locally."""
    print("Using Hugging Face CLIP API — no local model needed")