import open_clip
import os
import shutil

# open_clip ships the BPE vocab file — find and copy it
import open_clip.tokenizer as tok_module

vocab_path = os.path.join(
    os.path.dirname(tok_module.__file__),
    'bpe_simple_vocab_16e6.txt.gz'
)

if not os.path.exists(vocab_path):
    # Try alternate location
    import open_clip
    pkg_dir = os.path.dirname(open_clip.__file__)
    for root, dirs, files in os.walk(pkg_dir):
        for f in files:
            if 'bpe' in f and f.endswith('.gz'):
                vocab_path = os.path.join(root, f)
                break

print(f"Found vocab at: {vocab_path}")

dest = os.path.join(os.path.dirname(__file__), '..', 'api', 'bpe_simple_vocab_16e6.txt.gz')
shutil.copy(vocab_path, dest)

size_kb = os.path.getsize(dest) / 1024
print(f"Copied to api/ — {size_kb:.0f} KB")