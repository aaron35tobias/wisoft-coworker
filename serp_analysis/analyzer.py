import json
import os
import re
import time
from collections import Counter
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from django.utils import timezone

from .models import SERPAnalysis


USER_AGENT = 'WisoftCoWorkerSERPAnalysis/1.0'
HTML_CONTENT_TYPES = ('text/html', 'application/xhtml+xml')
DEFAULT_HTML_READ_LIMIT_BYTES = 4 * 1024 * 1024
STOPWORDS = {
    'about', 'after', 'also', 'and', 'are', 'best', 'can', 'for', 'from', 'get', 'has',
    'have', 'how', 'into', 'its', 'more', 'not', 'our', 'the', 'their', 'this', 'that',
    'these', 'they', 'with', 'you', 'your', 'www', 'com', 'contact', 'home', 'page',
    'read', 'learn', 'services', 'service',
}


def get_html_read_limit_bytes():
    try:
        return int(os.environ.get('SERP_ANALYSIS_HTML_READ_LIMIT_BYTES', DEFAULT_HTML_READ_LIMIT_BYTES))
    except (TypeError, ValueError):
        return DEFAULT_HTML_READ_LIMIT_BYTES


def normalize_text(value):
    return ' '.join((value or '').split())


def normalize_url(url):
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f'https://{url}'
    return url


class SERPPageParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.base_netloc = urlparse(base_url).netloc.lower()
        self.title = ''
        self.meta_description = ''
        self.canonical_url = ''
        self.robots_directives = ''
        self.headings = {'h1': [], 'h2': [], 'h3': []}
        self.body_parts = []
        self.image_count = 0
        self.video_count = 0
        self.internal_links_count = 0
        self.external_links_count = 0
        self.internal_links = []
        self.external_links = []
        self.schema_types = []
        self._active_tag = None
        self._buffer = []
        self._ignored_depth = 0
        self._json_ld_depth = 0
        self._json_ld_buffer = []
        self._seen_links = set()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = {name.lower(): (value or '') for name, value in attrs}

        if tag in {'script', 'style', 'noscript', 'svg'}:
            if tag == 'script' and attrs_dict.get('type', '').lower() == 'application/ld+json':
                self._json_ld_depth += 1
                self._json_ld_buffer = []
            else:
                self._ignored_depth += 1
            return

        if tag in {'title', 'h1', 'h2', 'h3'}:
            self._active_tag = tag
            self._buffer = []

        if tag == 'meta':
            name = attrs_dict.get('name', '').lower()
            content = attrs_dict.get('content', '').strip()
            if name == 'description' and content and not self.meta_description:
                self.meta_description = content
            if name == 'robots':
                self.robots_directives = content

        rel_values = set(attrs_dict.get('rel', '').lower().split())
        if tag == 'link' and 'canonical' in rel_values:
            href = attrs_dict.get('href', '').strip()
            if href:
                self.canonical_url = urljoin(self.base_url, href)

        if tag == 'img':
            self.image_count += 1

        if tag == 'video':
            self.video_count += 1

        if tag == 'iframe':
            src = attrs_dict.get('src', '').lower()
            if any(provider in src for provider in ('youtube.com', 'youtu.be', 'vimeo.com', 'wistia.com')):
                self.video_count += 1

        if tag == 'a':
            href = attrs_dict.get('href', '').strip()
            if href and not href.lower().startswith(('mailto:', 'tel:', 'javascript:')):
                href = href.split('#', 1)[0].strip()
                if not href:
                    return
                link = urljoin(self.base_url, href)
                parsed_link = urlparse(link)
                if parsed_link.scheme in {'http', 'https'} and parsed_link.netloc:
                    normalized = parsed_link._replace(fragment='').geturl()
                    if normalized in self._seen_links:
                        return
                    self._seen_links.add(normalized)
                    if parsed_link.netloc.lower() == self.base_netloc:
                        self.internal_links_count += 1
                        self.internal_links.append(normalized)
                    else:
                        self.external_links_count += 1
                        self.external_links.append(normalized)

    def handle_data(self, data):
        if self._json_ld_depth:
            self._json_ld_buffer.append(data)
            return
        if self._ignored_depth:
            return
        if self._active_tag:
            self._buffer.append(data)
        cleaned = normalize_text(data)
        if cleaned:
            self.body_parts.append(cleaned)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'script' and self._json_ld_depth:
            self._json_ld_depth -= 1
            self._extract_schema_types(''.join(self._json_ld_buffer))
            self._json_ld_buffer = []
            return
        if tag in {'script', 'style', 'noscript', 'svg'} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if tag != self._active_tag:
            return

        text = normalize_text(' '.join(self._buffer))
        if tag == 'title' and not self.title:
            self.title = text
        elif tag in self.headings and text:
            self.headings[tag].append(text)
        self._active_tag = None
        self._buffer = []

    def _extract_schema_types(self, value):
        try:
            data = json.loads(value)
        except Exception:
            return
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            graph = item.get('@graph') if isinstance(item.get('@graph'), list) else [item]
            for node in graph:
                schema_type = node.get('@type') if isinstance(node, dict) else ''
                if isinstance(schema_type, list):
                    self.schema_types.extend(str(value) for value in schema_type[:5])
                elif schema_type:
                    self.schema_types.append(str(schema_type))


def fetch_url(url):
    started = time.monotonic()
    url = normalize_url(url)
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


def extract_terms(text, limit=25):
    tokens = [
        token for token in re.findall(r'[a-zA-Z][a-zA-Z0-9-]{2,}', (text or '').lower())
        if token not in STOPWORDS and not token.isdigit()
    ]
    counts = Counter(tokens)
    return [{'term': term, 'count': count} for term, count in counts.most_common(limit)]


def performance_score(load_time_ms):
    if not load_time_ms:
        return 0
    if load_time_ms <= 800:
        return 95
    if load_time_ms <= 1500:
        return 85
    if load_time_ms <= 2500:
        return 70
    if load_time_ms <= 4000:
        return 50
    return 30


def clamp_score(value):
    return max(0, min(100, round(value)))


def score_snapshot(snapshot):
    status_code = snapshot.get('status_code') or 0
    title_length = len(snapshot.get('title') or '')
    meta_length = len(snapshot.get('meta_description') or '')
    word_count = snapshot.get('word_count') or 0
    h1_count = len(snapshot.get('h1') or [])
    h2_count = len(snapshot.get('h2') or [])
    media_count = (snapshot.get('image_count') or 0) + ((snapshot.get('video_count') or 0) * 2)
    schema_count = len(snapshot.get('schema_types') or [])
    internal_links = snapshot.get('internal_links_count') or 0
    external_links = snapshot.get('external_links_count') or 0

    content = clamp_score(
        min(word_count / 10, 60)
        + (20 if h1_count == 1 else 10 if h1_count > 1 else 0)
        + min(h2_count * 3, 20)
    )
    meta = clamp_score(
        (45 if 25 <= title_length <= 65 else 25 if title_length else 0)
        + (45 if 80 <= meta_length <= 165 else 25 if meta_length else 0)
        + (10 if snapshot.get('top_terms') else 0)
    )
    technical = clamp_score(
        (30 if status_code and status_code < 400 else 0)
        + (35 if snapshot.get('canonical_url') else 0)
        + (35 if 'noindex' not in (snapshot.get('robots_directives') or '').lower() else 0)
    )
    media_schema = clamp_score(min(media_count * 10, 55) + min(schema_count * 15, 45))
    links = clamp_score(min(internal_links * 8, 70) + min(external_links * 5, 30))
    pagespeed = snapshot.get('performance_score') or 0
    overall = clamp_score((content + meta + technical + media_schema + links + pagespeed) / 6)

    return {
        'overall': overall,
        'content': content,
        'meta': meta,
        'technical': technical,
        'media_schema': media_schema,
        'links': links,
        'pagespeed': pagespeed,
    }


def build_snapshot(url, result_type):
    fetched = fetch_url(url)
    snapshot = {
        'type': result_type,
        'url': fetched['url'],
        'status_code': fetched['status_code'],
        'final_url': fetched['final_url'],
        'content_type': fetched['content_type'],
        'load_time_ms': fetched['load_time_ms'],
        'performance_score': performance_score(fetched['load_time_ms']),
        'truncated': fetched['truncated'],
        'error_message': fetched['error_message'],
        'title': '',
        'meta_description': '',
        'canonical_url': '',
        'robots_directives': '',
        'h1': [],
        'h2': [],
        'h3': [],
        'word_count': 0,
        'image_count': 0,
        'video_count': 0,
        'internal_links_count': 0,
        'external_links_count': 0,
        'internal_links': [],
        'external_links': [],
        'schema_types': [],
        'top_terms': [],
        'content_excerpt': '',
    }
    content_type = fetched['content_type'].lower()
    if fetched['error_message'] or not any(content_type.startswith(valid) for valid in HTML_CONTENT_TYPES):
        snapshot['scores'] = score_snapshot(snapshot)
        return snapshot

    parser = SERPPageParser(fetched['final_url'] or fetched['url'])
    html = fetched['body'].decode('utf-8', errors='replace')
    parser.feed(html)
    body_text = normalize_text(' '.join(parser.body_parts))
    snapshot.update({
        'title': parser.title[:500],
        'meta_description': parser.meta_description[:1000],
        'canonical_url': parser.canonical_url[:1000],
        'robots_directives': parser.robots_directives[:255],
        'h1': parser.headings['h1'][:8],
        'h2': parser.headings['h2'][:25],
        'h3': parser.headings['h3'][:30],
        'word_count': len(body_text.split()),
        'image_count': parser.image_count,
        'video_count': parser.video_count,
        'internal_links_count': parser.internal_links_count,
        'external_links_count': parser.external_links_count,
        'internal_links': parser.internal_links[:100],
        'external_links': parser.external_links[:100],
        'schema_types': sorted(set(parser.schema_types))[:10],
        'top_terms': extract_terms(body_text),
        'content_excerpt': body_text[:1200],
    })
    snapshot['scores'] = score_snapshot(snapshot)
    return snapshot


def build_findings(target_snapshot, competitor_snapshots):
    snapshots = ([target_snapshot] if target_snapshot else []) + competitor_snapshots
    technical_findings = []
    for snapshot in snapshots:
        label = 'Target' if snapshot.get('type') == 'target' else 'Competitor'
        url = snapshot.get('url', '')
        status_code = snapshot.get('status_code') or 0
        if snapshot.get('error_message'):
            technical_findings.append({'severity': 'High', 'area': 'Crawl', 'page': url, 'finding': snapshot['error_message'], 'recommendation': 'Confirm the URL is reachable and not blocked.'})
        if status_code >= 400:
            technical_findings.append({'severity': 'High', 'area': 'Status', 'page': url, 'finding': f'{label} page returned HTTP {status_code}.', 'recommendation': 'Use only live, indexable SERP URLs for comparison.'})
        if not snapshot.get('title'):
            technical_findings.append({'severity': 'Medium', 'area': 'Meta', 'page': url, 'finding': 'Missing title tag.', 'recommendation': 'Add a descriptive title aligned to the target keyword.'})
        elif len(snapshot.get('title', '')) > 65:
            technical_findings.append({'severity': 'Low', 'area': 'Meta', 'page': url, 'finding': f'Title is {len(snapshot["title"])} characters.', 'recommendation': 'Keep the main intent and differentiator early in the title.'})
        if not snapshot.get('meta_description'):
            technical_findings.append({'severity': 'Medium', 'area': 'Meta', 'page': url, 'finding': 'Missing meta description.', 'recommendation': 'Add a click-focused description for SERP appeal.'})
        if not snapshot.get('canonical_url'):
            technical_findings.append({'severity': 'Low', 'area': 'Canonical', 'page': url, 'finding': 'Missing canonical tag.', 'recommendation': 'Add a self-referencing canonical unless another URL is preferred.'})
        if 'noindex' in (snapshot.get('robots_directives') or '').lower():
            technical_findings.append({'severity': 'High', 'area': 'Indexing', 'page': url, 'finding': 'Page is marked noindex.', 'recommendation': 'Remove noindex if the page should compete in organic search.'})
        if snapshot.get('performance_score', 0) < 60:
            technical_findings.append({'severity': 'Medium', 'area': 'PageSpeed', 'page': url, 'finding': f'Fetch performance score is {snapshot.get("performance_score", 0)}.', 'recommendation': 'Investigate server response, caching, and heavy page resources.'})
    return technical_findings


def build_strategy_and_opportunities(keyword, target_snapshot, competitor_snapshots):
    content_strategies = []
    competitor_terms = Counter()
    competitor_headings = Counter()
    for snapshot in competitor_snapshots:
        if snapshot.get('error_message'):
            continue
        content_strategies.append({
            'competitor': urlparse(snapshot.get('url', '')).netloc or snapshot.get('url', ''),
            'content_depth': snapshot.get('word_count', 0),
            'primary_angle': (snapshot.get('h1') or [snapshot.get('title') or '-'])[0],
            'serp_assets': f'{snapshot.get("image_count", 0)} images, {snapshot.get("video_count", 0)} videos, {len(snapshot.get("schema_types", []))} schema types',
            'technical_strength': f'Score: {(snapshot.get("scores") or {}).get("overall", 0)}, Canonical: {"Yes" if snapshot.get("canonical_url") else "No"}, Performance: {snapshot.get("performance_score", 0)}',
        })
        for term in snapshot.get('top_terms', []):
            competitor_terms[term.get('term', '')] += term.get('count', 0)
        for heading in (snapshot.get('h2') or [])[:10]:
            competitor_headings[normalize_text(heading).lower()] += 1

    target_terms = {item.get('term') for item in (target_snapshot or {}).get('top_terms', [])}
    target_headings = {normalize_text(item).lower() for item in (target_snapshot or {}).get('h2', [])}
    opportunities = []
    for term, count in competitor_terms.most_common(10):
        if term and term not in target_terms:
            opportunities.append({
                'priority': 'High' if len(opportunities) < 4 else 'Medium',
                'opportunity': f'Competitors emphasize "{term}" more than the target page.',
                'recommendation': f'Add or strengthen coverage around "{term}" with examples, FAQs, and internal links.',
            })
    for heading, count in competitor_headings.most_common(8):
        if heading and heading not in target_headings:
            opportunities.append({
                'priority': 'Medium',
                'opportunity': f'Competitor pages include a section around "{heading.title()}".',
                'recommendation': 'Consider whether this section matches the target keyword intent and add it if useful.',
            })
    if target_snapshot and competitor_snapshots:
        avg_words = sum(item.get('word_count', 0) for item in competitor_snapshots) // max(1, len(competitor_snapshots))
        if target_snapshot.get('word_count', 0) < avg_words * 0.65:
            opportunities.insert(0, {
                'priority': 'High',
                'opportunity': f'Target page is thinner than competitors for "{keyword}".',
                'recommendation': f'Expand the page from {target_snapshot.get("word_count", 0)} words toward the competitor average of {avg_words} words where intent requires depth.',
            })
    return content_strategies, opportunities[:12]


def fallback_summary(analysis):
    return (
        f'The SERP analysis compared the own target page against {analysis.competitor_count} competitor result pages '
        f'for "{analysis.keyword}". The report highlights where competitors are stronger in content depth, metadata, '
        f'canonical signals, media usage, internal linking, and response-time based performance. Use the scorecard to see '
        f'where the own page is ahead, close, or behind. Start with high-priority '
        f'content gaps and technical findings, then improve the target page title, meta description, headings, '
        f'canonical/indexing signals, and page speed where needed.'
    )


def generate_ai_summary(analysis):
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022').strip()
    if not api_key:
        analysis.ai_model = ''
        analysis.ai_error = 'No AI provider configured; used deterministic summary.'
        analysis.ai_summary = fallback_summary(analysis)
        analysis.save(update_fields=['ai_model', 'ai_error', 'ai_summary'])
        return

    payload = {
        'keyword': analysis.keyword,
        'location': analysis.location,
        'target_page': analysis.target_snapshot,
        'competitor_pages': analysis.competitor_snapshots,
        'content_strategies': analysis.content_strategies,
        'opportunities': analysis.serp_opportunities,
        'technical_findings': analysis.technical_findings,
    }
    prompt = (
        'You are a senior SEO strategist. Summarize this own-page vs competitor SERP analysis in 180-260 words. '
        'Compare the target page against competitors. Mention competitor content strategies, SERP opportunities, '
        'canonical/meta/indexing issues, and page speed observations. '
        'Do not invent rankings or search volume. Use only the provided page snapshots.\n\n'
        f'{json.dumps(payload, indent=2)[:18000]}'
    )
    body = json.dumps({
        'model': model,
        'max_tokens': 900,
        'messages': [{'role': 'user', 'content': prompt}],
    }).encode('utf-8')
    request = Request(
        'https://api.anthropic.com/v1/messages',
        data=body,
        headers={
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode('utf-8'))
        text_parts = [
            item.get('text', '')
            for item in data.get('content', [])
            if item.get('type') == 'text' and item.get('text')
        ]
        analysis.ai_summary = '\n'.join(text_parts).strip() or fallback_summary(analysis)
        analysis.ai_model = f'anthropic:{model}'
        analysis.ai_error = ''
    except Exception as exc:
        analysis.ai_summary = fallback_summary(analysis)
        analysis.ai_model = f'anthropic:{model}'
        analysis.ai_error = f'Claude summary failed; used fallback summary. {exc}'
    analysis.save(update_fields=['ai_summary', 'ai_model', 'ai_error'])


def run_serp_analysis(analysis):
    try:
        target_snapshot = build_snapshot(analysis.target_url, 'target') if analysis.target_url else {}
        competitor_snapshots = [
            build_snapshot(url, 'competitor')
            for url in analysis.competitor_urls
        ]
        content_strategies, opportunities = build_strategy_and_opportunities(
            analysis.keyword,
            target_snapshot,
            competitor_snapshots,
        )
        analysis.target_snapshot = target_snapshot
        analysis.competitor_snapshots = competitor_snapshots
        analysis.content_strategies = content_strategies
        analysis.serp_opportunities = opportunities
        analysis.technical_findings = build_findings(target_snapshot, competitor_snapshots)
        analysis.save(update_fields=[
            'target_snapshot',
            'competitor_snapshots',
            'content_strategies',
            'serp_opportunities',
            'technical_findings',
        ])
        generate_ai_summary(analysis)
        analysis.status = SERPAnalysis.STATUS_COMPLETED
        analysis.completed_at = timezone.now()
        analysis.save(update_fields=['status', 'completed_at'])
    except Exception as exc:
        analysis.status = SERPAnalysis.STATUS_FAILED
        analysis.error_message = str(exc)
        analysis.completed_at = timezone.now()
        analysis.save(update_fields=['status', 'error_message', 'completed_at'])
        raise
