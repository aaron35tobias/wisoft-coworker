import json
import os
import re
from decimal import Decimal
from urllib.request import Request, urlopen

from .models import (
    WebsitePage,
    WebsiteSpeedReport,
    WebsiteSpeedReportAiEvaluation,
    WebsiteSpeedReportAiIndex,
)

ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages'
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MAX_TOKENS = 1600

def get_timeout_seconds():
    try:
        return int(os.environ.get('CONTENT_GAP_ANTHROPIC_TIMEOUT_SECONDS', DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS

def get_max_tokens():
    try:
        return int(os.environ.get('CONTENT_GAP_ANTHROPIC_MAX_TOKENS', DEFAULT_MAX_TOKENS))
    except (TypeError, ValueError):
        return DEFAULT_MAX_TOKENS

def clean_value(value):
    if isinstance(value, Decimal):
        return float(value)
    return value

def report_to_payload(report):
    if not report:
        return None

    return {
        'device': report.device_type,
        'performance_score': report.performance_score,
        'accessibility_score': report.accessibility_score,
        'best_practices_score': report.best_practices_score,
        'seo_score': report.seo_score,
        'first_contentful_paint_seconds': clean_value(report.first_contentful_paint),
        'largest_contentful_paint_seconds': clean_value(report.largest_contentful_paint),
        'interaction_to_next_paint_ms': clean_value(report.interaction_to_next_paint),
        'cumulative_layout_shift': clean_value(report.cumulative_layout_shift),
        'total_blocking_time_ms': clean_value(report.total_blocking_time),
        'speed_index_seconds': clean_value(report.speed_index),
        'time_to_first_byte_seconds': clean_value(report.time_to_first_byte),
        'warnings': extract_warning_audits(report.raw_response_json),
    }

def extract_warning_audits(raw_response_json):
    audits = raw_response_json.get('lighthouseResult', {}).get('audits', {})
    warning_audits = []

    for audit_key, audit in audits.items():
        score = audit.get('score')
        score_display_mode = audit.get('scoreDisplayMode')
        if score_display_mode not in ['numeric', 'binary', 'metricSavings'] or score is None or score >= 0.9:
            continue

        warning_audits.append({
            'key': audit_key,
            'title': audit.get('title', ''),
            'display_value': audit.get('displayValue', ''),
            'score': score,
        })

        if len(warning_audits) >= 12:
            break

    return warning_audits

def get_device_reports(report_index):
    reports = list(report_index.reports.all())
    mobile_report = next((report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_MOBILE), None)
    desktop_report = next((report for report in reports if report.device_type == WebsiteSpeedReport.DEVICE_DESKTOP), None)
    return mobile_report, desktop_report

def build_evaluation_payload(page, latest_report_index, previous_report_index):
    latest_mobile_report, latest_desktop_report = get_device_reports(latest_report_index)
    previous_mobile_report, previous_desktop_report = get_device_reports(previous_report_index) if previous_report_index else (None, None)

    return {
        'page_url': page.page_url,
        'latest_scan': {
            'scan_id': latest_report_index.scan_group_token,
            'scanned_at': latest_report_index.scanned_at.isoformat(),
            'mobile': report_to_payload(latest_mobile_report),
            'desktop': report_to_payload(latest_desktop_report),
        },
        'previous_scan': {
            'scan_id': previous_report_index.scan_group_token,
            'scanned_at': previous_report_index.scanned_at.isoformat(),
            'mobile': report_to_payload(previous_mobile_report),
            'desktop': report_to_payload(previous_desktop_report),
        } if previous_report_index else None,
    }

def build_prompt(payload):
    return (
        'Evaluate this Google PageSpeed latest scan against the previous scan. '
        'Return only raw valid JSON. Do not use markdown. Do not wrap it in ```json. '
        'Use these keys: summary, improvements, declines, warnings, recommendations. '
        'Each list item should be a short practical sentence. '
        'Focus on what changed, current warnings, and next actions.\n\n'
        f'{json.dumps(payload, ensure_ascii=False)}'
    )

def parse_ai_json(text):
    cleaned_text = text.strip()
    fenced_match = re.search(r'```(?:json)?\\s*(.*?)\\s*```', cleaned_text, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        cleaned_text = fenced_match.group(1).strip()

    if not cleaned_text.startswith('{'):
        start_index = cleaned_text.find('{')
        end_index = cleaned_text.rfind('}')
        if start_index != -1 and end_index != -1 and end_index > start_index:
            cleaned_text = cleaned_text[start_index:end_index + 1]

    return json.loads(cleaned_text)

def call_anthropic(prompt):
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        return None, '', 'ANTHROPIC_API_KEY is not configured.', ''

    model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022').strip()
    body = {
        'model': model,
        'max_tokens': get_max_tokens(),
        'messages': [
            {'role': 'user', 'content': prompt},
        ],
    }
    request = Request(
        ANTHROPIC_API_URL,
        data=json.dumps(body).encode('utf-8'),
        headers={
            'content-type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        },
        method='POST',
    )

    try:
        with urlopen(request, timeout=get_timeout_seconds()) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as error:
        return None, model, f'Claude request failed: {error}', ''

    text = ''.join(block.get('text', '') for block in data.get('content', []) if block.get('type') == 'text').strip()
    if not text:
        return None, model, 'Claude returned an empty response.', ''

    try:
        return parse_ai_json(text), model, '', text
    except json.JSONDecodeError as error:
        return None, model, f'Could not parse Claude JSON: {error}', text

def evaluate_page_latest_vs_previous(page):
    report_indexes = list(WebsiteSpeedReportAiIndex.objects.filter(page=page).prefetch_related('reports')[:2])
    if not report_indexes:
        return None, 'No PageSpeed scans found.'

    latest_report_index = report_indexes[0]
    previous_report_index = report_indexes[1] if len(report_indexes) > 1 else None
    existing_evaluation = WebsiteSpeedReportAiEvaluation.objects.filter(page=page, latest_report_index=latest_report_index).first()
    if existing_evaluation and not existing_evaluation.ai_error:
        return existing_evaluation, 'AI evaluation already exists.'

    payload = build_evaluation_payload(page, latest_report_index, previous_report_index)
    ai_result, model, error, raw_ai_text = call_anthropic(build_prompt(payload))

    if error:
        evaluation = existing_evaluation or WebsiteSpeedReportAiEvaluation(website=page.website,page=page,latest_report_index=latest_report_index,previous_report_index=previous_report_index)
        evaluation.ai_model = model
        evaluation.ai_error = error
        evaluation.raw_ai_response_json = {'payload': payload, 'raw_ai_text': raw_ai_text}
        evaluation.save()
        return evaluation, error

    evaluation = existing_evaluation or WebsiteSpeedReportAiEvaluation(website=page.website,page=page,latest_report_index=latest_report_index,previous_report_index=previous_report_index)
    evaluation.ai_model = model
    evaluation.summary = ai_result.get('summary', '')
    evaluation.improvements_json = ai_result.get('improvements', [])
    evaluation.declines_json = ai_result.get('declines', [])
    evaluation.warnings_json = ai_result.get('warnings', [])
    evaluation.recommendations_json = ai_result.get('recommendations', [])
    evaluation.raw_ai_response_json = ai_result
    evaluation.ai_error = ''
    evaluation.save()
    return evaluation, 'AI evaluation completed.'

def evaluate_website_latest_vs_previous(website_id=None, page_id=None):
    pages = WebsitePage.objects.filter(is_active=True, website__is_active=True).select_related('website')
    if website_id:
        pages = pages.filter(website_id=website_id)
    if page_id:
        pages = pages.filter(id=page_id)

    results = []
    for page in pages.order_by('website_id', 'id'):
        evaluation, message = evaluate_page_latest_vs_previous(page)
        results.append((page, evaluation, message))
    return results
