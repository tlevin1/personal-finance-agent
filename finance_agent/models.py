from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Transaction:
    id: str
    date: str  # YYYY-MM-DD
    description: str
    raw_description: str
    amount: float
    category: str | None
    source_file: str
    confirmed_by_bank: bool | None = None
    exclude_from_totals: bool = False
    flags: list[str] = field(default_factory=list)

    def to_report_dict(self) -> dict:
        return {
            "date": self.date,
            "description": self.description,
            "amount": self.amount,
            "category": self.category or "Uncategorized",
            "excluded_from_totals": self.exclude_from_totals,
        }
