from __future__ import annotations

from io import BytesIO

import pandas as pd


def build_excel(
    employee_rows: list[dict],
    contribution_rows: list[dict],
    change_rows: list[dict],
    final_errors: list[dict],
    fund_rows: list[dict] | None = None,
) -> bytes:
    """
    יוצר קובץ Excel מעוצב הכולל:
    - סיכום קופות והפקדות
    - סיכום עובדים
    - פירוט הפרשות
    - תיקונים שבוצעו
    - שגיאות XSD
    """

    output = BytesIO()

    with pd.ExcelWriter(
        output,
        engine="xlsxwriter",
    ) as writer:
        workbook = writer.book

        # -----------------------------
        # עיצובים כלליים
        # -----------------------------
        header_format = workbook.add_format(
            {
                "bold": True,
                "font_size": 12,
                "font_color": "#FFFFFF",
                "bg_color": "#1F4E78",
                "border": 1,
                "border_color": "#B4C6E7",
                "align": "center",
                "valign": "vcenter",
                "text_wrap": True,
            }
        )

        text_format = workbook.add_format(
            {
                "font_size": 11,
                "border": 1,
                "border_color": "#D9E2F3",
                "align": "right",
                "valign": "top",
                "text_wrap": True,
            }
        )

        center_format = workbook.add_format(
            {
                "font_size": 11,
                "border": 1,
                "border_color": "#D9E2F3",
                "align": "center",
                "valign": "vcenter",
                "text_wrap": True,
            }
        )

        money_format = workbook.add_format(
            {
                "font_size": 12,
                "bold": True,
                "border": 1,
                "border_color": "#D9E2F3",
                "align": "right",
                "valign": "vcenter",
                "num_format": '#,##0.00 "₪"',
            }
        )

        percentage_format = workbook.add_format(
            {
                "font_size": 11,
                "border": 1,
                "border_color": "#D9E2F3",
                "align": "center",
                "valign": "vcenter",
                "num_format": "0.00",
            }
        )

        number_format = workbook.add_format(
            {
                "font_size": 11,
                "border": 1,
                "border_color": "#D9E2F3",
                "align": "center",
                "valign": "vcenter",
                "num_format": "#,##0",
            }
        )

        title_format = workbook.add_format(
            {
                "bold": True,
                "font_size": 15,
                "font_color": "#1F4E78",
                "align": "right",
                "valign": "vcenter",
            }
        )

        error_format = workbook.add_format(
            {
                "font_size": 11,
                "border": 1,
                "border_color": "#F4B084",
                "bg_color": "#FCE4D6",
                "align": "right",
                "valign": "top",
                "text_wrap": True,
            }
        )

        fixed_format = workbook.add_format(
            {
                "font_size": 11,
                "border": 1,
                "border_color": "#A9D18E",
                "bg_color": "#E2F0D9",
                "align": "right",
                "valign": "top",
                "text_wrap": True,
            }
        )

        # -----------------------------
        # פונקציית עזר לכתיבת גיליון
        # -----------------------------
        def write_sheet(
            df: pd.DataFrame,
            sheet_name: str,
            money_columns: list[str] | None = None,
            center_columns: list[str] | None = None,
            percentage_columns: list[str] | None = None,
            preferred_widths: dict[str, int] | None = None,
        ) -> None:
            money_columns = money_columns or []
            center_columns = center_columns or []
            percentage_columns = percentage_columns or []
            preferred_widths = preferred_widths or {}

            if df.empty:
                df = pd.DataFrame(
                    [{"מידע": "לא נמצאו נתונים להצגה"}]
                )

            df.to_excel(
                writer,
                sheet_name=sheet_name,
                index=False,
                startrow=1,
            )

            worksheet = writer.sheets[sheet_name]

            # מימין לשמאל
            worksheet.right_to_left()

            # כותרת עליונה
            worksheet.write(
                0,
                0,
                sheet_name,
                title_format,
            )

            # הקפאת שורת הכותרות
            worksheet.freeze_panes(2, 0)

            # מסנן אוטומטי
            worksheet.autofilter(
                1,
                0,
                len(df) + 1,
                len(df.columns) - 1,
            )

            # גובה הכותרת
            worksheet.set_row(1, 32)

            # כותרות
            for column_index, column_name in enumerate(df.columns):
                worksheet.write(
                    1,
                    column_index,
                    column_name,
                    header_format,
                )

            # עיצוב עמודות ותוכן
            for column_index, column_name in enumerate(df.columns):
                column_text = str(column_name)

                if column_text in preferred_widths:
                    width = preferred_widths[column_text]
                else:
                    # חישוב רוחב מוגבל כדי למנוע עמודות ענקיות
                    values = df[column_name].fillna("").astype(str)
                    max_content_length = max(
                        [len(column_text)] +
                        [len(value) for value in values.head(200)]
                    )
                    width = min(
                        max(max_content_length + 2, 12),
                        35,
                    )

                if column_text in money_columns:
                    cell_format = money_format
                elif column_text in percentage_columns:
                    cell_format = percentage_format
                elif column_text in center_columns:
                    cell_format = center_format
                else:
                    cell_format = text_format

                worksheet.set_column(
                    column_index,
                    column_index,
                    width,
                    cell_format,
                )

            # גובה שורות כדי שטקסט ארוך יישאר בתוך התא
            for row_index in range(2, len(df) + 2):
                worksheet.set_row(row_index, 27)

            # פסי שורות עדינים
            worksheet.conditional_format(
                2,
                0,
                len(df) + 1,
                len(df.columns) - 1,
                {
                    "type": "formula",
                    "criteria": "=MOD(ROW(),2)=0",
                    "format": workbook.add_format(
                        {"bg_color": "#F7F9FC"}
                    ),
                },
            )

        # -----------------------------
        # גיליון קופות והפקדות
        # -----------------------------
        fund_df = pd.DataFrame(fund_rows or [])

        # הסרת עמודות שעלולות לבלבל
        fund_columns_to_remove = [
            "ח.פ חברה מנהלת",
            "סטטוס זיהוי",
            "קוד קופה מהקובץ",
        ]

        fund_df = fund_df.drop(
            columns=[
                column
                for column in fund_columns_to_remove
                if column in fund_df.columns
            ],
            errors="ignore",
        )

        preferred_fund_columns = [
            "שם קופה",
            "סכום להפקדה",
            "פרטי חשבון",
            "מספר קופה",
            "שם חברה מנהלת",
            "קוד בנק",
            "קוד סניף",
            "מספר חשבון",
        ]

        if not fund_df.empty:
            existing_columns = [
                column
                for column in preferred_fund_columns
                if column in fund_df.columns
            ]

            fund_df = fund_df[existing_columns]

        write_sheet(
            fund_df,
            "קופות והפקדות",
            money_columns=["סכום להפקדה"],
            center_columns=[
                "מספר קופה",
                "קוד בנק",
                "קוד סניף",
                "מספר חשבון",
            ],
            preferred_widths={
                "שם קופה": 32,
                "סכום להפקדה": 18,
                "פרטי חשבון": 22,
                "מספר קופה": 15,
                "שם חברה מנהלת": 25,
                "קוד בנק": 12,
                "קוד סניף": 12,
                "מספר חשבון": 24,
            },
        )

        # -----------------------------
        # גיליון סיכום עובדים
        # -----------------------------
        employee_df = pd.DataFrame(employee_rows)

        write_sheet(
            employee_df,
            "סיכום עובדים",
            money_columns=[
                "שכר מדווח",
                "תגמולי עובד",
                "תגמולי מעסיק",
                "פיצויים",
                "אובדן כושר עבודה",
                "הפרשות אחרות",
                "סה״כ הפרשות",
            ],
            center_columns=[
                "ת.ז",
                "חודש שכר",
                "הפקדה אחרונה",
            ],
            preferred_widths={
                "שם עובד": 25,
                "ת.ז": 15,
                "חודש שכר": 14,
                "שכר מדווח": 18,
                "הפקדה אחרונה": 16,
                "תגמולי עובד": 17,
                "תגמולי מעסיק": 18,
                "פיצויים": 16,
                "אובדן כושר עבודה": 20,
                "הפרשות אחרות": 18,
                "סה״כ הפרשות": 20,
            },
        )

        # -----------------------------
        # גיליון פירוט הפרשות
        # -----------------------------
        contribution_df = pd.DataFrame(contribution_rows)

        write_sheet(
            contribution_df,
            "פירוט הפרשות",
            money_columns=[
                "שכר מדווח",
                "סכום הפרשה",
            ],
            percentage_columns=[
                "שיעור הפרשה",
            ],
            center_columns=[
                "מספר רשומה",
                "ת.ז",
                "חודש שכר",
                "הפקדה אחרונה",
                "קוד הפרשה",
            ],
            preferred_widths={
                "מספר רשומה": 14,
                "שם עובד": 25,
                "ת.ז": 15,
                "חודש שכר": 14,
                "שכר מדווח": 18,
                "הפקדה אחרונה": 16,
                "קוד הפרשה": 14,
                "סוג הפרשה": 22,
                "שיעור הפרשה": 17,
                "סכום הפרשה": 18,
            },
        )

        # -----------------------------
        # גיליון תיקונים
        # -----------------------------
        changes_df = pd.DataFrame(change_rows)

        write_sheet(
            changes_df,
            "תיקונים שבוצעו",
            center_columns=[
                "severity",
                "rule",
            ],
            preferred_widths={
                "severity": 14,
                "rule": 25,
                "location": 28,
                "before": 30,
                "after": 30,
                "explanation": 55,
            },
        )

        # צבע ירוק לתיקונים שבוצעו
        if not changes_df.empty:
            changes_sheet = writer.sheets["תיקונים שבוצעו"]
            changes_sheet.conditional_format(
                2,
                0,
                len(changes_df) + 1,
                len(changes_df.columns) - 1,
                {
                    "type": "text",
                    "criteria": "containing",
                    "value": "fixed",
                    "format": fixed_format,
                },
            )

        # -----------------------------
        # גיליון שגיאות XSD
        # -----------------------------
        errors_df = pd.DataFrame(final_errors)

        write_sheet(
            errors_df,
            "שגיאות XSD",
            center_columns=[
                "שורה",
                "עמודה",
                "סוג",
            ],
            preferred_widths={
                "שורה": 12,
                "עמודה": 12,
                "סוג": 25,
                "הודעה": 70,
            },
        )

        if not errors_df.empty:
            errors_sheet = writer.sheets["שגיאות XSD"]
            errors_sheet.conditional_format(
                2,
                0,
                len(errors_df) + 1,
                len(errors_df.columns) - 1,
                {
                    "type": "no_blanks",
                    "format": error_format,
                },
            )

    output.seek(0)
    return output.getvalue()
