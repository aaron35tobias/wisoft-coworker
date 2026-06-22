import email.utils
import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import timezone as datetime_timezone
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

from django.utils import timezone

from .models import PricingPRChange, PricingPRNewsMention, PricingPRRun, PricingPRSnapshot


USER_AGENT = 'WisoftCoWorkerPricingPRMonitor/1.0'
DEFAULT_HTML_READ_LIMIT_BYTES = 2 * 1024 * 1024
DEFAULT_AI_TIMEOUT_SECONDS = 90
DEFAULT_AI_MAX_TOKENS = 900
PR_NEWS_VALIDATION_TOOL_NAME = 'validate_pr_news_mentions'
PRICE_PATTERN = re.compile(r'(\$|AED|USD|EUR|GBP|SAR|INR)\s?[0-9][0-9,]*(?:\.[0-9]{1,2})?|[0-9][0-9,]*(?:\.[0-9]{1,2})?\s?(?:AED|USD|EUR|GBP|SAR|INR)', re.IGNORECASE)
CTA_WORDS = ('free', 'trial', 'demo', 'quote', 'contact', 'consultation', 'audit', 'book', 'schedule', 'pricing', 'package', 'offer')
PRESS_RELEASE_QUERY_TERMS = (
    'press release',
    'announces',
    'launches',
    'partnership',
    'expands',
    'award',
    'funding',
)
GENERIC_NEWS_TERMS = {
    'seo',
    'marketing',
    'digital marketing',
    'pricing',
    'press release',
    'dubai',
    'uae',
    'agency',
    'company',
    'service',
    'services',
}


def get_html_read_limit_bytes():
    try:
        return int(os.environ.get('PRICING_PR_HTML_READ_LIMIT_BYTES', DEFAULT_HTML_READ_LIMIT_BYTES))
    except (TypeError, ValueError):
        return DEFAULT_HTML_READ_LIMIT_BYTES


def get_ai_timeout_seconds():
    try:
        return int(os.environ.get('PRICING_PR_ANTHROPIC_TIMEOUT_SECONDS', DEFAULT_AI_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_AI_TIMEOUT_SECONDS


def get_ai_max_tokens():
    try:
        return int(os.environ.get('PRICING_PR_ANTHROPIC_MAX_TOKENS', DEFAULT_AI_MAX_TOKENS))
    except (TypeError, ValueError):
        return DEFAULT_AI_MAX_TOKENS


class PageTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.meta_description = ''
        self.headings = []
        self.text_parts = []
        self._active_tag = None
        self._buffer = []
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = {name.lower(): (value or '') for name, value in attrs}
        if tag in {'script', 'style', 'noscript', 'svg'}:
            self._ignored_depth += 1
            return
        if tag in {'title', 'h1', 'h2', 'h3', 'a', 'button'}:
            self._active_tag = tag
            self._buffer = []
        if tag == 'meta':
            name = attrs_dict.get('name', '').lower()
            content = attrs_dict.get('content', '').strip()
            if name == 'description' and content and not self.meta_description:
                self.meta_description = content

    def handle_data(self, data):
        if self._ignored_depth:
            return
        if self._active_tag:
            self._buffer.append(data)
        cleaned = normalize_text(data)
        if cleaned:
            self.text_parts.append(cleaned)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {'script', 'style', 'noscript', 'svg'} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if tag != self._active_tag:
            return
        text = normalize_text(' '.join(self._buffer))
        if tag == 'title' and not self.title:
            self.title = text
        elif tag in {'h1', 'h2', 'h3'} and text:
            self.headings.append(text)
        self._active_tag = None
        self._buffer = []


def normalize_text(value):
    return ' '.join(unescape(value or '').split())


def strip_html(value):
    return normalize_text(re.sub(r'<[^>]+>', ' ', value or ''))


def normalize_match_text(value):
    return re.sub(r'[^a-z0-9]+', ' ', (value or '').lower()).strip()


def domain_terms(url):
    parsed = urlparse(url or '')
    host = parsed.netloc.lower().replace('www.', '')
    root = host.split(':')[0]
    stem = root.split('.')[0] if root else ''
    terms = []
    if root:
        terms.append(root)
    if stem and len(stem) >= 3:
        terms.append(stem)
    return terms


def brand_terms_for_monitor(monitor):
    terms = []
    competitor_name = normalize_text(monitor.competitor_name)
    if competitor_name:
        terms.append(competitor_name)
    terms.extend(domain_terms(monitor.competitor_website))
    if monitor.pricing_url:
        terms.extend(domain_terms(monitor.pricing_url))

    unique_terms = []
    for term in terms:
        normalized = normalize_match_text(term)
        if len(normalized) >= 3 and normalized not in GENERIC_NEWS_TERMS and normalized not in unique_terms:
            unique_terms.append(normalized)
    return unique_terms


def keyword_is_brand_like(keyword, brand_terms):
    normalized = normalize_match_text(keyword)
    return any(normalized == term or normalized in term or term in normalized for term in brand_terms)


def news_search_query(monitor, keyword):
    brand_name = normalize_text(monitor.competitor_name)
    keyword = normalize_text(keyword)
    if keyword and keyword.lower() != brand_name.lower():
        return f'"{brand_name}" {keyword}'
    return f'"{brand_name}"'


def news_search_queries(monitor, keywords):
    brand_name = normalize_text(monitor.competitor_name)
    queries = [f'"{brand_name}" "{term}"' for term in PRESS_RELEASE_QUERY_TERMS]
    for keyword in keywords:
        keyword = normalize_text(keyword)
        if keyword and keyword.lower() != brand_name.lower():
            queries.append(f'"{brand_name}" {keyword}')
    unique_queries = []
    for query in queries:
        if query not in unique_queries:
            unique_queries.append(query)
    return unique_queries


def mention_is_relevant(mention, brand_terms):
    haystack = normalize_match_text(' '.join([
        mention.get('title', ''),
        mention.get('source', ''),
        mention.get('snippet', ''),
    ]))
    padded = f' {haystack} '
    for term in brand_terms:
        if f' {term} ' in padded or term.replace(' ', '') in haystack.replace(' ', ''):
            return True
    return False


def mention_record_is_relevant(mention, monitor):
    return mention_is_relevant(
        {
            'title': mention.title,
            'source': mention.source,
            'snippet': mention.snippet,
        },
        brand_terms_for_monitor(monitor),
    )


def clean_text_hash(text):
    normalized = re.sub(r'\s+', ' ', (text or '').lower()).strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def fetch_page(url):
    started = time.monotonic()
    request = Request(url, headers={'User-Agent': USER_AGENT})
    read_limit = get_html_read_limit_bytes()
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read(read_limit + 1)
            truncated = len(body) > read_limit
            if truncated:
                body = body[:read_limit]
            return {
                'url': url,
                'status_code': response.getcode(),
                'final_url': response.geturl(),
                'content_type': response.headers.get('Content-Type', ''),
                'body': body,
                'load_time_ms': int((time.monotonic() - started) * 1000),
                'truncated': truncated,
                'error_message': '',
            }
    except HTTPError as exc:
        return {
            'url': url,
            'status_code': exc.code,
            'final_url': exc.url or url,
            'content_type': exc.headers.get('Content-Type', '') if exc.headers else '',
            'body': b'',
            'load_time_ms': int((time.monotonic() - started) * 1000),
            'truncated': False,
            'error_message': str(exc),
        }
    except (URLError, TimeoutError, ValueError) as exc:
        return {
            'url': url,
            'status_code': None,
            'final_url': url,
            'content_type': '',
            'body': b'',
            'load_time_ms': int((time.monotonic() - started) * 1000),
            'truncated': False,
            'error_message': str(exc),
        }


def extract_cta_terms(text):
    lines = []
    for line in re.split(r'[.!?\n]', text or ''):
        cleaned = normalize_text(line)
        if cleaned and any(word in cleaned.lower() for word in CTA_WORDS):
            lines.append(cleaned[:180])
        if len(lines) >= 12:
            break
    return lines


def build_snapshot_data(url):
    fetched = fetch_page(url)
    parser = PageTextParser()
    text = ''
    if not fetched['error_message'] and fetched['body']:
        parser.feed(fetched['body'].decode('utf-8', errors='replace'))
        text = normalize_text(' '.join(parser.text_parts))

    pricing_terms = sorted(set(match.group(0).strip() for match in PRICE_PATTERN.finditer(text)))[:20]
    cta_terms = extract_cta_terms(text)
    return {
        'url': url,
        'status_code': fetched['status_code'],
        'final_url': fetched['final_url'],
        'title': parser.title[:500],
        'meta_description': parser.meta_description[:1000],
        'headings': parser.headings[:30],
        'pricing_terms': pricing_terms,
        'cta_terms': cta_terms,
        'text_excerpt': text[:3000],
        'content_hash': clean_text_hash(text),
        'error_message': fetched['error_message'],
        'raw_data': {
            'content_type': fetched['content_type'],
            'load_time_ms': fetched['load_time_ms'],
            'truncated': fetched['truncated'],
        },
    }


def monitored_urls(monitor):
    urls = [monitor.competitor_website]
    if monitor.pricing_url:
        urls.append(monitor.pricing_url)
    urls.extend(monitor.monitored_urls or [])
    cleaned = []
    for url in urls:
        if url and url not in cleaned:
            cleaned.append(url)
    return cleaned


def previous_snapshot_for(monitor, url):
    return (
        PricingPRSnapshot.objects
        .filter(monitor=monitor, url=url)
        .exclude(run__status=PricingPRRun.STATUS_RUNNING)
        .order_by('-checked_at')
        .first()
    )


def create_change_if_needed(run, current_snapshot):
    previous = previous_snapshot_for(run.monitor, current_snapshot.url)
    if not previous:
        return None
    if previous.content_hash == current_snapshot.content_hash:
        return None

    severity = PricingPRChange.SEVERITY_MEDIUM
    change_type = 'page_content_changed'
    evidence_bits = []
    if previous.pricing_terms != current_snapshot.pricing_terms:
        severity = PricingPRChange.SEVERITY_HIGH
        change_type = 'pricing_changed'
        evidence_bits.append(f'Pricing terms changed from {previous.pricing_terms or "none"} to {current_snapshot.pricing_terms or "none"}.')
    if previous.cta_terms != current_snapshot.cta_terms:
        evidence_bits.append('CTA or offer-related text changed.')
    if previous.title != current_snapshot.title:
        evidence_bits.append(f'Title changed from "{previous.title}" to "{current_snapshot.title}".')
    if not evidence_bits:
        evidence_bits.append('Page text changed compared with the previous saved snapshot.')

    return PricingPRChange.objects.create(
        run=run,
        monitor=run.monitor,
        previous_snapshot=previous,
        current_snapshot=current_snapshot,
        change_type=change_type,
        severity=severity,
        title='Pricing page changed' if change_type == 'pricing_changed' else 'Competitor page changed',
        evidence=' '.join(evidence_bits),
        recommendation='Review the changed page and update competitor messaging, pricing comparisons, or response strategy if needed.',
    )


def parse_google_news_date(value):
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed and timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone=datetime_timezone.utc)
        return parsed
    except Exception:
        return None


def fetch_google_news_mentions(query, keyword, limit=5):
    encoded_query = quote_plus(query)
    url = f'https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en'
    request = Request(url, headers={'User-Agent': USER_AGENT})
    mentions = []
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read(512 * 1024)
        root = ET.fromstring(body)
    except Exception:
        return mentions

    for item in root.findall('./channel/item')[:limit]:
        title = normalize_text(item.findtext('title', ''))
        link = normalize_text(item.findtext('link', ''))
        source = normalize_text(item.findtext('source', ''))
        published_at = parse_google_news_date(item.findtext('pubDate', ''))
        snippet = strip_html(item.findtext('description', ''))
        if not title or not link:
            continue
        mentions.append({
            'keyword': keyword,
            'title': title[:500],
            'url': link,
            'source': source[:255],
            'published_at': published_at,
            'snippet': snippet[:1000],
        })
    return mentions


def build_news_validation_tool():
    return {
        'name': PR_NEWS_VALIDATION_TOOL_NAME,
        'description': 'Validate whether Google News candidates are truly competitor press releases or announcement-style news.',
        'input_schema': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'mentions': {
                    'type': 'array',
                    'maxItems': 20,
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'candidate_index': {'type': 'integer'},
                            'is_relevant': {'type': 'boolean'},
                            'mention_type': {
                                'type': 'string',
                                'enum': [
                                    'press_release',
                                    'pricing_update',
                                    'product_launch',
                                    'partnership',
                                    'expansion',
                                    'award',
                                    'campaign',
                                    'competitor_news',
                                    'other',
                                ],
                            },
                            'relevance_reason': {'type': 'string', 'maxLength': 500},
                            'competitive_impact': {'type': 'string', 'maxLength': 700},
                        },
                        'required': [
                            'candidate_index',
                            'is_relevant',
                            'mention_type',
                            'relevance_reason',
                            'competitive_impact',
                        ],
                    },
                },
            },
            'required': ['mentions'],
        },
    }


def validate_news_candidates_with_ai(monitor, candidates):
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022').strip()
    brand_terms = brand_terms_for_monitor(monitor)

    strict_fallback = []
    for index, candidate in enumerate(candidates):
        if mention_is_relevant(candidate, brand_terms):
            strict_fallback.append({
                **candidate,
                'mention_type': 'competitor_news',
                'relevance_reason': 'The candidate explicitly mentions the monitored competitor identity.',
                'competitive_impact': 'Review this mention for possible positioning, PR, or competitive response opportunities.',
                'candidate_index': index,
            })

    if not api_key or not candidates:
        return strict_fallback

    payload = {
        'competitor_name': monitor.competitor_name,
        'competitor_website': monitor.competitor_website,
        'brand_terms_that_must_be_present': brand_terms,
        'instruction': (
            'Approve a candidate only when it is clearly about the monitored competitor and looks like a press release, '
            'announcement, launch, partnership, expansion, award, funding, campaign, or similarly useful PR/news update. '
            'Reject broad industry news, unrelated companies, generic keyword matches, and articles where the competitor is not central.'
        ),
        'candidates': [
            {
                'candidate_index': index,
                'keyword': candidate.get('keyword', ''),
                'title': candidate.get('title', ''),
                'source': candidate.get('source', ''),
                'snippet': candidate.get('snippet', ''),
                'url': candidate.get('url', ''),
            }
            for index, candidate in enumerate(candidates)
        ],
    }
    body = json.dumps({
        'model': model,
        'max_tokens': 1200,
        'tools': [build_news_validation_tool()],
        'tool_choice': {'type': 'tool', 'name': PR_NEWS_VALIDATION_TOOL_NAME},
        'messages': [
            {
                'role': 'user',
                'content': (
                    'Validate these Google News candidates for a competitor monitor. '
                    'Only approve candidates that are explicitly about the competitor brand/domain and represent press release or announcement-style news. '
                    f'{json.dumps(payload, ensure_ascii=True)[:12000]}'
                ),
            },
        ],
    }).encode('utf-8')

    request = Request(
        'https://api.anthropic.com/v1/messages',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        },
        method='POST',
    )

    try:
        with urlopen(request, timeout=get_ai_timeout_seconds()) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception:
        return strict_fallback

    decisions = {}
    for item in data.get('content', []):
        if item.get('type') == 'tool_use' and item.get('name') == PR_NEWS_VALIDATION_TOOL_NAME:
            tool_input = item.get('input') or {}
            for decision in tool_input.get('mentions', []):
                decisions[decision.get('candidate_index')] = decision

    approved = []
    for index, candidate in enumerate(candidates):
        decision = decisions.get(index)
        if not decision or not decision.get('is_relevant'):
            continue
        if not mention_is_relevant(candidate, brand_terms):
            continue
        approved.append({
            **candidate,
            'mention_type': decision.get('mention_type', 'competitor_news')[:100],
            'relevance_reason': decision.get('relevance_reason', ''),
            'competitive_impact': decision.get('competitive_impact', ''),
            'candidate_index': index,
        })
    return approved


def save_news_mentions(run):
    seen_urls = set()
    brand_terms = brand_terms_for_monitor(run.monitor)
    if not brand_terms:
        return 0

    keywords = run.monitor.news_keywords or []

    candidates = []
    for query in news_search_queries(run.monitor, keywords):
        for mention in fetch_google_news_mentions(query, query):
            if mention['url'] in seen_urls:
                continue
            seen_urls.add(mention['url'])
            candidates.append(mention)

    approved_mentions = validate_news_candidates_with_ai(run.monitor, candidates)
    count = 0
    for mention in approved_mentions:
        exists = PricingPRNewsMention.objects.filter(monitor=run.monitor, url=mention['url']).exists()
        if exists:
            continue
        mention.pop('candidate_index', None)
        PricingPRNewsMention.objects.create(run=run, monitor=run.monitor, **mention)
        count += 1
    return count


def fallback_summary(run):
    if not run.changes_found and not run.news_mentions_found:
        return 'No competitor website changes or validated Google News mentions were detected in this run.'
    return (
        f'This run checked {run.pages_checked} pages, found {run.changes_found} website changes, '
        f'and captured {run.news_mentions_found} validated Google News mentions. Review high-priority pricing or offer changes first, '
        'then use PR mentions to adjust positioning and response messaging.'
    )


def build_ai_prompt(run):
    changes = list(run.changes.values('change_type', 'severity', 'title', 'evidence', 'recommendation', 'current_snapshot__url')[:20])
    mentions = list(run.news_mentions.values('keyword', 'title', 'source', 'url', 'published_at', 'snippet')[:15])
    payload = {
        'competitor_name': run.monitor.competitor_name,
        'competitor_website': run.monitor.competitor_website,
        'changes': changes,
        'news_mentions': [
            {
                **mention,
                'published_at': mention['published_at'].isoformat() if mention['published_at'] else '',
            }
            for mention in mentions
        ],
    }
    return (
        'You are a competitive intelligence analyst. Summarize competitor pricing, website, and PR/news changes. '
        'Return a short executive insight, maximum 90 words. Use plain language. Include only: '
        '1) what changed, 2) why it matters, 3) recommended response. Do not include markdown headings. '
        'Do not invent facts.\n\n'
        f'{json.dumps(payload, ensure_ascii=True)[:10000]}'
    )


def generate_ai_summary(run):
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022').strip()
    if not api_key or (not run.changes_found and not run.news_mentions_found):
        run.ai_summary = fallback_summary(run)
        run.ai_model = ''
        run.ai_error = '' if api_key else 'ANTHROPIC_API_KEY is not configured; used fallback summary.'
        run.save(update_fields=['ai_summary', 'ai_model', 'ai_error'])
        return

    prompt = build_ai_prompt(run)
    body = json.dumps({
        'model': model,
        'max_tokens': min(get_ai_max_tokens(), 450),
        'messages': [{'role': 'user', 'content': prompt}],
    }).encode('utf-8')
    request = Request(
        'https://api.anthropic.com/v1/messages',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        },
        method='POST',
    )
    try:
        with urlopen(request, timeout=get_ai_timeout_seconds()) as response:
            data = json.loads(response.read().decode('utf-8'))
        text = '\n'.join(
            item.get('text', '')
            for item in data.get('content', [])
            if item.get('type') == 'text' and item.get('text')
        ).strip()
        usage = data.get('usage', {}) or {}
        input_tokens = usage.get('input_tokens') or 0
        output_tokens = usage.get('output_tokens') or 0
        run.ai_summary = text or fallback_summary(run)
        run.ai_model = model
        run.ai_error = ''
        run.ai_prompt_chars = len(prompt)
        run.ai_input_tokens = input_tokens
        run.ai_output_tokens = output_tokens
        run.ai_total_tokens = input_tokens + output_tokens
    except Exception as exc:
        run.ai_summary = fallback_summary(run)
        run.ai_model = model
        run.ai_error = f'AI summary failed; used fallback summary. {exc}'
        run.ai_prompt_chars = len(prompt)
    run.save(update_fields=[
        'ai_summary',
        'ai_model',
        'ai_error',
        'ai_prompt_chars',
        'ai_input_tokens',
        'ai_output_tokens',
        'ai_total_tokens',
    ])


def run_pricing_pr_monitor(run):
    try:
        for url in monitored_urls(run.monitor):
            snapshot_data = build_snapshot_data(url)
            snapshot = PricingPRSnapshot.objects.create(run=run, monitor=run.monitor, **snapshot_data)
            create_change_if_needed(run, snapshot)

        news_count = save_news_mentions(run)
        run.pages_checked = run.snapshots.count()
        run.changes_found = run.changes.count()
        run.news_mentions_found = news_count
        run.save(update_fields=['pages_checked', 'changes_found', 'news_mentions_found'])
        generate_ai_summary(run)
        run.status = PricingPRRun.STATUS_COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'completed_at'])
    except Exception as exc:
        run.status = PricingPRRun.STATUS_FAILED
        run.error_message = str(exc)
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'error_message', 'completed_at'])
        raise
