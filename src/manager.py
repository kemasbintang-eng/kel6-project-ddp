from typing import List
from src.models import Item
from src.storage import JSONStorage

class LostAndFoundManager:
    def __init__(self):
        self.storage = JSONStorage()
        self.items: List[Item] = self.storage.load_all()

    def add_report(self, item: Item) -> List[Item]:
        self.items.append(item)
        self.storage.save_all(self.items)
        return self.find_potential_matches(item)

    def find_potential_matches(self, target: Item) -> List[Item]:
        opposite_type = "FOUND" if target.report_type == "LOST" else "LOST"
        target_keywords = set(target.title.lower().split() + target.description.lower().split())

        matches = []
        for item in self.items:
            if item.report_type == opposite_type and item.status == "OPEN":
                if item.category.lower() == target.category.lower():
                    item_words = set(item.title.lower().split() + item.description.lower().split())
                    if target_keywords.intersection(item_words):
                        matches.append(item)
        return matches

    def search_items(self, keyword: str = "", report_type: str = "") -> List[Item]:
        results = self.items
        if report_type:
            results = [i for i in results if i.report_type == report_type.upper()]
        if keyword:
            kw = keyword.lower()
            results = [
                i for i in results
                if kw in i.title.lower() or kw in i.location.lower() or kw in i.description.lower()
            ]
        return results

    def mark_resolved(self, item_id: str) -> bool:
        for item in self.items:
            if item.item_id == item_id.upper() and item.status == "OPEN":
                item.status = "RESOLVED"
                self.storage.save_all(self.items)
                return True
        return False
