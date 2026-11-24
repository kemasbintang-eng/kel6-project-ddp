from dataclasses import dataclass, asdict
from datetime import datetime
import uuid

@dataclass
class Item:
    title : str
    category : str
    report_type : str
    location : str
    description : str
    contact : str
    status : str = "OPEN"
    item_id : str = ""
    created_at : str = ""

    def __post_init__(self):
        if not self.item_id:
            self.item_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)
