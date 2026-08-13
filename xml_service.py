from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path

from lxml import etree


LYN_CONSTANTS = {
    "MISPAR-GIRSAT-XML": "006",
    "KOD-SHOLECH": "6",
    "SUG-MEZAHE-SHOLECH": "5",
    "MISPAR-ZIHUI-SHOLECH": "058893207",
    "KOD-NIMAAN": "2",
    "SUG-MEZAHE-NIMAAN": "1",
    "MISPAR-ZIHUI-NIMAAN": "514813450",
    "MISPAR-TELEPHONE-KAVI-PONE-LEMISLAKA": "048220228",

    "KOD-EMTZAI-TASHLUM": "1",
    "SUG-CHESHBON-KOLET-TASHLUM": "1",
}


BANK_ZERO_REPLACEMENTS = {
    "MISPAR-CHESHBON-KOLET": "00000000000000000000",
    "MISPAR-SNIF-KOLET": "000",
    "MISPAR-CHESHBON-MAASIK": "00000000000000000000",
    "MISPAR-SNIF-MAASIK": "000",
}


CONTRIBUTION_LABELS = {
    "1": "פיצויים",
    "2": "תגמולי עובד",
    "3": "תגמולי מעסיק",
    "4": "תגמולים אחרים",
    "5": "תגמולים אחרים",
    "6": "אובדן כושר עבודה",
    "7": "הפרשה נוספת",
    "8": "הפרשה נוספת",
}


@dataclass
class Change:
    severity: str
    rule: str
    location: str
    before: str
    after: str
    explanation: str

    def to_dict(self) -> dict:
        return asdict(self)


def _local_name(node_or_tag) -> str:
    tag = node_or_tag.tag if hasattr(node_or_tag, "tag") else node_or_tag
    return etree.QName(tag).localname


def _find_all(root, local_name: str):
    return root.xpath(f".//*[local-name()='{local_name}']")


def _find_first(root, local_name: str):
    items = _find_all(root, local_name)
    return items[0] if items else None


def _find_direct(parent, local_name: str):
    return next(
        (child for child in parent if _local_name(child) == local_name),
        None,
    )


def _text(node) -> str:
    return "" if node is None or node.text is None else node.text.strip()


def _money(value) -> str:
    try:
        return str(
            Decimal(str(value)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        )
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"סכום לא תקין: {value}")


def parse_xml(data: bytes):
    parser = etree.XMLParser(
        remove_blank_text=False,
        recover=False,
        huge_tree=True,
    )
    return etree.parse(BytesIO(data), parser)


def load_xsd(xsd_path: str | Path) -> etree.XMLSchema:
    xsd_doc = etree.parse(str(xsd_path))
    return etree.XMLSchema(xsd_doc)


def validate_xsd(tree, schema: etree.XMLSchema) -> list[dict]:
    is_valid = schema.validate(tree)

    if is_valid:
        return []

    errors = []

    for err in schema.error_log:
        errors.append(
            {
                "שורה": err.line,
                "עמודה": err.column,
                "סוג": err.type_name,
                "הודעה": err.message,
            }
        )

    return errors


def validate_and_repair(
    data: bytes,
    employer_id_type: str | None = None,
    last_deposit_default: str = "2",
    repair_bank_zeroes: bool = True,
    accounts: dict[str, list[dict]] | None = None,
):
    tree = parse_xml(data)
    root = tree.getroot()

    changes: list[Change] = []

    # ערכים קבועים של לין והמסלקה.
    for tag, required in LYN_CONSTANTS.items():
        node = _find_first(root, tag)

        if node is None:
            changes.append(
                Change(
                    "error",
                    "constant_missing",
                    tag,
                    "חסר",
                    required,
                    "השדה הקבוע חסר ולא ניתן ליצור בבטחה את בלוק האב באופן אוטומטי.",
                )
            )
            continue

        before = _text(node)

        if before != required:
            node.text = required

            changes.append(
                Change(
                    "fixed",
                    "lyn_constant",
                    tag,
                    before,
                    required,
                    "הותאם לערך הקבוע של קובץ הנשלח דרך לין למסלקה.",
                )
            )

    # סוג מזהה מעסיק:
    # 1 = ח.פ
    # 5 = עוסק מורשה
    if employer_id_type in {"1", "5"}:
        for idx, node in enumerate(
            _find_all(root, "SUG-MEZAHE-MAASIK"),
            start=1,
        ):
            before = _text(node)

            if before != employer_id_type:
                node.text = employer_id_type

                changes.append(
                    Change(
                        "fixed",
                        "employer_id_type",
                        f"SUG-MEZAHE-MAASIK #{idx}",
                        before,
                        employer_id_type,
                        "עודכן בהתאם לסוג המעסיק שנבחר.",
                    )
                )

    # בגרסה 006 השדה HAFKADA-ACHRONA נדרש
    # בתוך כל ChodeshMaskoretVestatusOved
    # ולפני פירוט ההפרשות.
    salary_blocks = _find_all(
        root,
        "ChodeshMaskoretVestatusOved",
    )

    for idx, block in enumerate(
        salary_blocks,
        start=1,
    ):
        children = list(block)

        deposit_nodes = [
            child
            for child in children
            if _local_name(child) == "HAFKADA-ACHRONA"
        ]

        first_contribution = next(
            (
                child
                for child in children
                if _local_name(child)
                in {
                    "PizulHafrashotOvedBeKupa",
                    "SachHafrashaLeKupaBechodeshMaskoretOved",
                }
            ),
            None,
        )

        if not deposit_nodes:
            if first_contribution is None:
                changes.append(
                    Change(
                        "error",
                        "last_deposit_missing",
                        f"רשומת שכר #{idx}",
                        "חסר",
                        "לא נוסף",
                        "לא נמצאה נקודת הכנסה בטוחה לפני בלוק ההפרשות.",
                    )
                )

            else:
                new = etree.Element(
                    first_contribution.tag.replace(
                        _local_name(first_contribution),
                        "HAFKADA-ACHRONA",
                    )
                )

                new.text = last_deposit_default

                block.insert(
                    block.index(first_contribution),
                    new,
                )

                changes.append(
                    Change(
                        "fixed",
                        "last_deposit_added",
                        f"רשומת שכר #{idx}",
                        "חסר",
                        last_deposit_default,
                        "נוסף לפני פירוט ההפרשות כנדרש בגרסה 006.",
                    )
                )

        else:
            keep = deposit_nodes[0]
            before = _text(keep)

            if before not in {"1", "2"}:
                keep.text = last_deposit_default

                changes.append(
                    Change(
                        "fixed",
                        "last_deposit_value",
                        f"רשומת שכר #{idx}",
                        before,
                        last_deposit_default,
                        "קוד חוקי: 1=לא, 2=כן.",
                    )
                )

            for duplicate in deposit_nodes[1:]:
                block.remove(duplicate)

                changes.append(
                    Change(
                        "fixed",
                        "last_deposit_duplicate",
                        f"רשומת שכר #{idx}",
                        _text(duplicate),
                        "הוסר",
                        "נשמר מופע יחיד בלבד.",
                    )
                )

            children = list(block)

            first_contribution = next(
                (
                    child
                    for child in children
                    if _local_name(child)
                    in {
                        "PizulHafrashotOvedBeKupa",
                        "SachHafrashaLeKupaBechodeshMaskoretOved",
                    }
                ),
                None,
            )

            if (
                first_contribution is not None
                and block.index(keep)
                > block.index(first_contribution)
            ):
                block.remove(keep)

                block.insert(
                    block.index(first_contribution),
                    keep,
                )

                changes.append(
                    Change(
                        "fixed",
                        "last_deposit_order",
                        f"רשומת שכר #{idx}",
                        "אחרי ההפרשות",
                        "לפני ההפרשות",
                        "תוקן סדר האלמנטים.",
                    )
                )

    # תיקון שדות בנק שבהם מופיע רק 0.
    if repair_bank_zeroes:
        for tag, replacement in BANK_ZERO_REPLACEMENTS.items():
            for idx, node in enumerate(
                _find_all(root, tag),
                start=1,
            ):
                before = _text(node)

                if before == "0":
                    node.text = replacement

                    changes.append(
                        Change(
                            "fixed",
                            "bank_pattern",
                            f"{tag} #{idx}",
                            before,
                            replacement,
                            "הערך הושלם באפסים לאורך הנדרש ב-XSD.",
                        )
                    )

    # מילוי פרטי חשבון הקופה לפי accounts.xlsx.
    if accounts:
        from account_lookup import find_account

        transfer_blocks = _find_all(
            root,
            "PirteiHaavaratKsafim",
        )

        for idx, block in enumerate(
            transfer_blocks,
            start=1,
        ):
            identifier_node = _find_direct(
                block,
                "KOD-MEZAHE-KUPA-H-P",
            )

            identifier = _text(identifier_node)

            company_id, fund_number = parse_fund_identifier(
                identifier
            )

            if not company_id:
                changes.append(
                    Change(
                        "error",
                        "fund_identifier_missing",
                        f"PirteiHaavaratKsafim #{idx}",
                        identifier or "חסר",
                        "לא שונה",
                        "לא ניתן לזהות את ח.פ החברה המנהלת מתוך קוד הקופה.",
                    )
                )

                continue

            account = find_account(
                accounts,
                company_id=company_id,
                fund_number=fund_number,
            )

            if account is None:
                changes.append(
                    Change(
                        "error",
                        "fund_account_not_found",
                        f"PirteiHaavaratKsafim #{idx}",
                        f"ח.פ {company_id}, קופה {fund_number}",
                        "לא שונה",
                        "לא נמצאה התאמה מתאימה בקובץ accounts.xlsx.",
                    )
                )

                continue

            bank_code = str(
                account.get("קוד בנק", "") or ""
            ).strip()

            branch_code_raw = str(
                account.get("קוד סניף", "") or ""
            ).strip()

            branch_code_digits = "".join(
                char
                for char in branch_code_raw
                if char.isdigit()
            )

            branch_code = (
                branch_code_digits.zfill(3)
                if branch_code_digits
                else ""
            )

            account_number_digits = "".join(
                char
                for char in str(
                    account.get(
                        "מספר חשבון",
                        "",
                    )
                    or ""
                )
                if char.isdigit()
            )

            account_number = (
                account_number_digits.zfill(20)
                if account_number_digits
                else ""
            )

            fund_name = str(
                account.get(
                    "שם קופה",
                    "",
                )
                or ""
            ).strip()

            values_to_update = {
                "MISPAR-BANK-KOLET": bank_code,
                "MISPAR-SNIF-KOLET": branch_code,
                "MISPAR-CHESHBON-KOLET": account_number,
            }

            for tag, required_value in values_to_update.items():
                if not required_value:
                    changes.append(
                        Change(
                            "error",
                            "fund_bank_value_missing",
                            f"{tag} בקופה #{idx}",
                            "חסר באקסל",
                            "לא שונה",
                            f"לא נמצא ערך עבור {tag} בקובץ accounts.xlsx.",
                        )
                    )

                    continue

                node = _find_direct(
                    block,
                    tag,
                )

                if node is None:
                    changes.append(
                        Change(
                            "error",
                            "fund_bank_element_missing",
                            f"{tag} בקופה #{idx}",
                            "האלמנט חסר",
                            "לא שונה",
                            "האלמנט לא קיים בבלוק ולכן לא נוסף כדי לא לשבש את סדר ה-XSD.",
                        )
                    )

                    continue

                before = _text(node)

                if before != required_value:
                    node.text = required_value

                    changes.append(
                        Change(
                            "fixed",
                            "fund_bank_details",
                            f"{tag} בקופה #{idx}",
                            before,
                            required_value,
                            (
                                f"עודכן לפי הקופה "
                                f"{fund_name or fund_number}, "
                                f"ח.פ חברה מנהלת "
                                f"{company_id}."
                            ),
                        )
                    )

    # השלמת טלפון קווי של הפונה למסלקה.
    for idx, node in enumerate(
        _find_all(
            root,
            "MISPAR-TELEPHONE-KAVI-PONE-LEMISLAKA",
        ),
        start=1,
    ):
        before = _text(node)

        xsi_nil = (
            "{http://www.w3.org/2001/XMLSchema-instance}nil"
        )

        if node.get(xsi_nil) == "true":
            del node.attrib[xsi_nil]

        if before != "048220228":
            node.text = "048220228"

            changes.append(
                Change(
                    "fixed",
                    "phone_completion",
                    (
                        "MISPAR-TELEPHONE-KAVI-PONE-LEMISLAKA "
                        f"#{idx}"
                    ),
                    before or "ריק",
                    "048220228",
                    (
                        "הושלם מספר הטלפון הקבוע של לין "
                        "והוסר xsi:nil אם היה קיים."
                    ),
                )
            )

    # השלמת מספר חשבון מעסיק ל-20 ספרות.
    for idx, node in enumerate(
        _find_all(
            root,
            "MISPAR-CHESHBON-MAASIK",
        ),
        start=1,
    ):
        before = _text(node)

        account_digits = "".join(
            char
            for char in before
            if char.isdigit()
        )

        if not account_digits:
            continue

        if len(account_digits) > 20:
            changes.append(
                Change(
                    "error",
                    "employer_account_too_long",
                    f"MISPAR-CHESHBON-MAASIK #{idx}",
                    before,
                    "לא שונה",
                    (
                        "מספר החשבון ארוך מ-20 ספרות "
                        "ולכן לא ניתן לתקן אוטומטית."
                    ),
                )
            )

            continue

        required_value = account_digits.zfill(20)

        if before != required_value:
            node.text = required_value

            changes.append(
                Change(
                    "fixed",
                    "employer_account_padding",
                    f"MISPAR-CHESHBON-MAASIK #{idx}",
                    before,
                    required_value,
                    (
                        "מספר החשבון הושלם ל-20 ספרות "
                        "באמצעות אפסים מובילים."
                    ),
                )
            )

    # ==========================================================
    # תיקון מספרי סלולר
    # ==========================================================
    #
    # מספר סלולרי תקין:
    # - בדיוק 10 ספרות
    # - מתחיל ב-05
    #
    # לדוגמה:
    # 0528785450 = תקין
    # 0500000000 = תקין
    # 0482202281 = לא תקין
    # 048220228  = לא תקין
    #
    # השדה החשוב לשגיאה 2322:
    # MISPAR-CELLULARI-ISH-KESHER-SHOLECH
    #
    # הודעת המסלקה:
    # KoteretKovetz.NetuneiGoremSholech.
    # MISPARCELLULARIISHKESHERSHOLECH
    #
    DEFAULT_MOBILE = "0500000000"

    cellular_field_names = {
        "MISPAR-CELLULARI",
        "MISPAR-CELLULARI-ISH-KESHER-SHOLECH",
        "MISPARCELLULARIISHKESHERSHOLECH",
    }

    cellular_nodes = [
        node
        for node in root.iter()
        if (
            _local_name(node) in cellular_field_names
            or "CELLULARI" in _local_name(node).upper()
        )
    ]

    for idx, node in enumerate(
        cellular_nodes,
        start=1,
    ):
        before = _text(node)
        field_name = _local_name(node)

        mobile = "".join(
            char
            for char in before
            if char.isdigit()
        )

        is_valid_mobile = (
            len(mobile) == 10
            and mobile.startswith("05")
        )

        if not is_valid_mobile:
            xsi_nil = (
                "{http://www.w3.org/2001/"
                "XMLSchema-instance}nil"
            )

            if xsi_nil in node.attrib:
                del node.attrib[xsi_nil]

            node.text = DEFAULT_MOBILE

            changes.append(
                Change(
                    "fixed",
                    "mobile_number",
                    f"{field_name} #{idx}",
                    before or "ריק",
                    DEFAULT_MOBILE,
                    (
                        "מספר סלולרי חייב להיות בן "
                        "10 ספרות ולהתחיל ב-05. "
                        "הערך תוקן ל-0500000000."
                    ),
                )
            )




        # =========================================================
    # פרטי קשר קבועים / תיקון פרטי קשר בכל הקובץ
    # =========================================================

    DEFAULT_EMAIL = "niv@ssade.co.il"
    DEFAULT_MOBILE = "0500000000"
    DEFAULT_LANDLINE = "048220228"
    DEFAULT_CITY = "חיפה"

    XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

    # ---------------------------------------------------------
    # 1. כל כתובות המייל בקובץ מוחלפות למייל הקבוע של לין
    # מטפל בכל תג שמכיל E-MAIL:
    # עובד, מעסיק, שולח, פונה למסלקה וכו'
    # ---------------------------------------------------------
    email_nodes = root.xpath(
        ".//*[contains(local-name(), 'E-MAIL')]"
    )

    for idx, node in enumerate(email_nodes, start=1):
        before = _text(node)

        # אם האלמנט מסומן כריק, חייבים להסיר xsi:nil לפני הכנסת ערך
        if node.get(XSI_NIL) == "true":
            del node.attrib[XSI_NIL]

        if before != DEFAULT_EMAIL:
            node.text = DEFAULT_EMAIL

            changes.append(
                Change(
                    "fixed",
                    "email_standardization",
                    f"{_local_name(node)} #{idx}",
                    before or "ריק",
                    DEFAULT_EMAIL,
                    "כתובת המייל הוחלפה למייל הקבוע של לין.",
                )
            )

    # ---------------------------------------------------------
    # 2. תיקון כל מספרי הסלולר בקובץ
    # תקין רק אם:
    # - 10 ספרות
    # - מתחיל ב-05
    # אחרת: 0500000000
    # ---------------------------------------------------------
    mobile_nodes = root.xpath(
        ".//*[contains(local-name(), 'CELLULARI')]"
    )

    for idx, node in enumerate(mobile_nodes, start=1):
        before = _text(node)

        mobile = "".join(
            ch for ch in before
            if ch.isdigit()
        )

        if node.get(XSI_NIL) == "true":
            del node.attrib[XSI_NIL]

        mobile_is_valid = (
            len(mobile) == 10
            and mobile.startswith("05")
        )

        if not mobile_is_valid:
            node.text = DEFAULT_MOBILE

            changes.append(
                Change(
                    "fixed",
                    "mobile_number",
                    f"{_local_name(node)} #{idx}",
                    before or "ריק",
                    DEFAULT_MOBILE,
                    "מספר סלולרי חייב להכיל 10 ספרות ולהתחיל ב-05.",
                )
            )

    # ---------------------------------------------------------
    # 3. תיקון כל הטלפונים הקוויים בקובץ
    # תקין רק אם:
    # - 9 ספרות
    # - מתחיל ב-04 / 03 / 09
    # אחרת: 048220228
    # ---------------------------------------------------------
    landline_nodes = root.xpath(
        ".//*[contains(local-name(), 'TELEPHONE-KAVI')]"
    )

    for idx, node in enumerate(landline_nodes, start=1):
        before = _text(node)

        phone = "".join(
            ch for ch in before
            if ch.isdigit()
        )

        if node.get(XSI_NIL) == "true":
            del node.attrib[XSI_NIL]

        landline_is_valid = (
            len(phone) == 9
            and phone.startswith(("04", "03", "09"))
        )

        if not landline_is_valid:
            node.text = DEFAULT_LANDLINE

            changes.append(
                Change(
                    "fixed",
                    "landline_number",
                    f"{_local_name(node)} #{idx}",
                    before or "ריק",
                    DEFAULT_LANDLINE,
                    "טלפון קווי חייב להכיל 9 ספרות ולהתחיל ב-04, 03 או 09.",
                )
            )

    # ---------------------------------------------------------
    # 4. השלמת פרטי עובדים
    # עיר ריקה -> חיפה
    # מייל -> niv@ssade.co.il
    # סלולרי לא תקין/ריק -> 0500000000
    # ---------------------------------------------------------
    for employee_idx, employee in enumerate(
        _find_all(root, "PirteiOved"),
        start=1,
    ):
        # עיר
        city_node = _find_direct(employee, "SHEM-YISHUV")

        if city_node is not None:
            before = _text(city_node)

            if city_node.get(XSI_NIL) == "true":
                del city_node.attrib[XSI_NIL]

            if not before:
                city_node.text = DEFAULT_CITY

                changes.append(
                    Change(
                        "fixed",
                        "employee_city",
                        f"עובד #{employee_idx} - SHEM-YISHUV",
                        "ריק",
                        DEFAULT_CITY,
                        "עיר העובד הייתה ריקה ולכן הושלמה לחיפה.",
                    )
                )

        # מייל עובד
        employee_email = _find_direct(employee, "E-MAIL")

        if employee_email is not None:
            before = _text(employee_email)

            if employee_email.get(XSI_NIL) == "true":
                del employee_email.attrib[XSI_NIL]

            if before != DEFAULT_EMAIL:
                employee_email.text = DEFAULT_EMAIL

                changes.append(
                    Change(
                        "fixed",
                        "employee_email",
                        f"עובד #{employee_idx} - E-MAIL",
                        before or "ריק",
                        DEFAULT_EMAIL,
                        "מייל העובד הוחלף למייל הקבוע.",
                    )
                )

        # סלולרי עובד
        employee_mobile = _find_direct(
            employee,
            "MISPAR-CELLULARI",
        )

        if employee_mobile is not None:
            before = _text(employee_mobile)

            mobile = "".join(
                ch for ch in before
                if ch.isdigit()
            )

            if employee_mobile.get(XSI_NIL) == "true":
                del employee_mobile.attrib[XSI_NIL]

            if len(mobile) != 10 or not mobile.startswith("05"):
                employee_mobile.text = DEFAULT_MOBILE

                changes.append(
                    Change(
                        "fixed",
                        "employee_mobile",
                        f"עובד #{employee_idx} - MISPAR-CELLULARI",
                        before or "ריק",
                        DEFAULT_MOBILE,
                        "מספר הסלולר של העובד לא היה תקין.",
                    )
                )
    # תיקון MISPAR-HAKOVETZ לאורך מקסימלי של 34 תווים
file_number_nodes = _find_all(root, "MISPAR-HAKOVETZ")

for idx, node in enumerate(file_number_nodes, start=1):
    before = _text(node)

    if len(before) > 34:
        # 14 תווים ראשונים = תאריך ושעה
        timestamp = before[:14]

        # 4 תווים אחרונים = מספר סידורי
        serial = before[-4:]

        # מזהה לין הקבוע
        sender_id = "058893207"

        # המבנה הסופי באורך 34 תווים
        required_value = (
            f"{timestamp}"
            f"0000000"
            f"{sender_id}"
            f"{serial}"
        )

        node.text = required_value

        changes.append(
            Change(
                "fixed",
                "mispar_hakovetz_length",
                f"MISPAR-HAKOVETZ #{idx}",
                before,
                required_value,
                "מספר הקובץ היה ארוך מ-34 תווים ולכן נבנה מחדש לפי פורמט גרסה 006.",
            )
        )

    return tree, changes


def extract_contributions(tree) -> list[dict]:
    root = tree.getroot()

    rows: list[dict] = []
    row_number = 0

    for person in _find_all(
        root,
        "PirteiOved",
    ):
        first = _text(
            _find_direct(
                person,
                "SHEM-PRATI",
            )
        )

        last = _text(
            _find_direct(
                person,
                "SHEM-MISHPACHA",
            )
        )

        person_id = _text(
            _find_direct(
                person,
                "MISPAR-MEZAHE",
            )
        )

        salary_blocks = person.xpath(
            "./*[local-name()='ChodeshMaskoretVestatusOved']"
        )

        for salary_block in salary_blocks:
            salary = _text(
                _find_direct(
                    salary_block,
                    "SACHAR-MEDUVACH",
                )
            )

            month = _text(
                _find_direct(
                    salary_block,
                    "CHODESH-MASKORET",
                )
            )

            last_dep = _text(
                _find_direct(
                    salary_block,
                    "HAFKADA-ACHRONA",
                )
            )

            contributions = salary_block.xpath(
                "./*[local-name()='PizulHafrashotOvedBeKupa']"
            )

            for contribution in contributions:
                row_number += 1

                kind = _text(
                    _find_direct(
                        contribution,
                        "SUG-HAFRASHA",
                    )
                )

                contribution_rate = _text(
                    _find_direct(
                        contribution,
                        "SHIUR-HAFRASHA",
                    )
                )

                contribution_amount = _text(
                    _find_direct(
                        contribution,
                        "SCHUM-HAFRASHA",
                    )
                )

                rows.append(
                    {
                        "מספר רשומה": row_number,
                        "שם עובד": f"{first} {last}".strip(),
                        "ת.ז": person_id,
                        "חודש שכר": month,
                        "שכר מדווח": float(
                            salary or 0
                        ),
                        "הפקדה אחרונה": last_dep,
                        "קוד הפרשה": kind,
                        "סוג הפרשה": (
                            CONTRIBUTION_LABELS.get(
                                kind,
                                f"קוד {kind}",
                            )
                        ),
                        "שיעור הפרשה": float(
                            contribution_rate or 0
                        ),
                        "סכום הפרשה": float(
                            contribution_amount or 0
                        ),
                    }
                )

    return rows


def build_employee_summary(
    contribution_rows: list[dict],
) -> list[dict]:
    grouped: dict[tuple, dict] = {}

    for row in contribution_rows:
        key = (
            row["שם עובד"],
            row["ת.ז"],
            row["חודש שכר"],
            row["שכר מדווח"],
            row["הפקדה אחרונה"],
        )

        if key not in grouped:
            grouped[key] = {
                "שם עובד": row["שם עובד"],
                "ת.ז": row["ת.ז"],
                "חודש שכר": row["חודש שכר"],
                "שכר מדווח": row["שכר מדווח"],
                "הפקדה אחרונה": row["הפקדה אחרונה"],
                "תגמולי עובד": 0.0,
                "תגמולי מעסיק": 0.0,
                "פיצויים": 0.0,
                "אובדן כושר עבודה": 0.0,
                "הפרשות אחרות": 0.0,
                "סה״כ הפרשות": 0.0,
            }

        amount = float(
            row["סכום הפרשה"] or 0
        )

        kind = str(
            row["קוד הפרשה"]
        )

        target = {
            "1": "פיצויים",
            "2": "תגמולי עובד",
            "3": "תגמולי מעסיק",
            "6": "אובדן כושר עבודה",
        }.get(
            kind,
            "הפרשות אחרות",
        )

        grouped[key][target] += amount
        grouped[key]["סה״כ הפרשות"] += amount

    return list(
        grouped.values()
    )


def _digits(value: str) -> str:
    return "".join(
        char
        for char in str(value or "")
        if char.isdigit()
    )


def parse_fund_identifier(
    identifier: str,
) -> tuple[str, str]:
    """
    KOD-MEZAHE-KUPA-H-P בנוי מ-30 ספרות.

    9 הספרות הראשונות הן ח.פ החברה המנהלת.

    מספר הקופה מופיע בחלק שאחרי הח.פ
    כשהוא מוקף באפסים.

    לדוגמה:

    513026484000000000002090000000

    יהפוך ל:

    ח.פ 513026484
    מספר קופה 209
    """

    digits = _digits(
        identifier
    )

    if len(digits) < 9:
        return "", ""

    company_id = digits[:9]

    remaining = digits[9:]

    # לפי מבנה הקוד,
    # שבע הספרות האחרונות הן מילוי.
    if len(remaining) > 7:
        fund_part = remaining[:-7]
    else:
        fund_part = remaining

    fund_number = fund_part.lstrip("0")

    return company_id, fund_number


def extract_fund_deposits(
    tree,
    accounts: dict[str, list[dict]],
) -> list[dict]:
    """
    מפיק טבלה מרוכזת של הקופות
    והסכום להפקדה בכל קופה.
    """

    root = tree.getroot()

    grouped: dict[
        tuple[str, str],
        dict,
    ] = {}

    transfer_blocks = _find_all(
        root,
        "PirteiHaavaratKsafim",
    )

    for block_index, transfer_block in enumerate(
        transfer_blocks,
        start=1,
    ):
        identifier_node = _find_direct(
            transfer_block,
            "KOD-MEZAHE-KUPA-H-P",
        )

        identifier = _text(
            identifier_node
        )

        company_id, fund_number = parse_fund_identifier(
            identifier
        )

        # חישוב הסכום בפועל מתוך
        # כל רשומות ההפרשה בקופה.
        contribution_nodes = transfer_block.xpath(
            ".//*[local-name()='SCHUM-HAFRASHA']"
        )

        total_amount = Decimal("0")

        for contribution_node in contribution_nodes:
            value = _text(
                contribution_node
            )

            if not value:
                continue

            try:
                total_amount += Decimal(
                    value
                )

            except InvalidOperation:
                continue

        account = None

        if company_id:
            # הייבוא נמצא כאן כדי למנוע
            # תלות מעגלית בין הקבצים.
            from account_lookup import find_account

            account = find_account(
                accounts,
                company_id=company_id,
                fund_number=fund_number,
            )

        if account:
            fund_name = account.get(
                "שם קופה",
                "",
            )

            company_name = account.get(
                "שם חברה",
                "",
            )

            matched_fund_number = account.get(
                "מספר קופה",
                fund_number,
            )

            bank_code = account.get(
                "קוד בנק",
                "",
            )

            branch_code = account.get(
                "קוד סניף",
                "",
            )

            account_number_raw = str(
                account.get(
                    "מספר חשבון",
                    "",
                )
                or ""
            ).strip()

            account_number = "".join(
                char
                for char in account_number_raw
                if char.isdigit()
            ).zfill(20)

            bank_account = account.get(
                "פרטי חשבון",
                "",
            )

            match_status = "זוהה"

        else:
            fund_name_node = transfer_block.xpath(
                ".//*[local-name()='SHEM-KUPA-ETZEL-MAASIK']"
            )

            fund_name = (
                _text(fund_name_node[0])
                if fund_name_node
                else "לא זוהה"
            )

            company_name = ""
            matched_fund_number = fund_number
            bank_code = ""
            branch_code = ""
            account_number = ""
            bank_account = ""
            match_status = "לא זוהה באקסל"

        key = (
            company_id,
            matched_fund_number or fund_number,
        )

        if key not in grouped:
            grouped[key] = {
                "שם חברה מנהלת": company_name,
                "שם קופה": fund_name,
                "ח.פ חברה מנהלת": company_id,
                "מספר קופה": (
                    matched_fund_number
                    or fund_number
                ),
                "סכום להפקדה": 0.0,
                "קוד בנק": bank_code,
                "קוד סניף": branch_code,
                "מספר חשבון": account_number,
                "פרטי חשבון": bank_account,
                "סטטוס זיהוי": match_status,
                "קוד קופה מהקובץ": identifier,
            }

        grouped[key][
            "סכום להפקדה"
        ] += float(
            total_amount
        )

    rows = list(
        grouped.values()
    )

    for row in rows:
        row["סכום להפקדה"] = round(
            float(
                row["סכום להפקדה"]
            ),
            2,
        )

    return rows


def to_bytes(tree) -> bytes:
    return etree.tostring(
        tree,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )
