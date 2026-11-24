"""Prepare report photos and rank opposite-type reports."""

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
from threading import Lock

from PIL import Image, ImageOps

MODEL_NAME = "facebook/dinov2-small"
MODEL_REVISION = "ed25f3a31f01632728cabb09d1542f84ab7b0056"
MODEL_CACHE = Path(__file__).resolve().parents[1] / ".model-cache"
MAX_PHOTO_BYTES = 8 * 1024 * 1024
_inference_lock = Lock()
_common_words = set("ada atau barang baru dan dari dengan di hilang ini itu kecil ke lagi pada saya sekitar sudah ditemukan tidak untuk yang".split())


def prepare_photo(raw):
    with Image.open(BytesIO(raw), formats=["JPEG", "PNG", "WEBP"]) as original:
        if original.width * original.height > 40_000_000 or getattr(original, "is_animated", False):
            raise ValueError("Gunakan satu foto dengan resolusi maksimal 40 megapiksel.")
        photo = ImageOps.exif_transpose(original).convert("RGB")
        photo.thumbnail((1200, 1200))
        photo.info.clear()
        return photo


def jpeg_bytes(photo):
    output = BytesIO()
    photo.save(output, format="JPEG", quality=86)
    return output.getvalue()


@lru_cache(maxsize=2)
def load_model(local_only=True):
    from transformers import AutoImageProcessor, AutoModel

    options = {
        "revision": MODEL_REVISION,
        "cache_dir": MODEL_CACHE,
        "local_files_only": local_only,
        "trust_remote_code": False,
    }
    processor = AutoImageProcessor.from_pretrained(MODEL_NAME, use_fast=False, **options)
    model = AutoModel.from_pretrained(MODEL_NAME, use_safetensors=True, **options).eval()
    return processor, model


def photo_embedding(photo):
    import torch

    with _inference_lock, torch.inference_mode():
        processor, model = load_model()
        # Fit the whole object into the model input, including wide or tall photos.
        square = ImageOps.pad(photo, (224, 224), color=(124, 116, 104))
        batch = processor(images=square, return_tensors="pt")
        features = model(**batch).last_hidden_state[:, 0]
        return torch.nn.functional.normalize(features, dim=-1)[0].tolist()


def _words(value):
    return set(re.findall(r"[^\W_]{3,}", (value or "").casefold())) - _common_words


@dataclass
class MatchProfile:
    category: str
    title: set[str]
    description: set[str]
    location: set[str]
    embedding: list[float] | None

    @classmethod
    def from_report(cls, report):
        return cls(
            (report.get("category") or "").casefold(),
            _words(report.get("title")),
            _words(report.get("description")),
            _words(report.get("location")),
            report.get("photo_embedding"),
        )


def match_score(left, right):
    same_category = bool(left.category and left.category == right.category)
    same_location = bool(left.location & right.location)
    if left.embedding and right.embedding and len(left.embedding) == len(right.embedding):
        similarity = sum(x * y for x, y in zip(left.embedding, right.embedding))
        # These are starting thresholds for campus reports, not confidence estimates.
        if similarity >= (0.65 if same_category else 0.77):
            return ("photo", similarity + 0.03 * same_category + 0.02 * same_location)
        return None
    shared_title = left.title & right.title
    shared_detail = (left.title | left.description) & (right.title | right.description)
    if same_category and (shared_title or len(shared_detail) >= 2 or (shared_detail and same_location)):
        overlap = len(shared_detail) / len(left.title | left.description | right.title | right.description)
        return ("text", overlap + 0.15 * same_location)
    return None


if __name__ == "__main__":
    load_model(local_only=False)
    print(f"{MODEL_NAME} siap digunakan.")
