from __future__ import annotations

from io import BytesIO

import pandas as pd


def build_excel(employee_rows: list[dict], contribution_rows: list[dict], changes: list[dict], xsd_errors: list[dict]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        header = workbook.add_format({
            "bold": True, "font_color": "white", "bg_color": "#1F4E78",
            "border": 1, "align": "center", "valign": "vcenter"
        })
        money = workbook.add_format({"num_format": '#,##0.00 "₪"', "border": 1})
        number = workbook.add_format({"num_format": "0.00", "border": 1})
        text = workbook.add_format({"border": 1, "align": "right"})
        title = workbook.add_format({"bold": True, "font_size": 15, "font_color": "#1F4E78"})

        sheets = [
            ("סיכום עובדים", pd.DataFrame(employee_rows)),
            ("פירוט הפרשות", pd.DataFrame(contribution_rows)),
            ("שינויים שבוצעו", pd.DataFrame(changes)),
            ("שגיאות XSD", pd.DataFrame(xsd_errors)),
        ]

        for sheet_name, df in sheets:
            if df.empty:
                df = pd.DataFrame([{"מידע": "לא נמצאו נתונים"}])
            df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=2)
            ws = writer.sheets[sheet_name]
            ws.right_to_left()
            ws.freeze_panes(3, 0)
            ws.write(0, 0, sheet_name, title)
            ws.set_row(2, 24)
            for col_idx, col_name in enumerate(df.columns):
                ws.write(2, col_idx, col_name, header)
                max_len = max(len(str(col_name)), *(len(str(v)) for v in df[col_name].head(500).fillna("")))
                width = min(max(max_len + 2, 11), 34)
                fmt = text
                if any(x in str(col_name) for x in ["סכום", "שכר", "סה״כ", "תגמולי", "פיצויים", "אובדן"]):
                    fmt = money
                elif "שיעור" in str(col_name):
                    fmt = number
                ws.set_column(col_idx, col_idx, width, fmt)
            ws.autofilter(2, 0, 2 + len(df), len(df.columns) - 1)

    return output.getvalue()
