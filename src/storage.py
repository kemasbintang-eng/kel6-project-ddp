import json
import os
from typing import List
from src.models import Item

class JSONStorage:
    def __init__(self, filepath: str = "data/items.json"):
        self.filepath = filepath
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        if not os.path.exists(self.filepath):
            self._save_raw([])

    def _save_raw(self, data: list):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def load_all(self) -> List[Item]:
        with open(self.filepath, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            return [Item.from_dict(item) for item in raw_data]

    def save_all(self, items: List[Item]):
        self._save_raw([item.to_dict() for item in items])