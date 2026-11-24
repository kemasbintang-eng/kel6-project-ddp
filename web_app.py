from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import fcntl
import json
import os
import re
import tempfile
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.photo_matching import (
    MAX_PHOTO_BYTES, MatchProfile, jpeg_bytes, match_score, photo_embedding, prepare_photo,
)

app = FastAPI(title="Campus Lost & Found Web")
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = os.environ.get("CAMPUS_DATA_FILE", str(BASE_DIR / "data/items.json"))
JAKARTA = timezone(timedelta(hours=7))


def load_items():
    path = Path(DATA_FILE)
    if not path.exists():
        return []
    # Data yang rusak harus diperbaiki, bukan ditimpa dengan daftar kosong.
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("Data laporan harus berupa daftar")
    return items


def save_items(items):
    path = Path(DATA_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(items, temporary, indent=4, ensure_ascii=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@contextmanager
def report_store():
    """Serialize report read-modify-write operations."""
    path = Path(DATA_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(str(path) + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield load_items()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def report_id(item):
    return item.get("id") or item.get("item_id")


def is_resolved(item):
    return bool(item.get("is_resolved") or item.get("status") == "RESOLVED")


def public_report(item):
    # Whitelist: credential fields must never appear in list/match/resolve responses.
    fields = ("title", "category", "report_type", "location", "description", "contact", "created_at")
    return {
        **{field: item.get(field, "") for field in fields},
        "id": report_id(item),
        "is_resolved": is_resolved(item),
        "resolution_reason": item.get("resolution_reason"),
        "resolved_at": item.get("resolved_at"),
        "custody_location": item.get("custody_location"),
        "custody_at": item.get("custody_at"),
        "has_photo": bool(item.get("photo_embedding")),
    }


def find_report(items, item_id):
    item = next((item for item in items if report_id(item) == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Laporan tidak ditemukan.")
    return item


class ItemCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    report_type: Literal["LOST", "FOUND"]
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    contact: str = Field(min_length=1, max_length=120)


class ItemResolution(BaseModel):
    reason: Literal["RETURNED", "FOUND_SELF", "CANCELLED"]
    confirmed: Literal[True]


class ItemCustody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    location: str = Field(min_length=1, max_length=160)
    confirmed: Literal[True]


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Keep submitted personal information out of validation errors.
    return JSONResponse(status_code=422, content={"detail": [
        {key: problem[key] for key in ("type", "loc", "msg")}
        for problem in error.errors()
    ]})


@app.middleware("http")
async def prevent_api_caching(request, call_next):
    if request.url.path == "/api/items/with-photo" and request.method == "POST":
        content_length = request.headers.get("content-length", "")
        if content_length.isdecimal() and int(content_length) > MAX_PHOTO_BYTES + 64 * 1024:
            return JSONResponse(status_code=413, content={"detail": "Ukuran foto maksimal 8 MB."})
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def read_index():
    return FileResponse(BASE_DIR / "static/index.html")


@app.get("/api/items")
def get_items(keyword: str = "", report_type: str = "", include_matches: bool = False):
    with report_store() as stored:
        stored = list(reversed(stored))
    items = [public_report(item) for item in stored]
    if report_type:
        items = [item for item in items if item["report_type"] == report_type]
    if keyword:
        keyword = keyword.lower()
        items = [item for item in items if any(keyword in item[field].lower() for field in ("title", "description", "location"))]
    if include_matches:
        candidates = match_candidates(stored)
        by_id = {report_id(item): item for item in stored}
        for item in items:
            item["matches"] = find_matches(by_id[item["id"]], candidates)
    return items


@app.post("/api/items")
def create_item(item: ItemCreate):
    return store_report(item)


def photo_path(item_id):
    return Path(DATA_FILE).parent / "report-photos" / f"{item_id}.jpg"


def store_report(item, photo=None, embedding=None):
    new_item = {
        **item.model_dump(),
        "id": uuid.uuid4().hex,
        "is_resolved": False,
        "created_at": datetime.now(JAKARTA).isoformat(timespec="seconds"),
    }
    if photo is not None:
        new_item["photo_embedding"] = embedding
    with report_store() as items:
        items.append(new_item)
        path = photo_path(new_item["id"]) if photo is not None else None
        try:
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(photo)
            save_items(items)
        except Exception:
            if path is not None:
                path.unlink(missing_ok=True)
            raise
    return public_report(new_item)


@app.post("/api/items/with-photo")
def create_item_with_photo(report: str = Form(...), photo: UploadFile = File(...)):
    try:
        item = ItemCreate.model_validate_json(report)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Detail laporan belum lengkap atau tidak valid.") from error
    raw = photo.file.read(MAX_PHOTO_BYTES + 1)
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Ukuran foto maksimal 8 MB.")
    try:
        image = prepare_photo(raw)
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(status_code=422, detail="Gunakan satu foto JPG, PNG, atau WebP dengan resolusi maksimal 40 megapiksel.") from error
    try:
        embedding = photo_embedding(image)
    except (OSError, RuntimeError, ImportError) as error:
        raise HTTPException(status_code=503, detail="Model foto belum siap. Coba lagi nanti atau kirim laporan tanpa foto.") from error
    return store_report(item, photo=jpeg_bytes(image), embedding=embedding)


@app.get("/api/items/{item_id}/photo")
def get_item_photo(item_id: str):
    if not re.fullmatch(r"[0-9a-f]{32}", item_id):
        raise HTTPException(status_code=404, detail="Foto laporan tidak ditemukan.")
    with report_store() as items:
        report = find_report(items, item_id)
        path = photo_path(item_id)
        if not report.get("photo_embedding") or not path.is_file():
            raise HTTPException(status_code=404, detail="Foto laporan tidak ditemukan.")
    return FileResponse(path, media_type="image/jpeg", headers={"X-Content-Type-Options": "nosniff"})


@app.patch("/api/items/{item_id}/resolve")
def resolve_item(item_id: str, resolution: ItemResolution):
    with report_store() as items:
        item = find_report(items, item_id)
        if is_resolved(item):
            raise HTTPException(status_code=409, detail="Laporan ini sudah selesai.")
        if resolution.reason == "FOUND_SELF" and item["report_type"] != "LOST":
            raise HTTPException(status_code=422, detail="Alasan ditemukan sendiri hanya berlaku untuk laporan barang hilang.")

        item["is_resolved"] = True
        if "status" in item:
            item["status"] = "RESOLVED"
        item["resolution_reason"] = resolution.reason
        item["resolved_at"] = datetime.now(JAKARTA).isoformat(timespec="seconds")
        save_items(items)
        return public_report(item)


@app.patch("/api/items/{item_id}/custody")
def update_custody(item_id: str, custody: ItemCustody):
    with report_store() as items:
        item = find_report(items, item_id)
        if is_resolved(item):
            raise HTTPException(status_code=409, detail="Laporan sudah selesai.")
        if item.get("custody_location") != custody.location:
            item["custody_location"] = custody.location
            item["custody_at"] = datetime.now(JAKARTA).isoformat(timespec="seconds")
            save_items(items)
        return public_report(item)


@app.get("/api/items/{item_id}/matches")
def get_matches(item_id: str):
    with report_store() as items:
        target = find_report(items, item_id)
    return find_matches(target, match_candidates(reversed(items)))


def match_candidates(items):
    groups = {"LOST": [], "FOUND": []}
    for item in items:
        group = groups.get(item.get("report_type"))
        if group is not None and not is_resolved(item):
            group.append((item, MatchProfile.from_report(item)))
    return groups


def find_matches(target, candidates):
    opposite = {"LOST": "FOUND", "FOUND": "LOST"}.get(target.get("report_type"))
    if is_resolved(target) or opposite is None:
        return []
    profile = MatchProfile.from_report(target)
    ranked = []
    for candidate, features in candidates[opposite]:
        result = match_score(profile, features)
        if result is not None:
            basis, score = result
            ranked.append((basis, score, candidate))
    ranked.sort(key=lambda match: (match[0] == "photo", match[1]), reverse=True)
    return [{**public_report(item), "match_basis": basis} for basis, _, item in ranked[:3]]
