import os
import time
import threading
from pathlib import Path
from typing import List

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"

from sentence_transformers import SentenceTransformer

_MODEL = None
_LOCK = threading.Lock()


def get_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    with _LOCK:
        if _MODEL is not None:
            return _MODEL

        import yaml
        config_path = Path(__file__).parent.parent.parent / "config.yaml"  # paperbridge/
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        model_name = cfg.get("embedding", {}).get("model", "BAAI/bge-large-en-v1.5")
        device = cfg.get("embedding", {}).get("device", "cpu")

        print(f"[Embedder] Loading model {model_name} from local cache (1.3GB)...")
        t0 = time.time()
        _MODEL = SentenceTransformer(
            model_name, device=device,
            local_files_only=True,
        )
        print(f"[Embedder] Model loaded in {time.time() - t0:.1f}s")
    return _MODEL


def embed(texts: List[str]) -> List[List[float]]:
    model = get_model()
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


def embed_single(text: str) -> List[float]:
    return embed([text])[0]
