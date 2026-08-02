from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


def _clean_number(value: Any) -> str:
    """הופך ערך מאקסל למחרוזת מספרית נקייה."""
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0"):
        text = text[:-2]

    return "".join(ch for ch in text if ch.isdigit())


def load_accounts(accounts_path: str | Path) -> dict[str, list[dict]]:
    """
    קורא את קובץ החשבונות ומחזיר מילון:
    ח.פ -> רשימת קופות השייכות לאותו ח.פ.
    """
    df = pd.read_excel(accounts_path, dtype=str)
    df.columns = [str(col).strip() for col in df.columns]

    required_columns = [
        "מספר ח.פ",
        "שם חברה",
        "שם קופה / קרן",
        "מספר קופה / קרן",
        "קוד בנק",
        "קוד סניף",
        "מספר חשבון",
    ]

    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "חסרות בקובץ החשבונות העמודות הבאות: "
            + ", ".join(missing)
        )

    accounts: dict[str, list[dict]] = defaultdict(list)

    for _, row in df.iterrows():
        company_id = _clean_number(row.get("מספר ח.פ"))

        if not company_id:
            continue

        bank_code = _clean_number(row.get("קוד בנק"))
        branch_code = _clean_number(row.get("קוד סניף"))
        account_number = _clean_number(row.get("מספר חשבון"))
        fund_number = _clean_number(row.get("מספר קופה / קרן"))

        bank_account = ""

        if bank_code and branch_code and account_number:
            bank_account = f"{bank_code}-{branch_code}-{account_number}"

        accounts[company_id].append(
            {
                "ח.פ חברה מנהלת": company_id,
                "שם חברה": str(row.get("שם חברה") or "").strip(),
                "שם קופה": str(row.get("שם קופה / קרן") or "").strip(),
                "מספר קופה": fund_number,
                "קוד בנק": bank_code,
                "קוד סניף": branch_code,
                "מספר חשבון": account_number,
                "פרטי חשבון": bank_account,
            }
        )

    return dict(accounts)


def find_account(
    accounts: dict[str, list[dict]],
    company_id: str,
    fund_number: str = "",
) -> dict | None:
    """
    אם לח.פ קיימת שורה יחידה — מחזיר אותה.
    אם קיימות כמה שורות — מחפש לפי ח.פ + מספר קופה.
    """
    company_id = _clean_number(company_id)
    fund_number = _clean_number(fund_number)

    candidates = accounts.get(company_id, [])

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    if fund_number:
        exact_matches = [
            row
            for row in candidates
            if _clean_number(row.get("מספר קופה")) == fund_number
        ]

        if len(exact_matches) == 1:
            return exact_matches[0]

    return None