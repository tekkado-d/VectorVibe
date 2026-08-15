# scripts/check_encoders.py  — run on your GPU box
import numpy as np, torch, open_clip
from embed_text_onnx import embed_text as onnx_embed   # adjust path as needed

model, _, _ = open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')
tok = open_clip.get_tokenizer('ViT-B-32'); model.eval()

for t in ["a black slip dress", "American Psycho", "cottagecore"]:
    with torch.no_grad():
        a = model.encode_text(tok([t]))
    a = (a / a.norm(dim=-1, keepdim=True)).squeeze().numpy()
    b = np.array(onnx_embed(t)); b = b / np.linalg.norm(b)
    print(f"{np.dot(a, b):.6f}   {t}")