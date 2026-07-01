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
from django.views.decorators.http import require_GET, require_POST

from .models import KeywordCartItem, KeywordResearchProject, KeywordResearchRun
from .tasks import run_keyword_research_task
from wisoft_co_worker.task_utils import enqueue_background_task


def get_user_run(user, run_id):
    return get_object_or_404(
        KeywordResearchRun.objects.select_related('project', 'requested_by'),
        id=run_id,
        project__added_by=user,
    )


def clean_cell(value):
    if value is None:
        return ''
    return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', str(value))


def export_filename(run, extension):
    subject = run.project.website_url or run.project.seed_topic or run.project.seed_keywords or 'keywords'
    subject_slug = slugify(subject[:80]) or 'keywords'
    return f'keyword-research-{subject_slug}-{run.started_at:%Y%m%d}.{extension}'


def build_export_sheets(run):
    overview = [
        ['Field', 'Value'],
        ['Website URL', run.project.website_url],
        ['Seed Keywords', run.project.seed_keywords],
        ['Target Location', run.project.target_location],
        ['Language', run.project.language],
        ['Seed Topic', run.project.seed_topic],
        ['Notes', run.project.notes],
        ['Status', run.status],
        ['Pages Crawled', run.pages_crawled],
        ['AI Model', run.ai_model],
        ['AI Error', run.ai_error],
        ['Planner Status', run.planner_status],
        ['Planner Error', run.planner_error],
        ['Started At', run.started_at.strftime('%Y-%m-%d %H:%M')],
        ['Completed At', run.completed_at.strftime('%Y-%m-%d %H:%M') if run.completed_at else ''],
    ]
    summary = [['Section', 'Text'], ['AI Summary', run.ai_summary or 'No summary available.']]

    ideas = [['Keyword', 'Intent', 'Funnel Stage', 'Priority', 'Suggested Page', 'Content Angle', 'Reason', 'Source']]
    for idea in run.keyword_ideas.all():
        ideas.append([idea.keyword, idea.intent, idea.funnel_stage, idea.priority, idea.suggested_page, idea.content_angle, idea.reason, idea.source])

    clusters = [['Cluster', 'Intent', 'Keywords', 'Recommended Page Type', 'Recommended Action']]
    for cluster in run.clusters.all():
        clusters.append([cluster.cluster_name, cluster.intent, ', '.join(cluster.keywords or []), cluster.recommended_page_type, cluster.recommended_action])

    planner = [['Keyword', 'Avg Monthly Searches', 'Competition', 'Competition Index', 'Low Bid', 'High Bid', 'Currency', 'Source']]
    for metric in run.planner_metrics.all():
        planner.append([
            metric.keyword,
            metric.avg_monthly_searches,
            metric.competition,
            metric.competition_index,
            metric.low_top_of_page_bid,
            metric.high_top_of_page_bid,
            metric.currency_code,
            metric.source,
        ])

    pages = [['URL', 'Title', 'Meta Description', 'H1', 'H2', 'H3', 'Word Count', 'Top Terms', 'Content Excerpt', 'Error']]
    for page in run.pages.all():
        top_terms = ', '.join(f'{item.get("term", "")}: {item.get("count", "")}' for item in (page.top_terms or []) if isinstance(item, dict))
        pages.append([
            page.url,
            page.title,
            page.meta_description,
            ', '.join(page.h1 or []),
            ', '.join(page.h2 or []),
            ', '.join(page.h3 or []),
            page.word_count,
            top_terms,
            page.content_excerpt,
            page.error_message,
        ])

    cart = [['Keyword', 'Source']]
    for item in run.cart_items.all():
        cart.append([item.keyword, item.source])

    return [
        ('Overview', overview),
        ('AI Summary', summary),
        ('Keyword Ideas', ideas),
        ('Keyword Clusters', clusters),
        ('Planner Metrics', planner),
        ('Crawled Pages', pages),
        ('Keyword Cart', cart),
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
                text = xml_escape(clean_cell(value))
                cells.append(f'<c r="{excel_column_name(column_index)}{row_index}" t="inlineStr"><is><t>{text}</t></is></c>')
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
            records.append(('section', line))
            index += 2
        elif not line:
            records.append(('space', ''))
            index += 1
        else:
            records.append(('row', line))
            index += 1

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
            y_position -= 8
            continue
        if record_type == 'section':
            if y_position < 82:
                finish_page()
                start_page()
            current_ops.append(f'0.00 0.62 0.97 rg 32 {y_position - 3} 778 20 re f')
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
        text_y = y_position
        for wrapped_line in wrapped:
            add_text(current_ops, 42, text_y, wrapped_line, 7.5)
            text_y -= 10
        y_position -= row_height
        row_number += 1
    finish_page()

    page_ids, content_ids, next_id = [], [], 5
    for _page in pages:
        page_ids.append(next_id)
        content_ids.append(next_id + 1)
        next_id += 2
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(f"{object_id} 0 R" for object_id in page_ids)}] /Count {len(page_ids)} >>'
    for page_ops, _page_id, content_id in zip(pages, page_ids, content_ids):
        content = '\n'.join(page_ops)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>')
        objects.append(f'<< /Length {len(content.encode("utf-8"))} >>\nstream\n{content}\nendstream')
    output = BytesIO()
    output.write(b'%PDF-1.4\n')
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f'{index} 0 obj\n{body}\nendobj\n'.encode('utf-8'))
    xref = output.tell()
    output.write(f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode('utf-8'))
    for offset in offsets[1:]:
        output.write(f'{offset:010d} 00000 n \n'.encode('utf-8'))
    output.write(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode('utf-8'))
    return output.getvalue()


def project_queryset(user):
    projects = list(KeywordResearchProject.objects.filter(added_by=user).prefetch_related('runs'))
    for project in projects:
        runs = list(project.runs.all())
        latest_run = runs[0] if runs else None
        project.latest_run = latest_run
        project.run_count = len(runs)
        project.latest_keywords_count = latest_run.keyword_ideas.count() if latest_run else 0
        project.latest_planner_count = latest_run.planner_metrics.count() if latest_run else 0
    return projects


@login_required(login_url='sign-in')
def research_view(request):
    return render(request, 'keyword_research/research.html', {'projects': project_queryset(request.user)})


@login_required(login_url='sign-in')
def history_view(request):
    runs = KeywordResearchRun.objects.filter(project__added_by=request.user).select_related('project', 'requested_by')
    return render(request, 'keyword_research/history.html', {'runs': runs})


def decorate_planner_metric(metric):
    searches = metric.avg_monthly_searches or 0
    if searches >= 1000:
        metric.search_badge_class = 'success'
    elif searches >= 100:
        metric.search_badge_class = 'warning'
    elif searches:
        metric.search_badge_class = 'primary'
    else:
        metric.search_badge_class = 'secondary'

    competition = (metric.competition or '').upper()
    if competition == 'HIGH':
        metric.competition_badge_class = 'danger'
    elif competition == 'MEDIUM':
        metric.competition_badge_class = 'warning'
    elif competition == 'LOW':
        metric.competition_badge_class = 'success'
    else:
        metric.competition_badge_class = 'secondary'

    index = metric.competition_index
    if index is None:
        metric.index_badge_class = 'secondary'
    elif index >= 67:
        metric.index_badge_class = 'danger'
    elif index >= 34:
        metric.index_badge_class = 'warning'
    else:
        metric.index_badge_class = 'success'

    bid = metric.high_top_of_page_bid or metric.low_top_of_page_bid
    if bid is None:
        metric.bid_badge_class = 'secondary'
    elif bid >= 20:
        metric.bid_badge_class = 'danger'
    elif bid >= 5:
        metric.bid_badge_class = 'warning'
    else:
        metric.bid_badge_class = 'info'
    return metric


@login_required(login_url='sign-in')
def run_research_view(request):
    if request.method != 'POST':
        return redirect('keyword_research:research')

    website_url = request.POST.get('website_url', '').strip()
    seed_keywords = request.POST.get('seed_keywords', '').strip()
    target_location = request.POST.get('target_location', '').strip()
    language = request.POST.get('language', '').strip()
    seed_topic = request.POST.get('seed_topic', '').strip()
    notes = request.POST.get('notes', '').strip()

    try:
        if not website_url and not seed_keywords:
            raise ValidationError('Enter either a Page URL or keywords.')
        if not target_location:
            raise ValidationError('Target location is required.')
        if website_url:
            URLValidator()(website_url)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
        return redirect('keyword_research:research')

    project = KeywordResearchProject.objects.create(
        website_url=website_url,
        seed_keywords=seed_keywords,
        target_location=target_location,
        language=language,
        seed_topic=seed_topic,
        notes=notes,
        added_by=request.user,
    )
    run = KeywordResearchRun.objects.create(
        project=project,
        requested_by=request.user,
        max_pages=1,
    )

    queued = enqueue_background_task(
        run_keyword_research_task,
        run,
        'Keyword research could not be queued',
    )
    if queued:
        messages.success(request, 'Keyword research started. This page will update when the research completes.')
    else:
        messages.error(request, 'Keyword research could not be queued. Check Redis/Celery and open the detail page for the error.')
    return redirect('keyword_research:detail', run.id)


@login_required(login_url='sign-in')
def detail_view(request, run_id):
    run = get_user_run(request.user, run_id)
    planner_metrics = [decorate_planner_metric(metric) for metric in run.planner_metrics.all()]
    cart_items = list(run.cart_items.filter(user=request.user))
    return render(request, 'keyword_research/detail.html', {
        'run': run,
        'keyword_ideas': run.keyword_ideas.all(),
        'clusters': run.clusters.all(),
        'planner_metrics': planner_metrics,
        'pages': run.pages.all(),
        'cart_items': cart_items,
        'cart_keyword_values': [item.keyword.lower() for item in cart_items],
    })


@login_required(login_url='sign-in')
def export_excel_view(request, run_id):
    run = get_user_run(request.user, run_id)
    response = HttpResponse(
        build_xlsx_bytes(build_export_sheets(run)),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{export_filename(run, "xlsx")}"'
    return response


@login_required(login_url='sign-in')
def export_pdf_view(request, run_id):
    run = get_user_run(request.user, run_id)
    lines = [
        'Keyword Research',
        f'Status: {run.status}',
        f'Website URL: {run.project.website_url}',
        f'Seed Keywords: {run.project.seed_keywords}',
        f'Target Location: {run.project.target_location}',
        f'Ideas: {run.keyword_ideas.count()}',
        f'Planner Rows: {run.planner_metrics.count()}',
        '',
    ]
    for sheet_name, rows in build_export_sheets(run):
        lines.append(sheet_name)
        lines.append('=' * len(sheet_name))
        for row in rows:
            lines.append(' | '.join(clean_cell(value) for value in row))
        lines.append('')
    response = HttpResponse(build_pdf_bytes('Keyword Research', lines), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{export_filename(run, "pdf")}"'
    return response


@login_required(login_url='sign-in')
@require_POST
def add_cart_keyword_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun,
        id=run_id,
        project__added_by=request.user,
    )
    keyword = request.POST.get('keyword', '').strip()
    source = request.POST.get('source', '').strip()
    if not keyword:
        return JsonResponse({'success': False, 'error': 'Keyword is required.'}, status=400)

    item = KeywordCartItem.objects.filter(
        run=run,
        user=request.user,
        keyword__iexact=keyword,
    ).first()
    if item is None:
        item = KeywordCartItem.objects.create(
            run=run,
            user=request.user,
            keyword=keyword[:255],
            source=source[:20],
        )
    elif source and not item.source:
        item.source = source[:20]
        item.save(update_fields=['source'])

    return JsonResponse({
        'success': True,
        'keyword': item.keyword,
        'source': item.source,
        'cart_count': run.cart_items.filter(user=request.user).count(),
    })


@login_required(login_url='sign-in')
@require_POST
def remove_cart_keyword_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun,
        id=run_id,
        project__added_by=request.user,
    )
    keyword = request.POST.get('keyword', '').strip()
    if not keyword:
        return JsonResponse({'success': False, 'error': 'Keyword is required.'}, status=400)

    KeywordCartItem.objects.filter(
        run=run,
        user=request.user,
        keyword__iexact=keyword,
    ).delete()

    return JsonResponse({
        'success': True,
        'keyword': keyword,
        'cart_count': run.cart_items.filter(user=request.user).count(),
    })


@login_required(login_url='sign-in')
def delete_run_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun.objects.select_related('project'),
        id=run_id,
        project__added_by=request.user,
    )
    if request.method == 'POST':
        run.delete()
        messages.success(request, 'Keyword research run deleted successfully.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('keyword_research:history')
    return redirect('keyword_research:history')

@login_required(login_url='sign-in')
@require_GET
def keyword_run_status_view(request, run_id):
    run = get_object_or_404(
        KeywordResearchRun.objects.only(
            'id',
            'status',
            'pages_crawled',
            'planner_status',
            'error_message',
        ),
        id=run_id,
        project__added_by=request.user,
    )

    return JsonResponse({
        'status': str(run.status).lower().strip(),
        'pages_crawled': run.pages_crawled or 0,
        'planner_status': run.planner_status or '',
        'keyword_ideas_count': run.keyword_ideas.count(),
        'clusters_count': run.clusters.count(),
        'planner_metrics_count': run.planner_metrics.count(),
        'detail_url': reverse('keyword_research:detail', args=[run.id]),
    })
