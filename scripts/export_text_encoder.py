import torch
import open_clip
import os
import os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / "api" / ".env")

MODEL_NAME = os.getenv("CLIP_MODEL", "ViT-B-16")
PRETRAINED = os.getenv("CLIP_PRETRAINED", "laion2b_s34b_b88k")

print("Loading CLIP model...")
model, _, _ = open_clip.create_model_and_transforms(
    'ViT-B-32', pretrained='openai'
)
tokenizer = open_clip.get_tokenizer('ViT-B-32')
model.eval()

class TextEncoder(torch.nn.Module):
    def __init__(self, clip_model):
        super().__init__()
        self.token_embedding = clip_model.token_embedding
        self.positional_embedding = clip_model.positional_embedding
        self.transformer = clip_model.transformer
        self.ln_final = clip_model.ln_final
        self.text_projection = clip_model.text_projection
        self.attn_mask = clip_model.attn_mask

    def forward(self, tokens):
        x = self.token_embedding(tokens)
        x = x + self.positional_embedding
        x = self.transformer(x, attn_mask=self.attn_mask)
        x = self.ln_final(x)
        # Take features from the EOT token position
        x = x[torch.arange(x.shape[0]), tokens.argmax(dim=-1)]
        x = x @ self.text_projection
        return x / x.norm(dim=-1, keepdim=True)

wrapper = TextEncoder(model)
wrapper.eval()

sample_tokens = tokenizer(["a sample fashion query"])
print(f"Sample token shape: {sample_tokens.shape}")

# Verify it produces sensible output before exporting
with torch.no_grad():
    test_out = wrapper(sample_tokens)
print(f"Test output shape: {test_out.shape}")
print(f"Test output norm: {test_out.norm().item():.4f}")

output_path = os.path.join(
    os.path.dirname(__file__), '..', 'api', 'clip_text_encoder.onnx'
)

print("Exporting to ONNX...")
torch.onnx.export(
    wrapper,
    (sample_tokens,),
    output_path,
    input_names=['tokens'],
    output_names=['embedding'],
    dynamic_axes={
        'tokens': {0: 'batch'},
        'embedding': {0: 'batch'}
    },
    opset_version=17,
    do_constant_folding=True,
    dynamo=False
)

size_mb = os.path.getsize(output_path) / (1024 * 1024)
print(f"Exported to {output_path}")
print(f"File size: {size_mb:.1f} MB")