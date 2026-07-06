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

from .models import ContentGapAnalysis, ContentGapProject
from .tasks import run_content_gap_analysis_task
from wisoft_co_worker.task_utils import enqueue_background_task


def get_user_analysis(user, analysis_id):
    return get_object_or_404(
        ContentGapAnalysis.objects.select_related('project', 'requested_by'),
        id=analysis_id,
        project__added_by=user,
    )


def clean_cell(value):
    if value is None:
        return ''
    return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', str(value))


def export_filename(analysis, extension):
    subject_slug = slugify(analysis.project.target_topic or analysis.own_url[:80]) or 'content-gap'
    return f'content-gap-{subject_slug}-{analysis.started_at:%Y%m%d}.{extension}'


def build_export_sheets(analysis):
    overview = [
        ['Field', 'Value'],
        ['Own URL', analysis.own_url],
        ['Competitor URLs', ', '.join(analysis.competitor_urls or [])],
        ['Target Topic', analysis.project.target_topic],
        ['Target Market', analysis.project.target_market],
        ['Notes', analysis.project.notes],
        ['Status', analysis.status],
        ['Content Gaps', len(analysis.content_gaps or [])],
        ['Keyword Opportunities', len(analysis.keyword_opportunities or [])],
        ['AI Model', analysis.ai_model],
        ['AI Error', analysis.display_ai_error],
        ['Started At', analysis.started_at.strftime('%Y-%m-%d %H:%M')],
        ['Completed At', analysis.completed_at.strftime('%Y-%m-%d %H:%M') if analysis.completed_at else ''],
    ]
    summary = [['Section', 'Text'], ['AI Summary', analysis.display_ai_summary]]
    gaps = [['Priority', 'Topic', 'Why It Matters', 'Competitors Covering', 'Recommendation']]
    for gap in analysis.content_gaps or []:
        gaps.append([gap.get('priority', ''), gap.get('topic', ''), gap.get('why_it_matters', ''), gap.get('competitors_covering', ''), gap.get('recommendation', '')])
    keywords = [['Keyword', 'Intent', 'Opportunity']]
    for keyword in analysis.keyword_opportunities or []:
        keywords.append([keyword.get('keyword', ''), keyword.get('intent', ''), keyword.get('opportunity', '')])
    sections = [['Section', 'Purpose', 'Priority', 'Notes']]
    for section in analysis.recommended_sections or []:
        sections.append([section.get('section', section.get('title', '')), section.get('purpose', ''), section.get('priority', ''), section.get('notes', section.get('recommendation', ''))])
    plan = [['Step', 'Action', 'Owner', 'Priority']]
    for item in analysis.execution_plan or []:
        plan.append([item.get('step', ''), item.get('action', item.get('task', '')), item.get('owner', ''), item.get('priority', '')])
    wireframe = [['Field', 'Value']]
    if isinstance(analysis.wireframe, dict):
        for key, value in analysis.wireframe.items():
            wireframe.append([key.replace('_', ' ').title(), value])

    snapshots = [['Type', 'URL', 'Status Code', 'Title', 'Meta Description', 'Word Count', 'Images', 'Videos', 'Internal Links', 'External Links', 'Error']]
    all_snapshots = [('Own Page', analysis.own_page_snapshot or {})] + [('Competitor', item) for item in (analysis.competitor_snapshots or [])]
    for snapshot_type, snapshot in all_snapshots:
        snapshots.append([
            snapshot_type,
            snapshot.get('url', ''),
            snapshot.get('status_code', ''),
            snapshot.get('title', ''),
            snapshot.get('meta_description', ''),
            snapshot.get('word_count', ''),
            snapshot.get('image_count', ''),
            snapshot.get('video_count', ''),
            snapshot.get('internal_links_count', ''),
            snapshot.get('external_links_count', ''),
            snapshot.get('error_message', ''),
        ])
    return [
        ('Overview', overview),
        ('AI Summary', summary),
        ('Content Gaps', gaps),
        ('Keyword Opportunities', keywords),
        ('Recommended Sections', sections),
        ('Execution Plan', plan),
        ('Wireframe', wireframe),
        ('Page Snapshots', snapshots),
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
                cells.append(f'<c r="{excel_column_name(column_index)}{row_index}" t="inlineStr"><is><t>{xml_escape(clean_cell(value))}</t></is></c>')
            row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(row_xml) + '</sheetData></worksheet>'

    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', ''.join([
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>',
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            *[f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for index, _sheet in enumerate(sheets, start=1)],
            '</Types>',
        ]))
        archive.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', ''.join([
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>',
            *[f'<sheet name="{xml_escape(name[:31])}" sheetId="{index}" r:id="rId{index}"/>' for index, (name, _rows) in enumerate(sheets, start=1)],
            '</sheets></workbook>',
        ]))
        archive.writestr('xl/_rels/workbook.xml.rels', ''.join([
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
            *[f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>' for index, _sheet in enumerate(sheets, start=1)],
            '</Relationships>',
        ]))
        for index, (_name, rows) in enumerate(sheets, start=1):
            archive.writestr(f'xl/worksheets/sheet{index}.xml', sheet_xml(rows))
    return output.getvalue()


def build_pdf_bytes(title, lines):
    def pdf_string(value):
        text = clean_cell(value).encode('latin-1', 'replace').decode('latin-1')
        return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    records = []
    index = 0
    while index < len(lines):
        line = clean_cell(lines[index])
        next_line = clean_cell(lines[index + 1]) if index + 1 < len(lines) else ''
        if line and next_line and set(next_line) == {'='}:
            records.append(('section', line)); index += 2
        elif not line:
            records.append(('space', '')); index += 1
        else:
            records.append(('row', line)); index += 1
    objects = ['<< /Type /Catalog /Pages 2 0 R >>', '', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>']
    pages, current_ops, y_position, row_number = [], [], 506, 0
    def add_text(ops, x, y, text, size=8, bold=False, color='0.18 0.23 0.31'):
        ops.append(f'BT {color} rg /{"F2" if bold else "F1"} {size} Tf {x} {y} Td ({pdf_string(text)}) Tj ET')
    def start_page():
        nonlocal current_ops, y_position
        current_ops = ['0.02 0.25 0.43 rg 0 535 842 60 re f', '0.00 0.62 0.97 rg 0 535 7 60 re f']
        add_text(current_ops, 34, 566, title, 18, True, '1 1 1')
        add_text(current_ops, 34, 546, 'Wisoft Co-Worker SEO Report', 8, False, '0.82 0.91 1')
        y_position = 506
    def finish_page():
        if current_ops:
            page_number = len(pages) + 1
            current_ops.append('0.86 0.89 0.93 RG 32 31 778 0.5 re f')
            add_text(current_ops, 34, 18, 'Generated from Wisoft Co-Worker', 7, False, '0.42 0.47 0.55')
            add_text(current_ops, 760, 18, f'Page {page_number}', 7, False, '0.42 0.47 0.55')
            pages.append(list(current_ops))
    start_page()
    for record_type, value in records:
        if record_type == 'space':
            y_position -= 8; continue
        if record_type == 'section':
            if y_position < 82:
                finish_page(); start_page()
            current_ops.append(f'0.00 0.62 0.97 rg 32 {y_position - 3} 778 20 re f')
            add_text(current_ops, 42, y_position + 3, value, 10, True, '1 1 1')
            y_position -= 32; row_number = 0; continue
        wrapped = textwrap.wrap(value, width=145) or ['']
        row_height = max(18, 10 * len(wrapped) + 8)
        if y_position - row_height < 42:
            finish_page(); start_page()
        fill = '0.97 0.98 0.99' if row_number % 2 == 0 else '1 1 1'
        current_ops.append(f'{fill} rg 32 {y_position - row_height + 7} 778 {row_height} re f')
        text_y = y_position
        for wrapped_line in wrapped:
            add_text(current_ops, 42, text_y, wrapped_line, 7.5); text_y -= 10
        y_position -= row_height; row_number += 1
    finish_page()
    page_ids, content_ids, next_id = [], [], 5
    for _page in pages:
        page_ids.append(next_id); content_ids.append(next_id + 1); next_id += 2
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(f"{object_id} 0 R" for object_id in page_ids)}] /Count {len(page_ids)} >>'
    for page_ops, _page_id, content_id in zip(pages, page_ids, content_ids):
        content = '\n'.join(page_ops)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>')
        objects.append(f'<< /Length {len(content.encode("utf-8"))} >>\nstream\n{content}\nendstream')
    output = BytesIO(); output.write(b'%PDF-1.4\n'); offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(output.tell()); output.write(f'{index} 0 obj\n{body}\nendobj\n'.encode('utf-8'))
    xref = output.tell(); output.write(f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode('utf-8'))
    for offset in offsets[1:]:
        output.write(f'{offset:010d} 00000 n \n'.encode('utf-8'))
    output.write(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode('utf-8'))
    return output.getvalue()


def get_project_queryset(user):
    projects = list(
        ContentGapProject.objects.filter(added_by=user).prefetch_related('analyses')
    )
    for project in projects:
        analyses = list(project.analyses.all())
        latest_analysis = analyses[0] if analyses else None
        project.latest_analysis = latest_analysis
        project.analysis_count = len(analyses)
        project.latest_gap_count = len(latest_analysis.content_gaps or []) if latest_analysis else 0
        project.latest_keyword_count = len(latest_analysis.keyword_opportunities or []) if latest_analysis else 0
    return projects


def validate_url(url, label):
    if not url:
        raise ValidationError(f'{label} is required.')
    URLValidator()(url)


@login_required(login_url='sign-in')
def analysis_form_view(request):
    context = {
        'projects': get_project_queryset(request.user),
    }
    return render(request, 'content_gap/analysis_form.html', context)


@login_required(login_url='sign-in')
def analysis_history_view(request):
    analyses = ContentGapAnalysis.objects.filter(
        project__added_by=request.user,
    ).select_related('project', 'requested_by')
    context = {
        'analyses': analyses,
        'projects': get_project_queryset(request.user),
    }
    return render(request, 'content_gap/history.html', context)


@login_required(login_url='sign-in')
def analysis_run_view(request):
    if request.method != 'POST':
        return redirect('content_gap:analysis')

    own_url = request.POST.get('own_url', '').strip()
    target_topic = request.POST.get('target_topic', '').strip()
    target_market = request.POST.get('target_market', '').strip()
    notes = request.POST.get('notes', '').strip()
    competitor_urls = [
        request.POST.get(f'competitor_url_{index}', '').strip()
        for index in range(1, 4)
        if request.POST.get(f'competitor_url_{index}', '').strip()
    ]

    try:
        validate_url(own_url, 'Own page URL')
        if not competitor_urls:
            raise ValidationError('Enter at least one competitor URL.')
        for index, competitor_url in enumerate(competitor_urls, start=1):
            validate_url(competitor_url, f'Competitor URL {index}')
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
        return redirect('content_gap:analysis')

    project, _created = ContentGapProject.objects.get_or_create(
        website_url=own_url,
        added_by=request.user,
        defaults={
            'target_topic': target_topic,
            'target_market': target_market,
            'notes': notes,
        },
    )
    changed_fields = []
    for field_name, value in (
        ('target_topic', target_topic),
        ('target_market', target_market),
        ('notes', notes),
    ):
        if value and getattr(project, field_name) != value:
            setattr(project, field_name, value)
            changed_fields.append(field_name)
    if changed_fields:
        changed_fields.append('updated_at')
        project.save(update_fields=changed_fields)

    analysis = ContentGapAnalysis.objects.create(
        project=project,
        requested_by=request.user,
        own_url=own_url,
        competitor_urls=competitor_urls,
    )

    queued = enqueue_background_task(
        run_content_gap_analysis_task,
        analysis,
        'Content gap analysis could not be queued',
    )
    if queued:
        messages.success(request, 'Content gap analysis started. This page will update when the analysis completes.')
    else:
        messages.error(request, 'Content gap analysis could not be queued. Check Redis/Celery and open the result for the error.')
    return redirect('content_gap:analysis-detail', analysis.id)


@login_required(login_url='sign-in')
def analysis_delete_view(request, analysis_id):
    analysis = get_user_analysis(request.user, analysis_id)

    if request.method == 'POST':
        analysis.delete()
        messages.success(request, 'Content gap analysis history deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('content_gap:history')

    return redirect('content_gap:history')


@login_required(login_url='sign-in')
def analysis_detail_view(request, analysis_id):
    analysis = get_user_analysis(request.user, analysis_id)
    context = {
        'analysis': analysis,
        'back_to_history_url': reverse('content_gap:history'),
    }
    return render(request, 'content_gap/analysis_detail.html', context)


@login_required(login_url='sign-in')
def analysis_export_excel_view(request, analysis_id):
    analysis = get_user_analysis(request.user, analysis_id)
    response = HttpResponse(
        build_xlsx_bytes(build_export_sheets(analysis)),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{export_filename(analysis, "xlsx")}"'
    return response


@login_required(login_url='sign-in')
def analysis_export_pdf_view(request, analysis_id):
    analysis = get_user_analysis(request.user, analysis_id)
    lines = [
        'Content Gap Analysis',
        f'Own URL: {analysis.own_url}',
        f'Status: {analysis.status}',
        f'Content Gaps: {len(analysis.content_gaps or [])}',
        f'Keyword Opportunities: {len(analysis.keyword_opportunities or [])}',
        '',
    ]
    for sheet_name, rows in build_export_sheets(analysis):
        lines.append(sheet_name)
        lines.append('=' * len(sheet_name))
        for row in rows:
            lines.append(' | '.join(clean_cell(value) for value in row))
        lines.append('')
    response = HttpResponse(build_pdf_bytes('Content Gap Analysis', lines), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{export_filename(analysis, "pdf")}"'
    return response


@login_required(login_url='sign-in')
@require_GET
def analysis_status_view(request, analysis_id):
    analysis = get_object_or_404(
        ContentGapAnalysis.objects.only(
            'id',
            'status',
            'competitor_urls',
            'content_gaps',
            'keyword_opportunities',
            'error_message',
        ),
        id=analysis_id,
        project__added_by=request.user,
    )

    return JsonResponse({
        'status': str(analysis.status).lower().strip(),
        'competitor_count': len(analysis.competitor_urls or []),
        'content_gap_count': len(analysis.content_gaps or []),
        'keyword_count': len(analysis.keyword_opportunities or []),
        'detail_url': reverse('content_gap:analysis-detail', args=[analysis.id]),
    })
