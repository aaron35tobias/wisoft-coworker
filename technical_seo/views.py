from io import BytesIO
import os
import re
import textwrap
import zipfile
from xml.sax.saxutils import escape as xml_escape

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify

from .models import TechnicalSEOAudit, TechnicalSEOIssue, TechnicalSEOWebsite
from .tasks import run_technical_seo_audit_task
from wisoft_co_worker.task_utils import enqueue_background_task

DEFAULT_CRAWL_PAGE_LIMIT = 5000


def get_crawl_page_limit():
    try:
        return int(os.environ.get('TECHNICAL_SEO_MAX_CRAWL_PAGES', DEFAULT_CRAWL_PAGE_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_CRAWL_PAGE_LIMIT


def get_user_audit(user, audit_id):
    return get_object_or_404(
        TechnicalSEOAudit.objects.select_related('website', 'requested_by'),
        id=audit_id,
        website__added_by=user,
    )


def clean_cell(value):
    if value is None:
        return ''
    return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', str(value))


def audit_export_filename(audit, extension):
    website_slug = slugify(audit.website.website_url.replace('https://', '').replace('http://', '')) or 'website'
    date_part = audit.started_at.strftime('%Y%m%d')
    return f'technical-seo-audit-{website_slug}-{date_part}.{extension}'


def get_audit_export_context(audit):
    issues = list(audit.issues.select_related('page').order_by('severity', 'issue_type', 'created_at'))
    pages = list(audit.pages.order_by('depth', 'url'))
    gsc_rows = list(audit.gsc_rows.order_by('-clicks', '-impressions', 'position'))
    gsc_inspections = list(audit.gsc_url_inspections.select_related('page').order_by('inspection_url'))
    return {
        'audit': audit,
        'issues': issues,
        'pages': pages,
        'gsc_rows': gsc_rows,
        'gsc_inspections': gsc_inspections,
        'ai_summary_sections': parse_ai_summary_sections(audit.ai_summary) if audit.ai_summary else [],
    }


def build_export_sheets(export_context):
    audit = export_context['audit']
    overview_rows = [
        ['Field', 'Value'],
        ['Website URL', audit.website.website_url],
        ['Status', audit.status],
        ['Started At', audit.started_at.strftime('%Y-%m-%d %H:%M')],
        ['Completed At', audit.completed_at.strftime('%Y-%m-%d %H:%M') if audit.completed_at else ''],
        ['Pages Crawled', audit.pages_crawled],
        ['Issues Found', audit.issues_found],
        ['Critical Issues', audit.critical_issues],
        ['High Issues', audit.high_issues],
        ['Medium Issues', audit.medium_issues],
        ['Low Issues', audit.low_issues],
        ['AI Model', audit.ai_model],
        ['AI Error', audit.ai_error],
        ['PageSpeed Status', audit.pagespeed_status],
        ['PageSpeed Error', audit.pagespeed_error],
        ['PageSpeed Mobile Performance', (audit.pagespeed_mobile or {}).get('performance_score', '')],
        ['PageSpeed Desktop Performance', (audit.pagespeed_desktop or {}).get('performance_score', '')],
        ['GSC Status', audit.gsc_status],
        ['GSC Site URL', audit.gsc_site_url],
        ['GSC Rows Found', audit.gsc_rows_found],
        ['GSC URL Inspections Found', audit.gsc_inspections_found],
    ]

    ai_rows = [['Section', 'Recommendation']]
    if export_context['ai_summary_sections']:
        for section in export_context['ai_summary_sections']:
            for item in section['items']:
                ai_rows.append([section['title'], item])
    elif audit.ai_summary:
        ai_rows.append(['Summary', audit.ai_summary])

    issue_rows = [['Severity', 'Type', 'Title', 'Page URL', 'Evidence', 'Recommendation', 'Status', 'Created At']]
    for issue in export_context['issues']:
        issue_rows.append([
            issue.severity,
            issue.issue_type,
            issue.title,
            issue.page.url if issue.page else '',
            issue.evidence,
            issue.recommendation,
            issue.status,
            issue.created_at.strftime('%Y-%m-%d %H:%M'),
        ])

    page_rows = [[
        'URL', 'Final URL', 'Status Code', 'Content Type', 'Depth', 'Title', 'Meta Description',
        'Canonical URL', 'Robots Directives', 'H1 Count', 'H2 Count', 'Internal Links',
        'External Links', 'Images', 'Images Missing Alt', 'Load Time MS', 'Error',
    ]]
    for page in export_context['pages']:
        page_rows.append([
            page.url,
            page.final_url,
            page.status_code,
            page.content_type,
            page.depth,
            page.title,
            page.meta_description,
            page.canonical_url,
            page.robots_directives,
            page.h1_count,
            page.h2_count,
            page.internal_links_count,
            page.external_links_count,
            page.images_count,
            page.images_missing_alt_count,
            page.load_time_ms,
            page.error_message,
        ])

    inspection_rows = [[
        'Inspection URL', 'Verdict', 'Coverage State', 'Indexing State', 'Robots.txt State',
        'Page Fetch State', 'Google Canonical', 'User Canonical', 'Last Crawl Time',
        'Mobile Usability', 'Rich Results', 'Error',
    ]]
    for item in export_context['gsc_inspections']:
        inspection_rows.append([
            item.inspection_url,
            item.verdict,
            item.coverage_state,
            item.indexing_state,
            item.robots_txt_state,
            item.page_fetch_state,
            item.google_canonical,
            item.user_canonical,
            item.last_crawl_time.strftime('%Y-%m-%d %H:%M') if item.last_crawl_time else '',
            item.mobile_usability_verdict,
            item.rich_results_verdict,
            item.error_message,
        ])

    gsc_rows = [['Page URL', 'Query', 'Device', 'Country', 'Clicks', 'Impressions', 'CTR', 'Position', 'Date Start', 'Date End']]
    for row in export_context['gsc_rows']:
        gsc_rows.append([
            row.page_url,
            row.query,
            row.device,
            row.country,
            row.clicks,
            row.impressions,
            row.ctr,
            row.position,
            row.date_range_start.isoformat() if row.date_range_start else '',
            row.date_range_end.isoformat() if row.date_range_end else '',
        ])

    pagespeed_rows = [[
        'Device', 'Performance', 'Accessibility', 'Best Practices', 'SEO',
        'FCP (s)', 'LCP (s)', 'INP (ms)', 'CLS', 'TBT (ms)', 'Speed Index (s)', 'TTFB (s)', 'Final URL',
    ]]
    for label, data in (('Mobile', audit.pagespeed_mobile or {}), ('Desktop', audit.pagespeed_desktop or {})):
        pagespeed_rows.append([
            label,
            data.get('performance_score', ''),
            data.get('accessibility_score', ''),
            data.get('best_practices_score', ''),
            data.get('seo_score', ''),
            data.get('first_contentful_paint', ''),
            data.get('largest_contentful_paint', ''),
            data.get('interaction_to_next_paint', ''),
            data.get('cumulative_layout_shift', ''),
            data.get('total_blocking_time', ''),
            data.get('speed_index', ''),
            data.get('time_to_first_byte', ''),
            data.get('final_url', ''),
        ])

    return [
        ('Overview', overview_rows),
        ('AI Recommendations', ai_rows),
        ('Issues', issue_rows),
        ('PageSpeed', pagespeed_rows),
        ('Crawled Pages', page_rows),
        ('GSC URL Inspections', inspection_rows),
        ('GSC Search Analytics', gsc_rows),
    ]


def excel_column_name(index):
    name = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def build_xlsx_bytes(sheets):
    def sheet_xml(rows):
        row_xml = []
        for row_index, row in enumerate(rows, start=1):
            cells = []
            for column_index, value in enumerate(row, start=1):
                cell_ref = f'{excel_column_name(column_index)}{row_index}'
                text = xml_escape(clean_cell(value))
                cells.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>')
            row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(row_xml)}</sheetData>'
            '</worksheet>'
        )

    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', ''.join([
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
            '<Default Extension="xml" ContentType="application/xml"/>',
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            *[
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for index, _sheet in enumerate(sheets, start=1)
            ],
            '</Types>',
        ]))
        archive.writestr('_rels/.rels', ''.join([
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>',
            '</Relationships>',
        ]))
        archive.writestr('xl/workbook.xml', ''.join([
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ',
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>',
            *[
                f'<sheet name="{xml_escape(name[:31])}" sheetId="{index}" r:id="rId{index}"/>'
                for index, (name, _rows) in enumerate(sheets, start=1)
            ],
            '</sheets></workbook>',
        ]))
        archive.writestr('xl/_rels/workbook.xml.rels', ''.join([
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
            *[
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
                for index, _sheet in enumerate(sheets, start=1)
            ],
            '</Relationships>',
        ]))
        for index, (_name, rows) in enumerate(sheets, start=1):
            archive.writestr(f'xl/worksheets/sheet{index}.xml', sheet_xml(rows))
    return output.getvalue()


def build_pdf_bytes(title, lines):
    def pdf_string(value):
        text = clean_cell(value).encode('latin-1', 'replace').decode('latin-1')
        return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    objects = [
        '<< /Type /Catalog /Pages 2 0 R >>',
        '',
        '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>',
    ]

    records = []
    index = 0
    while index < len(lines):
        line = clean_cell(lines[index])
        next_line = clean_cell(lines[index + 1]) if index + 1 < len(lines) else ''
        if line and next_line and set(next_line) == {'='}:
            records.append(('section', line))
            index += 2
        elif not line:
            records.append(('space', ''))
            index += 1
        else:
            records.append(('row', line))
            index += 1

    pages = []
    current_ops = []
    y_position = 506
    row_number = 0

    def add_text(ops, x, y, text, size=8, bold=False, color='0.18 0.23 0.31'):
        font = 'F2' if bold else 'F1'
        ops.append(f'BT {color} rg /{font} {size} Tf {x} {y} Td ({pdf_string(text)}) Tj ET')

    def add_header(ops, page_number):
        ops.append('0.02 0.25 0.43 rg 0 535 842 60 re f')
        ops.append('0.00 0.62 0.97 rg 0 535 7 60 re f')
        add_text(ops, 34, 566, title, 18, True, '1 1 1')
        add_text(ops, 34, 546, 'Wisoft Co-Worker SEO Report', 8, False, '0.82 0.91 1')
        add_text(ops, 736, 546, f'Page {page_number}', 8, False, '0.82 0.91 1')

    def add_footer(ops, page_number):
        ops.append('0.86 0.89 0.93 RG 32 31 778 0.5 re f')
        add_text(ops, 34, 18, 'Generated from Wisoft Co-Worker', 7, False, '0.42 0.47 0.55')
        add_text(ops, 760, 18, f'Page {page_number}', 7, False, '0.42 0.47 0.55')

    def finish_page():
        nonlocal current_ops
        if current_ops:
            page_number = len(pages) + 1
            add_footer(current_ops, page_number)
            pages.append(current_ops)
        current_ops = []

    def start_page():
        nonlocal current_ops, y_position
        current_ops = []
        add_header(current_ops, len(pages) + 1)
        y_position = 506

    start_page()
    for record_type, value in records:
        if record_type == 'space':
            y_position -= 8
            continue

        if record_type == 'section':
            if y_position < 82:
                finish_page()
                start_page()
            current_ops.append('0.00 0.62 0.97 rg 32 {0} 778 20 re f'.format(y_position - 3))
            add_text(current_ops, 42, y_position + 3, value, 10, True, '1 1 1')
            y_position -= 32
            row_number = 0
            continue

        wrapped = textwrap.wrap(value, width=145) or ['']
        row_height = max(18, 10 * len(wrapped) + 8)
        if y_position - row_height < 42:
            finish_page()
            start_page()
        fill = '0.97 0.98 0.99' if row_number % 2 == 0 else '1 1 1'
        current_ops.append(f'{fill} rg 32 {y_position - row_height + 7} 778 {row_height} re f')
        current_ops.append('0.88 0.91 0.95 RG 32 {0} 778 0.35 re S'.format(y_position - row_height + 7))
        text_y = y_position
        for wrapped_line in wrapped:
            add_text(current_ops, 42, text_y, wrapped_line, 7.5, False)
            text_y -= 10
        y_position -= row_height
        row_number += 1

    finish_page()

    page_object_ids = []
    content_object_ids = []
    next_object_id = 5
    for _page in pages:
        page_object_ids.append(next_object_id)
        content_object_ids.append(next_object_id + 1)
        next_object_id += 2

    objects[1] = f'<< /Type /Pages /Kids [{" ".join(f"{object_id} 0 R" for object_id in page_object_ids)}] /Count {len(page_object_ids)} >>'

    for page_ops, page_object_id, content_object_id in zip(pages, page_object_ids, content_object_ids):
        content = '\n'.join(page_ops)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_object_id} 0 R >>')
        objects.append(f'<< /Length {len(content.encode("utf-8"))} >>\nstream\n{content}\nendstream')

    output = BytesIO()
    output.write(b'%PDF-1.4\n')
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f'{index} 0 obj\n{body}\nendobj\n'.encode('utf-8'))
    xref_position = output.tell()
    output.write(f'xref\n0 {len(objects) + 1}\n'.encode('utf-8'))
    output.write(b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        output.write(f'{offset:010d} 00000 n \n'.encode('utf-8'))
    output.write(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_position}\n%%EOF'.encode('utf-8'))
    return output.getvalue()


def get_website_dashboard_queryset(user):
    websites = list(
        TechnicalSEOWebsite.objects.filter(added_by=user, is_active=True)
        .prefetch_related('technical_seo_audits')
    )
    for website in websites:
        audits = list(website.technical_seo_audits.all())
        latest_audit = audits[0] if audits else None
        website.latest_audit = latest_audit
        website.audit_count = len(audits)
        website.latest_issues_found = latest_audit.issues_found if latest_audit else 0
        website.latest_pages_crawled = latest_audit.pages_crawled if latest_audit else 0
    return websites


def parse_ai_summary_sections(summary):
    sections = []
    current_title = 'Summary'
    current_lines = []
    section_keywords = [
        'executive summary',
        'top priorities',
        'corrective actions',
        'search console insights',
        'developer notes',
        'summary',
        'priorities',
        'actions',
        'insights',
        'notes',
    ]

    def append_section():
        body_lines = [line for line in current_lines if line.lower() != 'summary complete.']
        if not body_lines:
            return
        sections.append({
            'title': current_title,
            'body': '\n'.join(body_lines),
            'items': body_lines,
        })

    def clean_summary_line(line):
        return re.sub(r'^(?:[-*\u2022]\s+|\d+[\.\)]\s+)', '', line).strip()

    for raw_line in summary.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = re.sub(r'^\d+[\.\)]\s*', '', line.strip('*#:- ')).strip()
        is_heading = (
            len(normalized) <= 60
            and not normalized.endswith('.')
            and any(keyword in normalized.lower() for keyword in section_keywords)
        )

        if is_heading:
            if current_lines:
                append_section()
            current_title = normalized
            current_lines = []
        else:
            current_lines.append(clean_summary_line(line))

    if current_lines:
        append_section()

    return sections[:6]


@login_required(login_url='sign-in')
def audits_view(request, website_id=None):
    website = None
    websites = get_website_dashboard_queryset(request.user)

    if website_id is not None:
        website = get_object_or_404(
            TechnicalSEOWebsite,
            id=website_id,
            added_by=request.user,
        )

    context = {
        'website': website,
        'websites': websites,
    }
    return render(request, 'technical_seo/audits.html', context)


@login_required(login_url='sign-in')
def audit_history_view(request, website_id=None):
    website = None
    audits = TechnicalSEOAudit.objects.filter(
        website__added_by=request.user,
    ).select_related('website', 'requested_by')
    websites = get_website_dashboard_queryset(request.user)

    if website_id is not None:
        website = get_object_or_404(
            TechnicalSEOWebsite,
            id=website_id,
            added_by=request.user,
        )
        audits = audits.filter(website=website)

    context = {
        'website': website,
        'websites': websites,
        'audits': audits,
    }
    return render(request, 'technical_seo/audit_history.html', context)


@login_required(login_url='sign-in')
def audit_run_view(request):
    if request.method != 'POST':
        return redirect('technical_seo:audits')

    website_url = request.POST.get('website_url', '').strip()
    note = request.POST.get('note', '').strip()
    if not website_url:
        messages.error(request, 'Website URL is required.')
        return redirect('technical_seo:audits')

    try:
        URLValidator()(website_url)
    except ValidationError:
        messages.error(request, 'Enter a valid website URL.')
        return redirect('technical_seo:audits')

    max_pages = max(1, min(get_crawl_page_limit(), 32767))

    website, _created = TechnicalSEOWebsite.objects.get_or_create(
        website_url=website_url,
        added_by=request.user,
        defaults={
            'note': note,
            'is_active': True,
        },
    )
    if note and website.note != note:
        website.note = note
        website.save(update_fields=['note', 'date_modified'])

    audit = TechnicalSEOAudit.objects.create(
        website=website,
        requested_by=request.user,
        max_pages=max_pages,
    )

    queued = enqueue_background_task(
        run_technical_seo_audit_task,
        audit,
        'Technical SEO audit could not be queued',
    )
    if queued:
        messages.success(request, 'Technical SEO audit started. The crawler will follow the website URL until the site queue is complete or the server crawl limit is reached.')
    else:
        messages.error(request, 'Technical SEO audit could not be queued. Check Redis/Celery and open the detail page for the error.')
    return redirect('technical_seo:audit-detail', audit.id)


@login_required(login_url='sign-in')
def audit_delete_view(request, audit_id):
    audit = get_object_or_404(
        TechnicalSEOAudit.objects.select_related('website'),
        id=audit_id,
        website__added_by=request.user,
    )

    if request.method == 'POST':
        website_id = audit.website_id
        audit.delete()
        messages.success(request, 'Technical SEO audit history deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('technical_seo:website-history', website_id)

    return redirect('technical_seo:history')


@login_required(login_url='sign-in')
def audit_detail_view(request, audit_id):
    audit = get_user_audit(request.user, audit_id)
    issues = audit.issues.select_related('page')
    pages = audit.pages.all()
    gsc_inspections = audit.gsc_url_inspections.select_related('page')
    issue_type_counts = list(issues.values('issue_type').annotate(total=Count('id')).order_by('-total', 'issue_type'))
    for row in issue_type_counts:
        row['label'] = row['issue_type'].replace('_', ' ').title()

    severity_filter = request.GET.get('severity', '').strip()
    if severity_filter:
        issues = issues.filter(severity=severity_filter)

    issue_type_filter = request.GET.get('issue_type', '').strip()
    if issue_type_filter:
        issues = issues.filter(issue_type=issue_type_filter)

    gsc_inspection_verdict = request.GET.get('gsc_verdict', '').strip()
    if gsc_inspection_verdict:
        gsc_inspections = gsc_inspections.filter(verdict=gsc_inspection_verdict)

    context = {
        'audit': audit,
        'issues': issues,
        'pages': pages,
        'gsc_inspections': gsc_inspections,
        'gsc_filters': {
            'verdict': gsc_inspection_verdict,
        },
        'gsc_verdicts': audit.gsc_url_inspections.exclude(verdict='').values_list('verdict', flat=True).distinct().order_by('verdict'),
        'issue_type_counts': issue_type_counts,
        'ai_summary_sections': parse_ai_summary_sections(audit.ai_summary) if audit.ai_summary else [],
        'severity_filter': severity_filter,
        'severity_choices': TechnicalSEOIssue.SEVERITY_CHOICES,
        'back_to_audits_url': reverse('technical_seo:history'),
        'issue_type_filter': issue_type_filter,
    }
    return render(request, 'technical_seo/audit_detail.html', context)


@login_required(login_url='sign-in')
def audit_export_excel_view(request, audit_id):
    audit = get_user_audit(request.user, audit_id)
    export_context = get_audit_export_context(audit)
    xlsx_bytes = build_xlsx_bytes(build_export_sheets(export_context))
    response = HttpResponse(
        xlsx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{audit_export_filename(audit, "xlsx")}"'
    return response


@login_required(login_url='sign-in')
def audit_export_pdf_view(request, audit_id):
    audit = get_user_audit(request.user, audit_id)
    export_context = get_audit_export_context(audit)
    lines = [
        'Technical SEO Audit',
        f'Website: {audit.website.website_url}',
        f'Status: {audit.status}',
        f'Started: {audit.started_at.strftime("%Y-%m-%d %H:%M")}',
        f'Completed: {audit.completed_at.strftime("%Y-%m-%d %H:%M") if audit.completed_at else ""}',
        f'Pages Crawled: {audit.pages_crawled}',
        f'Issues Found: {audit.issues_found}',
        f'Critical: {audit.critical_issues} | High: {audit.high_issues} | Medium: {audit.medium_issues} | Low: {audit.low_issues}',
        '',
    ]

    for sheet_name, rows in build_export_sheets(export_context):
        lines.append(sheet_name)
        lines.append('=' * len(sheet_name))
        for row in rows:
            lines.append(' | '.join(clean_cell(value) for value in row))
        lines.append('')

    pdf_bytes = build_pdf_bytes('Technical SEO Audit', lines)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{audit_export_filename(audit, "pdf")}"'
    return response


@login_required(login_url='sign-in')
def audit_status_view(request, audit_id):
    audit = get_user_audit(request.user, audit_id)

    return JsonResponse({
        "status": audit.status,
        "pages_crawled": audit.pages_crawled,
        "issues_found": audit.issues_found,
        "gsc_status": audit.gsc_status,
        "pagespeed_status": audit.pagespeed_status,
        "ai_ready": bool(audit.ai_summary),
        "detail_url": reverse("technical_seo:audit-detail", args=[audit.id]),
    })
