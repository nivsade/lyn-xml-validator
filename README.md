# LYN XML Fix

מערכת Streamlit פשוטה שמקבלת קובץ XML/DAT של ממשק מעסיקים ומחזירה:

1. קובץ DAT מתוקן לגרסה 006.
2. קובץ Excel עם סיכום עובדים, פירוט הפרשות, תיקונים ושגיאות XSD.

## בדיקות ותיקונים

- אימות מלא מול XSD הרשמי לגרסה 006.
- תיקון `MISPAR-GIRSAT-XML` ל-`006`.
- קיבוע פרטי השולח של לין ופרטי המסלקה.
- הוספת `HAFKADA-ACHRONA` במיקום הנכון.
- אפשרות לקבוע סוג מזהה מעסיק: ח.פ (1) או עוסק מורשה (5).
- השלמת שדות חשבון וסניף שערכם 0 לאורך הנדרש.

## הפעלה ב-VS Code

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```
