import json
import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from html.parser import HTMLParser
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from django.utils import timezone

from .models import TechnicalSEOAudit, TechnicalSEOIssue, TechnicalSEOPage
from .search_console import run_search_console_collection


USER_AGENT = 'WisoftCoWorkerTechnicalSEOAudit/1.0'
HTML_CONTENT_TYPES = ('text/html', 'application/xhtml+xml')
DEFAULT_HTML_READ_LIMIT_BYTES = 5 * 1024 * 1024
HREFLANG_PATTERN = re.compile(r'^(x-default|[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})?)$')
DEFAULT_AI_MAX_TOKENS = 1200
DEFAULT_AI_TIMEOUT_SECONDS = 240
DEFAULT_AI_RETRY_ATTEMPTS = 2


def get_html_read_limit_bytes():
    try:
        return int(os.environ.get('TECHNICAL_SEO_HTML_READ_LIMIT_BYTES', DEFAULT_HTML_READ_LIMIT_BYTES))
    except (TypeError, ValueError):
        return DEFAULT_HTML_READ_LIMIT_BYTES


def get_env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def is_timeout_error(exc):
    return isinstance(exc, (TimeoutError, socket.timeout)) or 'timed out' in str(exc).lower()


def execute_json_request(request_factory, timeout, attempts):
    max_attempts = max(1, attempts)
    for attempt in range(max_attempts):
        try:
            with urlopen(request_factory(), timeout=max(1, timeout)) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            if attempt >= max_attempts - 1 or not is_timeout_error(exc):
                raise
            time.sleep(2 * (attempt + 1))


class PageSEOParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ''
        self.meta_description = ''
        self.robots_directives = ''
        self.canonical_url = ''
        self.hreflang_links = []
        self.h1_texts = []
        self.h2_count = 0
        self.links = []
        self.images_count = 0
        self.images_missing_alt_count = 0
        self._active_tag = None
        self._text_buffer = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = {name.lower(): (value or '') for name, value in attrs}
        tag = tag.lower()

        if tag in {'title', 'h1', 'h2'}:
            self._active_tag = tag
            self._text_buffer = []

        if tag == 'meta':
            name = attrs_dict.get('name', '').lower()
            content = attrs_dict.get('content', '').strip()
            if name == 'description' and not self.meta_description:
                self.meta_description = content
            if name == 'robots':
                self.robots_directives = content

        rel_values = set(attrs_dict.get('rel', '').lower().split())

        if tag == 'link' and 'canonical' in rel_values:
            href = attrs_dict.get('href', '').strip()
            if href:
                self.canonical_url = normalize_url(urljoin(self.base_url, href))

        if tag == 'link' and 'alternate' in rel_values:
            hreflang = attrs_dict.get('hreflang', '').strip()
            href = attrs_dict.get('href', '').strip()
            if hreflang or href:
                self.hreflang_links.append({
                    'hreflang': hreflang.lower(),
                    'href': normalize_url(urljoin(self.base_url, href)) if href else '',
                })

        if tag == 'a':
            href = attrs_dict.get('href', '').strip()
            if href and not href.lower().startswith(('mailto:', 'tel:', 'javascript:')):
                self.links.append(normalize_url(urljoin(self.base_url, href)))

        if tag == 'img':
            self.images_count += 1
            if not attrs_dict.get('alt', '').strip():
                self.images_missing_alt_count += 1

    def handle_data(self, data):
        if self._active_tag:
            self._text_buffer.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag != self._active_tag:
            return

        text = ' '.join(' '.join(self._text_buffer).split())
        if tag == 'title' and not self.title:
            self.title = text
        elif tag == 'h1':
            self.h1_texts.append(text)
        elif tag == 'h2':
            self.h2_count += 1

        self._active_tag = None
        self._text_buffer = []


def normalize_url(url):
    url, _fragment = urldefrag(url)
    parsed = urlparse(url)
    scheme = parsed.scheme.lower() or 'https'
    netloc = parsed.netloc.lower()
    path = parsed.path or '/'
    if path != '/' and path.endswith('/'):
        path = path[:-1]
    return urlunparse((scheme, netloc, path, '', parsed.query, ''))


def same_site(url, root_netloc):
    parsed = urlparse(url)
    return parsed.scheme in {'http', 'https'} and parsed.netloc.lower() == root_netloc


def get_robots_parser(root_url):
    parsed = urlparse(root_url)
    robots_url = urlunparse((parsed.scheme, parsed.netloc, '/robots.txt', '', '', ''))
    parser = robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        return None
    return parser


def sitemap_url_for_root(root_url):
    parsed = urlparse(root_url)
    return urlunparse((parsed.scheme, parsed.netloc, '/sitemap.xml', '', '', ''))


def parse_sitemap_body(body):
    page_urls = []
    sitemap_urls = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return page_urls, sitemap_urls

    root_name = root.tag.lower()
    if root_name.endswith('sitemapindex'):
        for sitemap in root:
            if not sitemap.tag.lower().endswith('sitemap'):
                continue
            for child in sitemap:
                if child.tag.lower().endswith('loc') and child.text:
                    sitemap_urls.append(normalize_url(child.text.strip()))
                    break
    elif root_name.endswith('urlset'):
        for url_node in root:
            if not url_node.tag.lower().endswith('url'):
                continue
            for child in url_node:
                if child.tag.lower().endswith('loc') and child.text:
                    page_urls.append(normalize_url(child.text.strip()))
                    break
    return page_urls, sitemap_urls


def discover_sitemap_urls(root_url, root_netloc, robots, limit):
    sitemap_queue = deque()
    discovered_pages = []
    discovered_page_set = set()
    seen_sitemaps = set()

    for sitemap_url in (robots.site_maps() or []) if robots else []:
        normalized = normalize_url(sitemap_url)
        if same_site(normalized, root_netloc):
            sitemap_queue.append(normalized)

    direct_sitemap_url = sitemap_url_for_root(root_url)
    if direct_sitemap_url not in sitemap_queue:
        sitemap_queue.append(direct_sitemap_url)

    while sitemap_queue and len(discovered_pages) < limit and len(seen_sitemaps) < 25:
        sitemap_url = normalize_url(sitemap_queue.popleft())
        if sitemap_url in seen_sitemaps or not same_site(sitemap_url, root_netloc):
            continue
        seen_sitemaps.add(sitemap_url)
        result = fetch_url(sitemap_url)
        if result['error_message'] or not result['body'] or (result['status_code'] and result['status_code'] >= 400):
            continue

        page_urls, nested_sitemap_urls = parse_sitemap_body(result['body'])
        for page_url in page_urls:
            if same_site(page_url, root_netloc) and page_url not in discovered_page_set:
                discovered_pages.append(page_url)
                discovered_page_set.add(page_url)
                if len(discovered_pages) >= limit:
                    break
        for nested_sitemap_url in nested_sitemap_urls:
            if same_site(nested_sitemap_url, root_netloc) and nested_sitemap_url not in seen_sitemaps:
                sitemap_queue.append(nested_sitemap_url)

    return discovered_pages


def build_initial_crawl_queue(root_url, sitemap_urls, max_pages):
    queued_urls = set()
    queue = deque()

    def add_seed(url, depth):
        if len(queue) >= max_pages:
            return
        normalized = normalize_url(url)
        if normalized in queued_urls:
            return
        queued_urls.add(normalized)
        queue.append((normalized, depth))

    add_seed(root_url, 0)
    for sitemap_url in sitemap_urls:
        add_seed(sitemap_url, 1)

    return queue, queued_urls


def fetch_url(url):
    started = time.monotonic()
    request = Request(url, headers={'User-Agent': USER_AGENT})
    html_read_limit = get_html_read_limit_bytes()
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read(html_read_limit + 1)
            html_truncated = len(body) > html_read_limit
            if html_truncated:
                body = body[:html_read_limit]
            elapsed_ms = int((time.monotonic() - started) * 1000)
            content_type = response.headers.get('Content-Type', '')
            return {
                'url': url,
                'status_code': response.getcode(),
                'final_url': normalize_url(response.geturl()),
                'content_type': content_type,
                'body': body,
                'load_time_ms': elapsed_ms,
                'html_truncated': html_truncated,
                'error_message': '',
            }
    except HTTPError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            'url': url,
            'status_code': exc.code,
            'final_url': normalize_url(exc.url or url),
            'content_type': exc.headers.get('Content-Type', '') if exc.headers else '',
            'body': b'',
            'load_time_ms': elapsed_ms,
            'html_truncated': False,
            'error_message': str(exc),
        }
    except (URLError, TimeoutError, ValueError) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            'url': url,
            'status_code': None,
            'final_url': url,
            'content_type': '',
            'body': b'',
            'load_time_ms': elapsed_ms,
            'html_truncated': False,
            'error_message': str(exc),
        }


def parse_page(fetch_result):
    content_type = fetch_result['content_type'].lower()
    if not any(content_type.startswith(valid_type) for valid_type in HTML_CONTENT_TYPES):
        return None

    try:
        html = fetch_result['body'].decode('utf-8', errors='replace')
    except Exception:
        return None

    parser = PageSEOParser(fetch_result['final_url'])
    parser.feed(html)
    return parser


def add_issue(audit, page, issue_type, severity, title, evidence, recommendation):
    return TechnicalSEOIssue.objects.create(
        audit=audit,
        page=page,
        issue_type=issue_type,
        severity=severity,
        title=title,
        evidence=evidence,
        recommendation=recommendation,
    )


def normalize_text(value):
    return ' '.join((value or '').split()).strip().lower()


def detect_page_issues(audit, page):
    status_code = page.status_code or 0
    html_truncated = page.raw_data.get('html_truncated', False)

    if status_code >= 500:
        add_issue(
            audit,
            page,
            'server_error',
            TechnicalSEOIssue.SEVERITY_CRITICAL,
            'Server error blocks crawling',
            f'{page.url} returned HTTP {status_code}.',
            'Fix the server error and confirm the page returns a stable 200 response.',
        )
    elif status_code == 404:
        add_issue(
            audit,
            page,
            'not_found',
            TechnicalSEOIssue.SEVERITY_HIGH,
            'Page returns 404',
            f'{page.url} returned HTTP 404.',
            'Restore the page, update internal links, or redirect the URL to the most relevant live page.',
        )
    elif status_code in {301, 302, 307, 308} or (
        status_code < 400 and page.final_url and normalize_url(page.final_url) != normalize_url(page.url)
    ):
        add_issue(
            audit,
            page,
            'redirect',
            TechnicalSEOIssue.SEVERITY_LOW,
            'URL redirects',
            f'{page.url} redirects to {page.final_url}.',
            'Update internal links so they point directly to the final destination URL.',
        )
    elif status_code == 0:
        add_issue(
            audit,
            page,
            'crawl_failed',
            TechnicalSEOIssue.SEVERITY_HIGH,
            'Page could not be crawled',
            page.error_message or 'The crawler could not fetch this URL.',
            'Check DNS, SSL, firewall, timeout, and robots restrictions for the URL.',
        )

    if status_code and status_code >= 400:
        return

    if html_truncated:
        add_issue(
            audit,
            page,
            'html_truncated',
            TechnicalSEOIssue.SEVERITY_LOW,
            'HTML was too large for complete analysis',
            'The crawler reached the configured HTML read limit before the full document was parsed.',
            'Increase TECHNICAL_SEO_HTML_READ_LIMIT_BYTES or reduce excessive HTML output so metadata and headings can be audited fully.',
        )
        return

    if not page.title:
        add_issue(
            audit,
            page,
            'missing_title',
            TechnicalSEOIssue.SEVERITY_HIGH,
            'Missing title tag',
            'No title tag was found.',
            'Add a unique, descriptive title tag that reflects the page topic and search intent.',
        )
    elif len(page.title) > 65:
        add_issue(
            audit,
            page,
            'long_title',
            TechnicalSEOIssue.SEVERITY_LOW,
            'Title tag is too long',
            f'Title length is {len(page.title)} characters.',
            'Shorten the title so the main topic and differentiator appear early.',
        )

    if not page.meta_description:
        add_issue(
            audit,
            page,
            'missing_meta_description',
            TechnicalSEOIssue.SEVERITY_MEDIUM,
            'Missing meta description',
            'No meta description was found.',
            'Write a concise meta description that summarizes the page and encourages clicks.',
        )
    elif len(page.meta_description) > 160:
        add_issue(
            audit,
            page,
            'long_meta_description',
            TechnicalSEOIssue.SEVERITY_LOW,
            'Meta description is too long',
            f'Meta description length is {len(page.meta_description)} characters.',
            'Trim the description so the strongest value proposition appears within typical SERP limits.',
        )

    if page.h1_count == 0:
        add_issue(
            audit,
            page,
            'missing_h1',
            TechnicalSEOIssue.SEVERITY_MEDIUM,
            'Missing H1',
            'No H1 heading was found.',
            'Add one clear H1 that describes the main topic of the page.',
        )
    elif page.h1_count > 1:
        add_issue(
            audit,
            page,
            'multiple_h1',
            TechnicalSEOIssue.SEVERITY_LOW,
            'Multiple H1 headings',
            f'{page.h1_count} H1 headings were found.',
            'Keep one primary H1 and demote supporting headings to H2 or H3 where appropriate.',
        )

    robots = page.robots_directives.lower()
    if 'noindex' in robots:
        add_issue(
            audit,
            page,
            'noindex',
            TechnicalSEOIssue.SEVERITY_HIGH,
            'Page is marked noindex',
            f'Robots directives: {page.robots_directives}',
            'Remove noindex if this page should be eligible for organic search indexing.',
        )

    if not page.canonical_url:
        add_issue(
            audit,
            page,
            'missing_canonical',
            TechnicalSEOIssue.SEVERITY_LOW,
            'Missing canonical URL',
            'No canonical link tag was found.',
            'Add a self-referencing canonical tag unless another URL should be treated as the canonical version.',
        )
    elif normalize_url(page.canonical_url) != normalize_url(page.final_url or page.url):
        add_issue(
            audit,
            page,
            'canonical_mismatch',
            TechnicalSEOIssue.SEVERITY_MEDIUM,
            'Canonical points elsewhere',
            f'Canonical URL is {page.canonical_url}.',
            'Confirm the canonical target is intentional; otherwise update it to the preferred indexable URL.',
        )

    if page.images_missing_alt_count:
        add_issue(
            audit,
            page,
            'missing_image_alt',
            TechnicalSEOIssue.SEVERITY_LOW,
            'Images missing alt text',
            f'{page.images_missing_alt_count} of {page.images_count} images have empty alt text.',
            'Add descriptive alt text for meaningful images and leave only decorative images empty.',
        )

    if page.load_time_ms and page.load_time_ms > 3000:
        add_issue(
            audit,
            page,
            'slow_response',
            TechnicalSEOIssue.SEVERITY_MEDIUM,
            'Slow page response',
            f'Fetch time was {page.load_time_ms} ms.',
            'Review server response time, caching, render-blocking assets, and heavy page resources.',
        )


def detect_duplicate_issues(audit):
    pages = list(audit.pages.filter(status_code__lt=400))
    title_groups = defaultdict(list)
    description_groups = defaultdict(list)
    h1_groups = defaultdict(list)
    h1_display_values = {}

    for page in pages:
        if page.title:
            title_groups[page.title.strip().lower()].append(page)
        if page.meta_description:
            description_groups[page.meta_description.strip().lower()].append(page)
        for h1_text in page.raw_data.get('h1_texts', []):
            normalized_h1 = normalize_text(h1_text)
            if normalized_h1:
                h1_groups[normalized_h1].append(page)
                h1_display_values.setdefault(normalized_h1, ' '.join(h1_text.split()))

    for group in title_groups.values():
        if len(group) < 2:
            continue
        urls = ', '.join(page.url for page in group[:5])
        for page in group:
            add_issue(
                audit,
                page,
                'duplicate_title',
                TechnicalSEOIssue.SEVERITY_MEDIUM,
                'Duplicate title tag',
                f'This title is shared by {len(group)} pages. Examples: {urls}',
                'Rewrite title tags so each important page has a unique search result headline.',
            )

    for group in description_groups.values():
        if len(group) < 2:
            continue
        urls = ', '.join(page.url for page in group[:5])
        for page in group:
            add_issue(
                audit,
                page,
                'duplicate_meta_description',
                TechnicalSEOIssue.SEVERITY_LOW,
                'Duplicate meta description',
                f'This meta description is shared by {len(group)} pages. Examples: {urls}',
                'Write unique descriptions for pages that target distinct topics or intents.',
            )

    for h1_text, group in h1_groups.items():
        unique_pages = list({page.id: page for page in group}.values())
        if len(unique_pages) < 2:
            continue
        urls = ', '.join(page.url for page in unique_pages[:5])
        display_h1 = h1_display_values.get(h1_text, h1_text)
        for page in unique_pages:
            add_issue(
                audit,
                page,
                'duplicate_h1',
                TechnicalSEOIssue.SEVERITY_LOW,
                'Duplicate H1 across pages',
                f'The H1 "{display_h1}" is shared by {len(unique_pages)} pages. Examples: {urls}',
                'Make the primary H1 unique enough to describe this page topic and distinguish it from related pages.',
            )


def detect_hreflang_issues(audit):
    pages = list(audit.pages.filter(status_code__lt=400))
    all_pages = list(audit.pages.all())
    pages_by_url = {}
    for page in all_pages:
        pages_by_url[normalize_url(page.final_url or page.url)] = page
        pages_by_url[normalize_url(page.url)] = page

    for page in pages:
        hreflang_links = page.raw_data.get('hreflang_links', []) or []
        if not hreflang_links:
            continue

        seen_langs = defaultdict(list)
        for link in hreflang_links:
            hreflang = (link.get('hreflang') or '').strip().lower()
            href = (link.get('href') or '').strip()
            if not hreflang:
                add_issue(
                    audit,
                    page,
                    'hreflang_missing_language',
                    TechnicalSEOIssue.SEVERITY_LOW,
                    'Hreflang language is missing',
                    f'Hreflang alternate points to {href or "an empty URL"} without a language value.',
                    'Add a valid hreflang value such as en, en-ae, ar, or x-default.',
                )
            elif not HREFLANG_PATTERN.match(hreflang):
                add_issue(
                    audit,
                    page,
                    'hreflang_invalid_language',
                    TechnicalSEOIssue.SEVERITY_LOW,
                    'Invalid hreflang value',
                    f'Hreflang value "{hreflang}" does not match a valid language or language-region pattern.',
                    'Use valid ISO language codes and optional region codes, for example en, en-ae, ar-ae, or x-default.',
                )

            if not href:
                add_issue(
                    audit,
                    page,
                    'hreflang_missing_href',
                    TechnicalSEOIssue.SEVERITY_LOW,
                    'Hreflang URL is missing',
                    f'Hreflang value "{hreflang or "-"}" has no href URL.',
                    'Add the absolute URL for the alternate language page.',
                )
                continue

            seen_langs[hreflang].append(href)
            target_page = pages_by_url.get(normalize_url(href))
            if target_page and (target_page.status_code or 0) >= 400:
                add_issue(
                    audit,
                    page,
                    'hreflang_target_error',
                    TechnicalSEOIssue.SEVERITY_MEDIUM,
                    'Hreflang target is not crawlable',
                    f'Hreflang target {href} returned HTTP {target_page.status_code}.',
                    'Point hreflang to live, indexable pages that return a successful status code.',
                )
                continue

            if not target_page or target_page.id == page.id:
                continue

            target_links = target_page.raw_data.get('hreflang_links', []) or []
            source_url = normalize_url(page.final_url or page.url)
            has_return_link = any(normalize_url(item.get('href', '')) == source_url for item in target_links if item.get('href'))
            if not has_return_link:
                add_issue(
                    audit,
                    page,
                    'hreflang_missing_return',
                    TechnicalSEOIssue.SEVERITY_MEDIUM,
                    'Hreflang return link missing',
                    f'{page.url} references {href}, but the target page does not link back to this URL with hreflang.',
                    'Add reciprocal hreflang annotations on every alternate page in the language cluster.',
                )

        for hreflang, hrefs in seen_langs.items():
            unique_hrefs = set(hrefs)
            if hreflang and len(hrefs) > 1 and len(unique_hrefs) > 1:
                add_issue(
                    audit,
                    page,
                    'hreflang_duplicate_language',
                    TechnicalSEOIssue.SEVERITY_LOW,
                    'Duplicate hreflang language target',
                    f'Hreflang "{hreflang}" points to multiple URLs: {", ".join(sorted(unique_hrefs)[:5])}',
                    'Keep one URL per hreflang value on each page to avoid sending conflicting alternate signals.',
                )


def summarize_without_ai(audit):
    counts = Counter(audit.issues.values_list('severity', flat=True))
    top_issue_types = Counter(audit.issues.values_list('issue_type', flat=True)).most_common(5)
    if not audit.issues_found:
        return 'No technical SEO issues were found in the crawled pages. Continue monitoring indexability, performance, and internal links as the site changes.'

    issue_summary = ', '.join(f'{count} {issue_type.replace("_", " ")}' for issue_type, count in top_issue_types)
    return (
        f'The audit crawled {audit.pages_crawled} pages and found {audit.issues_found} issues. '
        f'Priority counts: {counts.get("critical", 0)} critical, {counts.get("high", 0)} high, '
        f'{counts.get("medium", 0)} medium, and {counts.get("low", 0)} low. '
        f'The most common issue themes are {issue_summary}. Start with crawl-blocking errors, '
        'indexability directives, and duplicate or missing metadata before lower-priority content refinements.'
    )


def build_ai_payload(audit):
    issues = list(
        audit.issues.select_related('page')
        .order_by('severity', 'issue_type')[:80]
        .values('severity', 'issue_type', 'title', 'evidence', 'recommendation', 'page__url')
    )
    gsc_inspections = list(
        audit.gsc_url_inspections.select_related('page').order_by('inspection_url')[:40]
        .values(
            'inspection_url',
            'verdict',
            'coverage_state',
            'indexing_state',
            'robots_txt_state',
            'page_fetch_state',
            'google_canonical',
            'user_canonical',
            'error_message',
            'page__url',
        )
    )
    return {
        'website': audit.website.website_url,
        'pages_crawled': audit.pages_crawled,
        'issues_found': audit.issues_found,
        'severity_counts': {
            'critical': audit.critical_issues,
            'high': audit.high_issues,
            'medium': audit.medium_issues,
            'low': audit.low_issues,
        },
        'issues': [
            {
                'url': issue['page__url'],
                'severity': issue['severity'],
                'type': issue['issue_type'],
                'title': issue['title'],
                'evidence': issue['evidence'],
                'deterministic_recommendation': issue['recommendation'],
            }
            for issue in issues
        ],
        'search_console': {
            'status': audit.gsc_status,
            'site_url': audit.gsc_site_url,
            'date_range': {
                'start': audit.gsc_start_date.isoformat() if audit.gsc_start_date else '',
                'end': audit.gsc_end_date.isoformat() if audit.gsc_end_date else '',
            },
            'url_inspections': list(gsc_inspections),
        },
    }


def extract_openai_response_text(data):
    if data.get('output_text'):
        return data['output_text'].strip()
    output_parts = []
    for item in data.get('output', []):
        for content in item.get('content', []):
            text = content.get('text')
            if text:
                output_parts.append(text)
    return '\n'.join(output_parts).strip()


def extract_anthropic_response_text(data):
    output_parts = []
    for content in data.get('content', []):
        if content.get('type') == 'text' and content.get('text'):
            output_parts.append(content['text'])
    return '\n'.join(output_parts).strip()


def build_ai_prompt(audit):
    return (
        'You are a senior technical SEO consultant. Analyze this structured crawl audit. '
        f'Return a complete client-ready summary that fits within {get_env_int("ANTHROPIC_MAX_TOKENS", DEFAULT_AI_MAX_TOKENS)} output tokens. '
        'Use exactly these sections: Executive summary, Top priorities, Corrective actions, '
        'Search Console insights, Developer notes. Keep each section concise. '
        'Use no more than 5 bullets per section and no more than 18 words per bullet. '
        'Prioritize the highest-impact findings instead of trying to mention every issue. '
        'End with the exact line: Summary complete. Be specific, do not invent facts. '
        'Use Google URL Inspection data only when present, connecting '
        'indexing verdicts, canonical differences, and crawl issues to practical fixes. '
        'Prioritize crawlability, indexability, metadata duplication, H1 duplication, hreflang, canonicalization, and performance.\n\n'
        f'{json.dumps(build_ai_payload(audit), indent=2)}'
    )


def generate_anthropic_summary(audit, prompt):
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022').strip()
    max_tokens = get_env_int('ANTHROPIC_MAX_TOKENS', DEFAULT_AI_MAX_TOKENS)
    timeout = get_env_int('AI_SUMMARY_TIMEOUT_SECONDS', DEFAULT_AI_TIMEOUT_SECONDS)
    attempts = get_env_int('AI_SUMMARY_RETRY_ATTEMPTS', DEFAULT_AI_RETRY_ATTEMPTS)
    if not api_key:
        return False

    def request_factory():
        body = json.dumps({
            'model': model,
            'max_tokens': max(1, max_tokens),
            'messages': [
                {
                    'role': 'user',
                    'content': prompt,
                },
            ],
        }).encode('utf-8')
        return Request(
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
        data = execute_json_request(request_factory, timeout, attempts)
        ai_summary = extract_anthropic_response_text(data)
        audit.ai_summary = ai_summary or summarize_without_ai(audit)
        audit.ai_model = f'anthropic:{model}'
        audit.ai_error = ''
    except Exception as exc:
        audit.ai_summary = summarize_without_ai(audit)
        audit.ai_model = f'anthropic:{model}'
        audit.ai_error = f'Claude summary failed; used fallback summary. {exc}'
    audit.save(update_fields=['ai_summary', 'ai_model', 'ai_error'])
    return True


def generate_openai_summary(audit, prompt):
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    model = os.environ.get('OPENAI_MODEL', 'gpt-4.1').strip()
    timeout = get_env_int('AI_SUMMARY_TIMEOUT_SECONDS', DEFAULT_AI_TIMEOUT_SECONDS)
    attempts = get_env_int('AI_SUMMARY_RETRY_ATTEMPTS', DEFAULT_AI_RETRY_ATTEMPTS)
    if not api_key:
        return False

    def request_factory():
        body = json.dumps({
            'model': model,
            'input': prompt,
        }).encode('utf-8')
        return Request(
            'https://api.openai.com/v1/responses',
            data=body,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )

    try:
        data = execute_json_request(request_factory, timeout, attempts)
        ai_summary = extract_openai_response_text(data)
        audit.ai_summary = ai_summary or summarize_without_ai(audit)
        audit.ai_model = f'openai:{model}'
        audit.ai_error = ''
    except Exception as exc:
        audit.ai_summary = summarize_without_ai(audit)
        audit.ai_model = f'openai:{model}'
        audit.ai_error = f'AI summary failed; used fallback summary. {exc}'
    audit.save(update_fields=['ai_summary', 'ai_model', 'ai_error'])
    return True


def generate_ai_summary(audit):
    prompt = build_ai_prompt(audit)
    if generate_anthropic_summary(audit, prompt):
        return
    if generate_openai_summary(audit, prompt):
        return

    audit.ai_model = ''
    audit.ai_error = 'No AI provider API key is configured; used deterministic fallback summary.'
    audit.ai_summary = summarize_without_ai(audit)
    audit.save(update_fields=['ai_model', 'ai_error', 'ai_summary'])


def update_audit_counts(audit):
    counts = Counter(audit.issues.values_list('severity', flat=True))
    audit.pages_crawled = audit.pages.count()
    audit.issues_found = audit.issues.count()
    audit.critical_issues = counts.get(TechnicalSEOIssue.SEVERITY_CRITICAL, 0)
    audit.high_issues = counts.get(TechnicalSEOIssue.SEVERITY_HIGH, 0)
    audit.medium_issues = counts.get(TechnicalSEOIssue.SEVERITY_MEDIUM, 0)
    audit.low_issues = counts.get(TechnicalSEOIssue.SEVERITY_LOW, 0)
    audit.save(update_fields=[
        'pages_crawled',
        'issues_found',
        'critical_issues',
        'high_issues',
        'medium_issues',
        'low_issues',
    ])


def run_technical_seo_audit(audit):
    root_url = normalize_url(audit.website.website_url)
    root_netloc = urlparse(root_url).netloc.lower()
    robots = get_robots_parser(root_url)
    sitemap_urls = discover_sitemap_urls(root_url, root_netloc, robots, audit.max_pages)
    sitemap_url_set = set(sitemap_urls)
    queue, queued_urls = build_initial_crawl_queue(root_url, sitemap_urls, audit.max_pages)
    seen = set()

    try:
        while queue and len(seen) < audit.max_pages:
            url, depth = queue.popleft()
            url = normalize_url(url)
            if url in seen or not same_site(url, root_netloc):
                continue
            seen.add(url)

            if robots and not robots.can_fetch(USER_AGENT, url):
                page = TechnicalSEOPage.objects.create(
                    audit=audit,
                    url=url,
                    status_code=0,
                    final_url=url,
                    depth=depth,
                    error_message='Blocked by robots.txt for this crawler user agent.',
                    raw_data={
                        'blocked_by_robots': True,
                        'source': 'sitemap' if url in sitemap_url_set else 'crawl',
                    },
                )
                add_issue(
                    audit,
                    page,
                    'blocked_by_robots',
                    TechnicalSEOIssue.SEVERITY_HIGH,
                    'URL blocked by robots.txt',
                    'robots.txt does not allow this crawler to fetch the page.',
                    'Review robots.txt rules and confirm important SEO pages are crawlable by search engines.',
                )
                continue

            result = fetch_url(url)
            parsed_page = parse_page(result)
            internal_links = []
            external_links = []

            if parsed_page:
                for link in parsed_page.links:
                    if same_site(link, root_netloc):
                        internal_links.append(link)
                    else:
                        external_links.append(link)

                for link in internal_links:
                    if link not in seen and link not in queued_urls and len(seen) + len(queue) < audit.max_pages:
                        queued_urls.add(link)
                        queue.append((link, depth + 1))

            page = TechnicalSEOPage.objects.create(
                audit=audit,
                url=url,
                status_code=result['status_code'] or 0,
                final_url=result['final_url'],
                content_type=result['content_type'][:255],
                title=(parsed_page.title[:500] if parsed_page else ''),
                meta_description=(parsed_page.meta_description if parsed_page else ''),
                canonical_url=(parsed_page.canonical_url if parsed_page else ''),
                robots_directives=(parsed_page.robots_directives[:255] if parsed_page else ''),
                h1_count=(len(parsed_page.h1_texts) if parsed_page else 0),
                h2_count=(parsed_page.h2_count if parsed_page else 0),
                internal_links_count=len(internal_links),
                external_links_count=len(external_links),
                images_count=(parsed_page.images_count if parsed_page else 0),
                images_missing_alt_count=(parsed_page.images_missing_alt_count if parsed_page else 0),
                depth=depth,
                load_time_ms=result['load_time_ms'],
                error_message=result['error_message'],
                raw_data={
                    'h1_texts': parsed_page.h1_texts[:10] if parsed_page else [],
                    'hreflang_links': parsed_page.hreflang_links[:50] if parsed_page else [],
                    'content_type': result['content_type'],
                    'final_url': result['final_url'],
                    'html_truncated': result['html_truncated'],
                    'html_read_limit_bytes': get_html_read_limit_bytes(),
                    'source': 'sitemap' if url in sitemap_url_set else 'crawl',
                },
            )
            detect_page_issues(audit, page)

        detect_duplicate_issues(audit)
        detect_hreflang_issues(audit)
        update_audit_counts(audit)
        run_search_console_collection(audit)
        generate_ai_summary(audit)
        audit.status = TechnicalSEOAudit.STATUS_COMPLETED
        audit.completed_at = timezone.now()
        audit.save(update_fields=['status', 'completed_at'])
    except Exception as exc:
        audit.status = TechnicalSEOAudit.STATUS_FAILED
        audit.error_message = str(exc)
        audit.completed_at = timezone.now()
        audit.save(update_fields=['status', 'error_message', 'completed_at'])
        raise
