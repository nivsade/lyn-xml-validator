from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from lxml import etree

from xml_service import parse_xml, to_bytes

XSI = '{http://www.w3.org/2001/XMLSchema-instance}nil'

def child(node, tag):
    return next((x for x in node if etree.QName(x).localname == tag), None)

def get(node, tag):
    x = child(node, tag)
    return (x.text or '').strip() if x is not None else ''

def put(node, tag, value):
    x = child(node, tag)
    if x is None:
        raise ValueError(f'חסר שדה נדרש במקור: {tag}')
    x.attrib.pop(XSI, None)
    x.text = str(value)

def all_named(root, tag):
    return root.xpath(f'.//*[local-name()="{tag}"]')

def employer_info(data):
    root = parse_xml(data).getroot()
    transfers = all_named(root, 'PirteiHaavaratKsafim')
    if not transfers:
        raise ValueError('לא נמצאו פרטי מעסיק בקובץ')
    t = transfers[0]
    ids = {(get(x,'MISPAR-ZIHUY-MAASIK'),get(x,'SHEM-MAASIK')) for x in transfers}
    if len({x[0] for x in ids}) > 1:
        raise ValueError('בקובץ יש מספר מעסיקים. יש להעלות קובץ של מעסיק אחד בלבד.')
    employees = {}
    funds = {}
    for t in transfers:
        code = get(t, 'KOD-MEZAHE-KUPA-H-P')
        for p in all_named(t, 'PirteiKupa'):
            funds.setdefault(code, get(p, 'SHEM-KUPA-ETZEL-MAASIK') or code)
            for e in all_named(p, 'PirteiOved'):
                pid = get(e, 'MISPAR-MEZAHE')
                employees.setdefault(pid, f'{get(e,"SHEM-PRATI")} {get(e,"SHEM-MISHPACHA")} ({pid})')
    return {'name':get(t,'SHEM-MAASIK'), 'id':get(t,'MISPAR-ZIHUY-MAASIK'), 'withholding':get(t,'MISPAR-TIK-NIKUIM-MAASIK'), 'employees':employees, 'funds':funds}

def create_negative(data, *, employee_id, fund_code, salary_month, amount_parts, bank, reason_code='2', declaration_filename='', employee_approval_filename=''):
    tree = parse_xml(data)
    root = tree.getroot()
    transfers = all_named(root, 'PirteiHaavaratKsafim')
    if len({get(t,'MISPAR-ZIHUY-MAASIK') for t in transfers}) != 1:
        raise ValueError('יש להעלות קובץ של מעסיק יחיד')
    matches = [(t,p,e) for t in transfers for p in all_named(t,'PirteiKupa') for e in all_named(p,'PirteiOved') if get(e,'MISPAR-MEZAHE') == employee_id]
    if not matches:
        raise ValueError('העובד לא נמצא בקובץ השכר. העלה קובץ המכיל את העובד.')
    # Prefer a record for the selected fund, but allow a different fund from the same employer.
    t,p,e = next(((t,p,e) for t,p,e in matches if get(t,'KOD-MEZAHE-KUPA-H-P') == fund_code), matches[0])
    total = sum((Decimal(str(x)) for x in amount_parts), Decimal('0'))
    if total <= 0 or any(Decimal(str(x)) < 0 for x in amount_parts):
        raise ValueError('סכומי ההחזר חייבים להיות חיוביים')
    if not (len(salary_month)==6 and salary_month.isdigit() and 1 <= int(salary_month[:2]) <= 12):
        raise ValueError('חודש שכר חייב להיות MMYYYY')
    if not (bank['bank'].isdigit() and bank['branch'].isdigit() and bank['account'].isdigit()):
        raise ValueError('פרטי הבנק חייבים להכיל ספרות בלבד')
    # Rebuild using source structure; never retain unrelated employees/transfers.
    container = t.getparent()
    for old in list(container):
        if etree.QName(old).localname == 'PirteiHaavaratKsafim':
            container.remove(old)
    t = deepcopy(t)
    container.append(t)
    put(t,'KOD-MEZAHE-KUPA-H-P',fund_code)
    put(t,'SUG-PEULA','5')
    put(t,'SACH-HAFKADA-KUPA-H-P',f'{total:.2f}')
    put(t,'MISPAR-BANK-MAASIK',bank['bank'].zfill(3))
    put(t,'MISPAR-SNIF-MAASIK',bank['branch'].zfill(3))
    put(t,'MISPAR-CHESHBON-MAASIK',bank['account'].zfill(20))
    put(t,'MISPAR-ZIHUI',str(uuid4()))
    if child(t,'SCHUM-HAFKADA-KOLEL') is not None:
        put(t,'SCHUM-HAFKADA-KOLEL','0.00')
    for old in list(t):
        if etree.QName(old).localname == 'PirteiKupa':
            t.remove(old)
    p = deepcopy(p)
    t.append(p)
    for old in list(p):
        if etree.QName(old).localname == 'PirteiOved':
            p.remove(old)
    e = deepcopy(e)
    p.append(e)
    for old in list(e):
        if etree.QName(old).localname == 'ChodeshMaskoretVestatusOved':
            e.remove(old)
    source_blocks = all_named(matches[0][2], 'ChodeshMaskoretVestatusOved')
    matching = [b for b in source_blocks if get(b,'CHODESH-MASKORET').startswith(salary_month[2:]+'-'+salary_month[:2])]
    if not matching:
        matching = source_blocks
    if not matching:
        raise ValueError('אין רשומת שכר לעובד בקובץ המקור')
    block = deepcopy(matching[0])
    e.append(block)
    put(block,'CHODESH-MASKORET',f'{salary_month[2:]}-{salary_month[:2]}-01')
    if child(block,'SIBAT-BAKASH-LECHZER-KSAFIM') is not None:
        put(block,'SIBAT-BAKASH-LECHZER-KSAFIM',reason_code)
    for old in list(block):
        if etree.QName(old).localname == 'PizulHafrashotOvedBeKupa':
            block.remove(old)
    source_parts = all_named(matching[0], 'PizulHafrashotOvedBeKupa')
    if not source_parts:
        raise ValueError('לא נמצאו רכיבי הפרשה בקובץ המקור')
    for kind, amount in zip(('2','3','1'),amount_parts):
        if Decimal(str(amount)) == 0:
            continue
        part = deepcopy(next((x for x in source_parts if get(x,'SUG-HAFRASHA')==kind),source_parts[0]))
        put(part,'SUG-HAFRASHA',kind)
        put(part,'SCHUM-HAFRASHA',f'{Decimal(str(amount)):.2f}')
        if child(part,'MISPAR-MEZAHE-RESHUMA') is not None:
            put(part,'MISPAR-MEZAHE-RESHUMA',str(uuid4()))
        if child(part,'MISPAR-MEZAHE-RESHUMA-KODEM') is not None:
            old = child(part,'MISPAR-MEZAHE-RESHUMA-KODEM');old.text=None;old.set(XSI,'true')
        summary = child(block,'SachHafrashaLeKupaBechodeshMaskoretOved')
        block.insert(block.index(summary) if summary is not None else len(block),part)
    for parent, field in ((block,'SACH-HAFRASHA-BECHODESH-MASKORET'),(e,'SACH-HAFRASHA-LEOVED-BEKUPA'),(p,'SACH-HAFRASHA-LEKUPA-BERAMAT-MAASIK'),(p,'SACH-HAFKADA-LEKUPA-BERAMAT-MAASIK')):
        node=all_named(parent,field)
        if node: node[0].text=f'{total:.2f}'
    # Document filename references only: PDF bytes are not embedded in XML.
    docs = all_named(t,'ZihuiShemMismachBeramatEirua')
    if docs:
        d=docs[0]
        if declaration_filename:
            put(d,'SHEM-KOVETZ-SHEL-MISMACH-BERAMAT-EIRUA-VEBERAMAT-LAKOACH',declaration_filename)
        else:
            t.remove(d)
    header = all_named(root,'KoteretKovetz')[0]
    put(header,'SUG-MIMSHAK','13')
    put(header,'MISPAR-GIRSAT-XML','006')
    now=datetime.now().strftime('%Y%m%d%H%M%S')
    put(header,'TAARICH-BITZUA',now)
    serial='0001'
    if child(header,'MISPAR-SIDURI') is not None: put(header,'MISPAR-SIDURI','1')
    if child(header,'MISPAR-HAKOVETZ') is not None:
        put(header,'MISPAR-HAKOVETZ',now+'0000000'+'058893207'+serial)
    for closing, val in [('MISPAR-KUPOT-YATZRANIM-BAKOVETZ','1'),('MISPAR-MAASIKIM','1'),('MISPAR-AMITIM','1'),('MISPAR-RESHUMOT',str(sum(Decimal(str(v))>0 for v in amount_parts))),('SACH-HAFRASHOT-BAKOVETZ',f'{total:.2f}'),('SACH-HAFKADOT-BAKOVETZ',f'{total:.2f}')]:
        nodes=all_named(root,closing)
        if nodes: nodes[-1].text=val
    filename=f'006000058893207EMPNEG000006{now}{serial}.DAT'
    return to_bytes(tree), filename
