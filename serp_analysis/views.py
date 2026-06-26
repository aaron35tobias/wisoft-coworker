from io import BytesIO
import re
import textwrap
import zipfile
from xml.sax.saxutils import escape as xml_escape

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

from .analyzer import normalize_url
from .models import SERPAnalysis
from .tasks import run_serp_analysis_task
from wisoft_co_worker.task_utils import enqueue_background_task


SCORE_LABELS = [
    ('overall', 'Overall'),
    ('content', 'Content'),
    ('meta', 'Meta'),
    ('technical', 'Technical'),
    ('media_schema', 'Media / Schema'),
    ('links', 'Links'),
    ('pagespeed', 'PageSpeed'),
]


def parse_ai_summary_sections(summary):
    sections = []
    current_title = 'Summary'
    current_lines = []
    heading_keywords = [
        'executive summary',
        'summary',
        'content strategy',
        'competitor strategy',
        'serp opportunities',
        'opportunities',
        'technical findings',
        'technical',
        'meta',
        'canonical',
        'page speed',
        'recommendations',
        'actions',
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

    for raw_line in (summary or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = re.sub(r'^\d+[\.\)]\s*', '', line.strip('*#:- ')).strip()
        is_heading = (
            len(normalized) <= 70
            and not normalized.endswith('.')
            and any(keyword in normalized.lower() for keyword in heading_keywords)
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


def validate_url(value, label, required=False):
    value = (value or '').strip()
    if not value and required:
        raise ValidationError(f'{label} is required.')
    if not value:
        return ''
    normalized = normalize_url(value)
    URLValidator()(normalized)
    return normalized


def get_user_analysis(user, analysis_id):
    return get_object_or_404(SERPAnalysis, id=analysis_id, requested_by=user)


def clean_cell(value):
    if value is None:
        return ''
    return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', str(value))


def export_filename(analysis, extension):
    keyword_slug = slugify(analysis.keyword) or 'keyword'
    date_part = analysis.started_at.strftime('%Y%m%d')
    return f'serp-analysis-{keyword_slug}-{date_part}.{extension}'


def build_export_sheets(analysis):
    ai_sections = parse_ai_summary_sections(analysis.ai_summary)
    scorecard_rows = build_scorecard_rows(analysis)
    comparison_rows = build_comparison_rows(analysis)
    target = analysis.target_snapshot or {}
    snapshots = []
    if target:
        snapshots.append(('Target', target))
    for snapshot in analysis.competitor_snapshots or []:
        snapshots.append(('Competitor', snapshot))

    overview_rows = [
        ['Field', 'Value'],
        ['Keyword', analysis.keyword],
        ['Location', analysis.location],
        ['Status', analysis.status],
        ['Target URL', analysis.target_url],
        ['Competitor Count', analysis.competitor_count],
        ['Opportunity Count', len(analysis.serp_opportunities or [])],
        ['Technical Finding Count', len(analysis.technical_findings or [])],
        ['Started At', analysis.started_at.strftime('%Y-%m-%d %H:%M')],
        ['Completed At', analysis.completed_at.strftime('%Y-%m-%d %H:%M') if analysis.completed_at else ''],
        ['AI Model', analysis.ai_model],
        ['AI Error', analysis.ai_error],
        ['Error Message', analysis.error_message],
    ]

    ai_rows = [['Section', 'Recommendation']]
    if ai_sections:
        for section in ai_sections:
            for item in section['items']:
                ai_rows.append([section['title'], item])
    elif analysis.ai_summary:
        ai_rows.append(['Summary', analysis.ai_summary])

    scorecard_sheet = [['Area', 'Own Score', 'Competitor Avg.', 'Gap', 'Status']]
    for row in scorecard_rows:
        scorecard_sheet.append([row['metric'], row['own'], row['competitors'], row['gap'], row['status']])

    comparison_sheet = [['Metric', 'Own Page', 'Competitor Average / Coverage']]
    for row in comparison_rows:
        comparison_sheet.append([row['metric'], row['own'], row['competitors']])

    opportunities_sheet = [['Priority', 'Opportunity', 'Recommendation']]
    for item in analysis.serp_opportunities or []:
        opportunities_sheet.append([
            item.get('priority', ''),
            item.get('opportunity', ''),
            item.get('recommendation', ''),
        ])

    strategies_sheet = [['Competitor', 'Depth', 'Primary Angle', 'SERP Assets', 'Technical']]
    for row in analysis.content_strategies or []:
        strategies_sheet.append([
            row.get('competitor', ''),
            row.get('content_depth', ''),
            row.get('primary_angle', ''),
            row.get('serp_assets', ''),
            row.get('technical_strength', ''),
        ])

    findings_sheet = [['Severity', 'Area', 'Page', 'Finding', 'Recommendation']]
    for item in analysis.technical_findings or []:
        findings_sheet.append([
            item.get('severity', ''),
            item.get('area', ''),
            item.get('page', ''),
            item.get('finding', ''),
            item.get('recommendation', ''),
        ])

    snapshots_sheet = [[
        'Type', 'URL', 'Status Code', 'Title', 'Meta Description', 'Canonical URL',
        'Word Count', 'Images', 'Videos', 'Internal Links', 'External Links',
        'Overall Score', 'Content Score', 'Meta Score', 'Technical Score',
        'Media / Schema Score', 'Links Score', 'PageSpeed Score', 'Performance Score',
        'Error',
    ]]
    for snapshot_type, snapshot in snapshots:
        scores = snapshot.get('scores') or {}
        snapshots_sheet.append([
            snapshot_type,
            snapshot.get('url', ''),
            snapshot.get('status_code', ''),
            snapshot.get('title', ''),
            snapshot.get('meta_description', ''),
            snapshot.get('canonical_url', ''),
            snapshot.get('word_count', ''),
            snapshot.get('image_count', ''),
            snapshot.get('video_count', ''),
            snapshot.get('internal_links_count', ''),
            snapshot.get('external_links_count', ''),
            scores.get('overall', ''),
            scores.get('content', ''),
            scores.get('meta', ''),
            scores.get('technical', ''),
            scores.get('media_schema', ''),
            scores.get('links', ''),
            scores.get('pagespeed', ''),
            snapshot.get('performance_score', ''),
            snapshot.get('error_message', ''),
        ])

    return [
        ('Overview', overview_rows),
        ('AI Recommendations', ai_rows),
        ('Scorecard', scorecard_sheet),
        ('Comparison', comparison_sheet),
        ('SERP Opportunities', opportunities_sheet),
        ('Content Strategies', strategies_sheet),
        ('Technical Findings', findings_sheet),
        ('Page Snapshots', snapshots_sheet),
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


@login_required(login_url='sign-in')
def analysis_view(request):
    analyses = SERPAnalysis.objects.filter(requested_by=request.user)[:8]
    return render(request, 'serp_analysis/analysis.html', {'analyses': analyses})


@login_required(login_url='sign-in')
def history_view(request):
    analyses = SERPAnalysis.objects.filter(requested_by=request.user)
    return render(request, 'serp_analysis/history.html', {'analyses': analyses})


def average_metric(snapshots, key):
    values = [snapshot.get(key) or 0 for snapshot in snapshots]
    if not values:
        return 0
    return round(sum(values) / len(values))


def yes_no_average(snapshots, key):
    if not snapshots:
        return '0%'
    total = sum(1 for snapshot in snapshots if snapshot.get(key))
    return f'{round((total / len(snapshots)) * 100)}%'


def average_score(snapshots, key):
    values = [
        (snapshot.get('scores') or {}).get(key)
        for snapshot in snapshots
    ]
    values = [int(value) for value in values if isinstance(value, (int, float))]
    if not values:
        return 0
    return round(sum(values) / len(values))


def score_status(own_score, competitor_score):
    if own_score >= competitor_score:
        return 'Ahead'
    if own_score >= competitor_score - 5:
        return 'Close'
    return 'Behind'


def build_scorecard_rows(analysis):
    own_scores = (analysis.target_snapshot or {}).get('scores') or {}
    competitors = analysis.competitor_snapshots or []
    rows = []
    for key, label in SCORE_LABELS:
        own_score = int(own_scores.get(key, 0) or 0)
        competitor_score = average_score(competitors, key)
        rows.append({
            'metric': label,
            'own': own_score,
            'competitors': competitor_score,
            'gap': own_score - competitor_score,
            'status': score_status(own_score, competitor_score),
        })
    return rows


def build_scorecard_chart(rows):
    return {
        'categories': [row['metric'] for row in rows],
        'own': [row['own'] for row in rows],
        'competitors': [row['competitors'] for row in rows],
    }


def build_comparison_rows(analysis):
    own = analysis.target_snapshot or {}
    competitors = analysis.competitor_snapshots or []
    return [
        {
            'metric': 'Word Count',
            'own': own.get('word_count', 0),
            'competitors': average_metric(competitors, 'word_count'),
        },
        {
            'metric': 'Images',
            'own': own.get('image_count', 0),
            'competitors': average_metric(competitors, 'image_count'),
        },
        {
            'metric': 'Videos',
            'own': own.get('video_count', 0),
            'competitors': average_metric(competitors, 'video_count'),
        },
        {
            'metric': 'Internal Links',
            'own': own.get('internal_links_count', 0),
            'competitors': average_metric(competitors, 'internal_links_count'),
        },
        {
            'metric': 'External Links',
            'own': own.get('external_links_count', 0),
            'competitors': average_metric(competitors, 'external_links_count'),
        },
        {
            'metric': 'PageSpeed Score',
            'own': own.get('performance_score', 0),
            'competitors': average_metric(competitors, 'performance_score'),
        },
        {
            'metric': 'Canonical Present',
            'own': 'Yes' if own.get('canonical_url') else 'No',
            'competitors': yes_no_average(competitors, 'canonical_url'),
        },
        {
            'metric': 'Meta Description Present',
            'own': 'Yes' if own.get('meta_description') else 'No',
            'competitors': yes_no_average(competitors, 'meta_description'),
        },
        {
            'metric': 'H1 Count',
            'own': len(own.get('h1') or []),
            'competitors': average_metric([{'h1_count': len(snapshot.get('h1') or [])} for snapshot in competitors], 'h1_count'),
        },
    ]


@login_required(login_url='sign-in')
def run_analysis_view(request):
    if request.method != 'POST':
        return redirect('serp_analysis:analysis')

    keyword = request.POST.get('keyword', '').strip()
    location = request.POST.get('location', '').strip()
    target_url_raw = request.POST.get('target_url', '').strip()
    competitor_urls_raw = [
        request.POST.get(f'competitor_url_{index}', '').strip()
        for index in range(1, 6)
        if request.POST.get(f'competitor_url_{index}', '').strip()
    ]

    try:
        if not keyword:
            raise ValidationError('Target keyword is required.')
        target_url = validate_url(target_url_raw, 'Own target URL', required=True)
        if not competitor_urls_raw:
            raise ValidationError('Enter at least one competitor SERP URL.')
        competitor_urls = [
            validate_url(url, f'Competitor URL {index}', required=True)
            for index, url in enumerate(competitor_urls_raw, start=1)
        ]
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
        return redirect('serp_analysis:analysis')

    analysis = SERPAnalysis.objects.create(
        keyword=keyword,
        location=location,
        target_url=target_url,
        competitor_urls=competitor_urls,
        requested_by=request.user,
    )

    queued = enqueue_background_task(
        run_serp_analysis_task,
        analysis,
        'SERP analysis could not be queued',
    )
    if queued:
        messages.success(request, 'SERP analysis started. This page will update when the analysis completes.')
    else:
        messages.error(request, 'SERP analysis could not be queued. Check Redis/Celery and open the result for the error.')
    return redirect('serp_analysis:detail', analysis.id)


@login_required(login_url='sign-in')
def detail_view(request, analysis_id):
    analysis = get_user_analysis(request.user, analysis_id)
    scorecard_rows = build_scorecard_rows(analysis)
    return render(request, 'serp_analysis/detail.html', {
        'analysis': analysis,
        'scorecard_rows': scorecard_rows,
        'scorecard_chart': build_scorecard_chart(scorecard_rows),
        'comparison_rows': build_comparison_rows(analysis),
        'ai_summary_sections': parse_ai_summary_sections(analysis.ai_summary),
        'back_to_history_url': reverse('serp_analysis:history'),
    })


@login_required(login_url='sign-in')
def export_excel_view(request, analysis_id):
    analysis = get_user_analysis(request.user, analysis_id)
    xlsx_bytes = build_xlsx_bytes(build_export_sheets(analysis))
    response = HttpResponse(
        xlsx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{export_filename(analysis, "xlsx")}"'
    return response


@login_required(login_url='sign-in')
def export_pdf_view(request, analysis_id):
    analysis = get_user_analysis(request.user, analysis_id)
    lines = [
        'SERP Analysis',
        f'Keyword: {analysis.keyword}',
        f'Location: {analysis.location}',
        f'Target URL: {analysis.target_url}',
        f'Status: {analysis.status}',
        f'Started: {analysis.started_at.strftime("%Y-%m-%d %H:%M")}',
        f'Completed: {analysis.completed_at.strftime("%Y-%m-%d %H:%M") if analysis.completed_at else ""}',
        f'Competitors: {analysis.competitor_count}',
        f'Opportunities: {len(analysis.serp_opportunities or [])}',
        f'Technical Findings: {len(analysis.technical_findings or [])}',
        '',
    ]
    for sheet_name, rows in build_export_sheets(analysis):
        lines.append(sheet_name)
        lines.append('=' * len(sheet_name))
        for row in rows:
            lines.append(' | '.join(clean_cell(value) for value in row))
        lines.append('')

    pdf_bytes = build_pdf_bytes('SERP Analysis', lines)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{export_filename(analysis, "pdf")}"'
    return response


@login_required(login_url='sign-in')
def delete_view(request, analysis_id):
    analysis = get_user_analysis(request.user, analysis_id)
    if request.method == 'POST':
        analysis.delete()
        messages.success(request, 'SERP analysis deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('serp_analysis:history')
    return redirect('serp_analysis:history')

@login_required(login_url='sign-in')
@require_GET
def serp_status_view(request, analysis_id):
    analysis = get_object_or_404(
        SERPAnalysis.objects.only(
            'id',
            'status',
            'competitor_urls',
            'serp_opportunities',
            'technical_findings',
            'target_snapshot',
            'error_message',
        ),
        id=analysis_id,
        requested_by=request.user,
    )

    target_snapshot = analysis.target_snapshot or {}

    return JsonResponse({
        'status': str(analysis.status).lower().strip(),
        'competitor_count': len(analysis.competitor_urls or []),
        'opportunity_count': len(analysis.serp_opportunities or []),
        'technical_finding_count': len(analysis.technical_findings or []),
        'target_words': target_snapshot.get('word_count') or 0,
        'detail_url': reverse('serp_analysis:detail', args=[analysis.id]),
    })
