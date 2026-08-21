from __future__ import annotations

from dataclasses import dataclass
import re

_ALLOWED = re.compile(r"^[0-9A-ZА-Я]{20}$", re.IGNORECASE)


def clean_code(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper().replace("Ё", "Е")
    return re.sub(r"[^0-9A-ZА-Я]", "", text)


@dataclass(frozen=True)
class ExpenseKBK:
    raw: str
    grbs: str
    section: str
    subsection: str
    target_article: str
    expense_type: str

    @classmethod
    def parse(cls, value: object) -> "ExpenseKBK":
        code = clean_code(value)
        if len(code) != 20 or not _ALLOWED.match(code):
            raise ValueError(f"expense KBK must contain 20 budget-classification symbols, got {value!r}")
        return cls(
            raw=code,
            grbs=code[0:3],
            section=code[3:5],
            subsection=code[5:7],
            target_article=code[7:17],
            expense_type=code[17:20],
        )

    @classmethod
    def from_parts(
        cls,
        grbs: object,
        section: object,
        subsection: object,
        target_article: object,
        expense_type: object,
    ) -> "ExpenseKBK":
        parts = [
            clean_code(grbs).zfill(3),
            clean_code(section).zfill(2),
            clean_code(subsection).zfill(2),
            clean_code(target_article),
            clean_code(expense_type).zfill(3),
        ]
        if len(parts[3]) != 10:
            raise ValueError(f"target article must contain 10 symbols, got {target_article!r}")
        return cls.parse("".join(parts))

    def dimensions(self) -> dict[str, str]:
        return {
            "kbk": self.raw,
            "grbs": self.grbs,
            "section": self.section,
            "subsection": self.subsection,
            "target_article": self.target_article,
            "expense_type": self.expense_type,
            "program_article": self.target_article[:5],
            "expense_direction": self.target_article[5:],
        }
