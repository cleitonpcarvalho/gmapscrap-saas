"""Shared CSV/XLSX fields and spreadsheet-safe text; no formula cells."""
import csv
from io import BytesIO, StringIO
import json
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.models import Lead, LeadWebsiteQualification as Result
from backend.services.website_qualification_jobs import result_data, filter_query

FIELDS = ("normalized_website", "site_availability", "cms", "cms_name", "wordpress_status", "blog_status",
          "blog_url", "total_posts", "last_published_at", "last_post_title", "last_post_url", "days_since_publication",
          "priority", "validation_status", "checked_at", "evidence", "errors")
HEADERS = ["Nicho", "Localidade", "Nome", "Endereço", "Telefone", "Site", "Email", "Insights do site", *FIELDS]


def safe_text(value):
    if value is None: return ""
    if isinstance(value, (list, dict)): value = json.dumps(value, ensure_ascii=False)
    elif hasattr(value, "isoformat"): value = value.isoformat()
    value = str(value)
    value = "".join(c for c in value if c in "\n\r\t" or 32 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        value = "'" + value
    return value


def rows(db, **filters):
    stmt = filter_query(select(Lead).options(selectinload(Lead.search_run)), **filters).order_by(Lead.created_at.desc(), Lead.id)
    results = {r.lead_id: result_data(r) for r in db.scalars(select(Result))}
    yield HEADERS
    for lead in db.scalars(stmt):
        result = results.get(lead.id) or {}
        yield [safe_text(v) for v in [lead.niche, lead.location, lead.name, lead.address, lead.phone, lead.website,
                                     lead.email, lead.site_insights, *[result.get(key) for key in FIELDS]]]


def csv_bytes(db, **filters):
    output = StringIO()
    csv.writer(output).writerows(rows(db, **filters))
    return output.getvalue().encode("utf-8-sig")


def xlsx_bytes(db, **filters):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Leads" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        with archive.open("xl/worksheets/sheet1.xml", "w") as sheet:
            sheet.write(b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
            for index, row in enumerate(rows(db, **filters), 1):
                cells = "".join('<c t="inlineStr"><is><t xml:space="preserve">' + escape(safe_text(value)[:32767]) + '</t></is></c>' for value in row)
                sheet.write(f'<row r="{index}">{cells}</row>'.encode())
            sheet.write(b'</sheetData></worksheet>')
    return output.getvalue()
