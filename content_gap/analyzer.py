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

from .models import ContentGapAnalysis


USER_AGENT = 'WisoftCoWorkerContentGap/1.0'
DEFAULT_HTML_READ_LIMIT_BYTES = 3 * 1024 * 1024
DEFAULT_ANTHROPIC_TIMEOUT_SECONDS = 90
DEFAULT_ANTHROPIC_MAX_TOKENS = 1600
HTML_CONTENT_TYPES = ('text/html', 'application/xhtml+xml')
CONTENT_GAP_TOOL_NAME = 'content_gap_analysis'
STOPWORDS = {
    'about', 'above', 'after', 'again', 'against', 'also', 'and', 'are', 'because', 'been',
    'before', 'being', 'below', 'between', 'both', 'but', 'can', 'cannot', 'could', 'did',
    'does', 'doing', 'down', 'during', 'each', 'few', 'for', 'from', 'further', 'had',
    'has', 'have', 'having', 'here', 'hers', 'him', 'his', 'how', 'into', 'its', 'itself',
    'just', 'more', 'most', 'not', 'now', 'off', 'once', 'only', 'other', 'our', 'ours',
    'out', 'over', 'own', 'same', 'she', 'should', 'some', 'such', 'than', 'that', 'the',
    'their', 'them', 'then', 'there', 'these', 'they', 'this', 'those', 'through', 'too',
    'under', 'until', 'very', 'was', 'were', 'what', 'when', 'where', 'which', 'while',
    'who', 'why', 'will', 'with', 'you', 'your', 'www', 'com', 'services', 'service',
    'contact', 'home', 'page', 'read', 'learn', 'more',
}


def get_html_read_limit_bytes():
    try:
        return int(os.environ.get('CONTENT_GAP_HTML_READ_LIMIT_BYTES', DEFAULT_HTML_READ_LIMIT_BYTES))
    except (TypeError, ValueError):
        return DEFAULT_HTML_READ_LIMIT_BYTES


def get_anthropic_timeout_seconds():
    try:
        return int(os.environ.get('CONTENT_GAP_ANTHROPIC_TIMEOUT_SECONDS', DEFAULT_ANTHROPIC_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_ANTHROPIC_TIMEOUT_SECONDS


def get_anthropic_max_tokens():
    try:
        return int(os.environ.get('CONTENT_GAP_ANTHROPIC_MAX_TOKENS', DEFAULT_ANTHROPIC_MAX_TOKENS))
    except (TypeError, ValueError):
        return DEFAULT_ANTHROPIC_MAX_TOKENS


class ContentSnapshotParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.base_netloc = urlparse(base_url).netloc.lower()
        self.title = ''
        self.meta_description = ''
        self.headings = {'h1': [], 'h2': [], 'h3': []}
        self.body_parts = []
        self.image_count = 0
        self.video_count = 0
        self.internal_links_count = 0
        self.external_links_count = 0
        self.internal_links = []
        self.external_links = []
        self._seen_links = set()
        self._active_tag = None
        self._buffer = []
        self._ignored_depth = 0
        self._body_depth = 0

    def _inside_body(self):
        return self._body_depth > 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = {name.lower(): (value or '') for name, value in attrs}

        if tag == 'body':
            self._body_depth += 1

        if tag in {'script', 'style', 'noscript', 'svg'}:
            self._ignored_depth += 1
            return

        if tag == 'img' and self._inside_body():
            self.image_count += 1

        if tag == 'video' and self._inside_body():
            self.video_count += 1

        if tag == 'iframe' and self._inside_body():
            src = attrs_dict.get('src', '').lower()
            if any(provider in src for provider in ('youtube.com', 'youtu.be', 'vimeo.com', 'wistia.com')):
                self.video_count += 1

        if tag == 'a' and self._inside_body():
            href = attrs_dict.get('href', '').strip()
            if href and not href.lower().startswith(('mailto:', 'tel:', 'javascript:')):
                href_without_fragment = href.split('#', 1)[0].strip()
                if not href_without_fragment:
                    return
                link = urljoin(self.base_url, href_without_fragment)
                parsed_link = urlparse(link)
                if parsed_link.scheme in {'http', 'https'} and parsed_link.netloc:
                    normalized_link = parsed_link._replace(fragment='').geturl()
                    if normalized_link not in self._seen_links:
                        self._seen_links.add(normalized_link)
                        if parsed_link.netloc.lower() == self.base_netloc:
                            self.internal_links_count += 1
                            self.internal_links.append(normalized_link)
                        else:
                            self.external_links_count += 1
                            self.external_links.append(normalized_link)

        if tag == 'title' or (tag in {'h1', 'h2', 'h3'} and self._inside_body()):
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
        if not self._inside_body():
            return
        cleaned = ' '.join(data.split())
        if cleaned:
            self.body_parts.append(cleaned)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {'script', 'style', 'noscript', 'svg'} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if tag == 'body' and self._body_depth:
            self._body_depth -= 1
        if tag != self._active_tag:
            return

        text = normalize_text(' '.join(self._buffer))
        if tag == 'title' and not self.title:
            self.title = text
        elif tag in self.headings and text:
            self.headings[tag].append(text)
        self._active_tag = None
        self._buffer = []


def normalize_text(value):
    return ' '.join((value or '').split())


def decode_body(body):
    return body.decode('utf-8', errors='replace')


def fetch_url(url):
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


def extract_terms(text, limit=35):
    tokens = [
        token for token in re.findall(r'[a-zA-Z][a-zA-Z0-9-]{2,}', (text or '').lower())
        if token not in STOPWORDS and not token.isdigit()
    ]
    unigram_counts = Counter(tokens)
    bigram_counts = Counter(
        f'{tokens[index]} {tokens[index + 1]}'
        for index in range(len(tokens) - 1)
        if tokens[index] not in STOPWORDS and tokens[index + 1] not in STOPWORDS
    )

    combined = []
    for phrase, count in bigram_counts.most_common(limit):
        if count > 1:
            combined.append({'term': phrase, 'count': count})
    for term, count in unigram_counts.most_common(limit):
        if term not in {item['term'] for item in combined}:
            combined.append({'term': term, 'count': count})
        if len(combined) >= limit:
            break
    return combined


def build_snapshot(url):
    fetched = fetch_url(url)
    content_type = fetched['content_type'].lower()
    snapshot = {
        'url': url,
        'status_code': fetched['status_code'],
        'final_url': fetched['final_url'],
        'content_type': fetched['content_type'],
        'load_time_ms': fetched['load_time_ms'],
        'truncated': fetched['truncated'],
        'error_message': fetched['error_message'],
        'title': '',
        'meta_description': '',
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
        'top_terms': [],
        'body_excerpt': '',
    }
    if fetched['error_message'] or not any(content_type.startswith(valid) for valid in HTML_CONTENT_TYPES):
        return snapshot

    parser = ContentSnapshotParser(fetched['final_url'] or url)
    html = decode_body(fetched['body'])
    parser.feed(html)
    body_text = normalize_text(' '.join(parser.body_parts))

    snapshot.update({
        'title': parser.title[:500],
        'meta_description': parser.meta_description[:1000],
        'h1': parser.headings['h1'][:8],
        'h2': parser.headings['h2'][:30],
        'h3': parser.headings['h3'][:40],
        'word_count': len(body_text.split()),
        'image_count': parser.image_count,
        'video_count': parser.video_count,
        'internal_links_count': parser.internal_links_count,
        'external_links_count': parser.external_links_count,
        'internal_links': parser.internal_links[:100],
        'external_links': parser.external_links[:100],
        'top_terms': extract_terms(body_text),
        'body_excerpt': body_text[:3500],
    })
    return snapshot


def page_label(url):
    parsed = urlparse(url)
    return parsed.netloc or url


def terms_set(snapshot):
    return {item.get('term', '') for item in snapshot.get('top_terms', []) if item.get('term')}


def headings_set(snapshot):
    values = []
    for key in ('h1', 'h2', 'h3'):
        values.extend(snapshot.get(key, []))
    return {normalize_text(value).lower() for value in values if normalize_text(value)}


def build_fallback_recommendations(own_snapshot, competitor_snapshots):
    own_terms = terms_set(own_snapshot)
    own_headings = headings_set(own_snapshot)
    competitor_term_counts = Counter()
    competitor_heading_sources = {}

    for snapshot in competitor_snapshots:
        if snapshot.get('error_message'):
            continue
        for term in terms_set(snapshot):
            competitor_term_counts[term] += 1
        for heading in headings_set(snapshot):
            if heading and heading not in own_headings:
                competitor_heading_sources.setdefault(heading, []).append(page_label(snapshot['url']))

    missing_terms = [
        term for term, _count in competitor_term_counts.most_common(20)
        if term not in own_terms
    ][:12]
    missing_headings = list(competitor_heading_sources.items())[:12]

    content_gaps = [
        {
            'topic': heading.title(),
            'why_it_matters': 'Competitor pages cover this topic more explicitly than your page.',
            'competitors_covering': ', '.join(sources[:3]),
            'priority': 'High' if index < 4 else 'Medium',
            'recommendation': 'Add a focused section that answers this intent with examples, proof points, and internal links.',
        }
        for index, (heading, sources) in enumerate(missing_headings)
    ]

    keyword_opportunities = [
        {
            'keyword': term,
            'intent': 'Informational' if 'how' in term or 'guide' in term else 'Commercial',
            'opportunity': 'Competitors mention this term more prominently than your page.',
            'recommended_page': own_snapshot.get('url', ''),
        }
        for term in missing_terms
    ]

    recommended_sections = [
        {
            'section': gap['topic'],
            'purpose': gap['why_it_matters'],
            'source_competitors': gap['competitors_covering'],
            'priority': gap['priority'],
        }
        for gap in content_gaps[:8]
    ]

    if not recommended_sections:
        recommended_sections = [
            {
                'section': 'Search Intent Overview',
                'purpose': 'Clarify who the page is for and what problem it solves.',
                'source_competitors': 'Derived from page comparison',
                'priority': 'High',
            },
            {
                'section': 'FAQs',
                'purpose': 'Capture long-tail questions and reduce ambiguity for users.',
                'source_competitors': 'Derived from page comparison',
                'priority': 'Medium',
            },
        ]

    execution_plan = [
        'Validate the highest-priority missing topics against search intent and business value.',
        'Update the target page outline with the recommended sections and keyword opportunities.',
        'Write or brief content for the new sections with clear examples, proof points, and internal links.',
        'Publish changes, request indexing, and monitor rankings, impressions, and engagement after two to four weeks.',
    ]

    wireframe_sections = [
        {
            'name': 'Hero / Above the Fold',
            'goal': 'State the page promise, audience, and primary conversion path.',
            'elements': ['Clear H1', 'Short value proposition', 'Primary CTA'],
        },
    ]
    for section in recommended_sections[:6]:
        wireframe_sections.append({
            'name': section['section'],
            'goal': section['purpose'],
            'elements': ['H2 section', 'Short explanation', 'Examples or proof points', 'Internal links'],
        })
    wireframe_sections.append({
        'name': 'FAQs and Next Steps',
        'goal': 'Answer objections and guide users to the next action.',
        'elements': ['FAQ accordion', 'Related resources', 'CTA'],
    })

    return {
        'summary': 'Competitor pages show opportunities to expand topical coverage, strengthen keyword targeting, and add a more complete page structure.',
        'content_gaps': content_gaps,
        'keyword_opportunities': keyword_opportunities,
        'recommended_sections': recommended_sections,
        'execution_plan': execution_plan,
        'wireframe': {
            'title': f'Wireframe for {own_snapshot.get("title") or page_label(own_snapshot.get("url", ""))}',
            'sections': wireframe_sections,
        },
    }


def compact_snapshot_for_ai(snapshot):
    return {
        'url': snapshot.get('url', ''),
        'status_code': snapshot.get('status_code'),
        'title': snapshot.get('title', ''),
        'meta_description': snapshot.get('meta_description', '')[:300],
        'h1': snapshot.get('h1', [])[:5],
        'h2': snapshot.get('h2', [])[:12],
        'h3': snapshot.get('h3', [])[:12],
        'word_count': snapshot.get('word_count', 0),
        'image_count': snapshot.get('image_count', 0),
        'video_count': snapshot.get('video_count', 0),
        'internal_links_count': snapshot.get('internal_links_count', 0),
        'top_terms': snapshot.get('top_terms', [])[:15],
        'body_excerpt': snapshot.get('body_excerpt', '')[:500],
        'error_message': snapshot.get('error_message', ''),
    }


def compact_fallback_for_ai(fallback):
    return {
        'content_gaps': fallback.get('content_gaps', [])[:8],
        'keyword_opportunities': fallback.get('keyword_opportunities', [])[:10],
        'recommended_sections': fallback.get('recommended_sections', [])[:8],
        'execution_plan': fallback.get('execution_plan', [])[:4],
        'wireframe': fallback.get('wireframe', {}),
    }


def build_ai_prompt(analysis, own_snapshot, competitor_snapshots, fallback):
    payload = {
        'target_topic': analysis.project.target_topic,
        'target_market': analysis.project.target_market,
        'notes': analysis.project.notes,
        'own_page': compact_snapshot_for_ai(own_snapshot),
        'competitor_pages': [compact_snapshot_for_ai(snapshot) for snapshot in competitor_snapshots],
        'baseline_recommendations': compact_fallback_for_ai(fallback),
    }
    return (
        'You are an expert SEO content strategist. Compare the own page against competitor pages. '
        'Identify content gaps, untapped keyword opportunities, recommended page sections, a page wireframe, '
        'and an execution plan. Return compact valid JSON only. Do not use markdown, code fences, comments, '
        'or line breaks inside string values. Use these exact keys: summary, content_gaps, '
        'keyword_opportunities, recommended_sections, execution_plan, wireframe. '
        'Limits: summary 160 to 220 words, content_gaps max 5, keyword_opportunities max 8, '
        'recommended_sections max 5, execution_plan max 4, wireframe.sections max 5. '
        'The summary should explain the page strength, competitor advantage, main missing topics, '
        'keyword opportunity, page structure opportunity, and the recommended strategic direction. '
        'Each content gap object must use topic, why_it_matters, competitors_covering, priority, recommendation. '
        'Each keyword object must use keyword, intent, opportunity, recommended_page. '
        'Wireframe must contain title and sections. Each section must contain name, goal, and elements.\n\n'
        f'{json.dumps(payload, ensure_ascii=True)[:9000]}'
    )


def build_content_gap_tool():
    string_field = {'type': 'string', 'maxLength': 600}
    return {
        'name': CONTENT_GAP_TOOL_NAME,
        'description': 'Return structured content gap analysis for the compared pages.',
        'input_schema': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'summary': {'type': 'string', 'maxLength': 1800},
                'content_gaps': {
                    'type': 'array',
                    'maxItems': 5,
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'topic': string_field,
                            'why_it_matters': string_field,
                            'competitors_covering': string_field,
                            'priority': {'type': 'string', 'enum': ['High', 'Medium', 'Low']},
                            'recommendation': string_field,
                        },
                        'required': ['topic', 'why_it_matters', 'competitors_covering', 'priority', 'recommendation'],
                    },
                },
                'keyword_opportunities': {
                    'type': 'array',
                    'maxItems': 8,
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'keyword': string_field,
                            'intent': string_field,
                            'opportunity': string_field,
                            'recommended_page': string_field,
                        },
                        'required': ['keyword', 'intent', 'opportunity', 'recommended_page'],
                    },
                },
                'recommended_sections': {
                    'type': 'array',
                    'maxItems': 5,
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'section': string_field,
                            'purpose': string_field,
                            'source_competitors': string_field,
                            'priority': {'type': 'string', 'enum': ['High', 'Medium', 'Low']},
                        },
                        'required': ['section', 'purpose', 'source_competitors', 'priority'],
                    },
                },
                'execution_plan': {
                    'type': 'array',
                    'maxItems': 4,
                    'items': {'type': 'string', 'maxLength': 300},
                },
                'wireframe': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'title': {'type': 'string', 'maxLength': 250},
                        'sections': {
                            'type': 'array',
                            'maxItems': 5,
                            'items': {
                                'type': 'object',
                                'additionalProperties': False,
                                'properties': {
                                    'name': {'type': 'string', 'maxLength': 200},
                                    'goal': {'type': 'string', 'maxLength': 350},
                                    'elements': {
                                        'type': 'array',
                                        'maxItems': 5,
                                        'items': {'type': 'string', 'maxLength': 120},
                                    },
                                },
                                'required': ['name', 'goal', 'elements'],
                            },
                        },
                    },
                    'required': ['title', 'sections'],
                },
            },
            'required': [
                'summary',
                'content_gaps',
                'keyword_opportunities',
                'recommended_sections',
                'execution_plan',
                'wireframe',
            ],
        },
    }


def extract_json_object(text):
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise ValueError('AI response did not contain a JSON object.')
    return json.loads(text[start:end + 1])


def call_anthropic(prompt):
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        return None, '', 'ANTHROPIC_API_KEY is not configured.', {}

    model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022').strip()
    body = json.dumps({
        'model': model,
        'max_tokens': get_anthropic_max_tokens(),
        'tools': [build_content_gap_tool()],
        'tool_choice': {'type': 'tool', 'name': CONTENT_GAP_TOOL_NAME},
        'messages': [
            {'role': 'user', 'content': prompt},
        ],
    }).encode('utf-8')

    timeout_seconds = get_anthropic_timeout_seconds()
    last_error = ''
    try:
        for attempt in range(2):
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
                with urlopen(request, timeout=timeout_seconds) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    break
            except Exception as exc:
                last_error = str(exc)
                if attempt == 0:
                    time.sleep(1)
        else:
            return None, model, f'Claude request timed out or failed after retry: {last_error}', {}
    except Exception as exc:
        return None, model, str(exc), {}

    usage = data.get('usage', {}) or {}
    for item in data.get('content', []):
        if item.get('type') == 'tool_use' and item.get('name') == CONTENT_GAP_TOOL_NAME:
            tool_input = item.get('input')
            if isinstance(tool_input, dict):
                return tool_input, model, '', usage

    text_parts = [
        item.get('text', '')
        for item in data.get('content', [])
        if item.get('type') == 'text' and item.get('text')
    ]
    if not text_parts:
        return None, model, 'Claude returned an empty response.', usage

    response_text = '\n'.join(text_parts)
    try:
        return extract_json_object(response_text), model, '', usage
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, model, f'Could not parse Claude JSON: {exc}', usage


def merge_recommendations(fallback, ai_result):
    if not ai_result:
        return fallback
    merged = fallback.copy()
    for key in ('summary', 'content_gaps', 'keyword_opportunities', 'recommended_sections', 'execution_plan', 'wireframe'):
        value = ai_result.get(key)
        if value:
            merged[key] = value
    return merged


def run_content_gap_analysis(analysis):
    try:
        own_snapshot = build_snapshot(analysis.own_url)
        competitor_snapshots = [build_snapshot(url) for url in analysis.competitor_urls]
        fallback = build_fallback_recommendations(own_snapshot, competitor_snapshots)
        prompt = build_ai_prompt(analysis, own_snapshot, competitor_snapshots, fallback)
        ai_result, model, ai_error, usage = call_anthropic(prompt)
        recommendations = merge_recommendations(fallback, ai_result)
        input_tokens = usage.get('input_tokens') or 0
        output_tokens = usage.get('output_tokens') or 0

        analysis.own_page_snapshot = own_snapshot
        analysis.competitor_snapshots = competitor_snapshots
        analysis.ai_summary = recommendations.get('summary', '')
        analysis.content_gaps = recommendations.get('content_gaps', [])
        analysis.keyword_opportunities = recommendations.get('keyword_opportunities', [])
        analysis.recommended_sections = recommendations.get('recommended_sections', [])
        analysis.execution_plan = recommendations.get('execution_plan', [])
        analysis.wireframe = recommendations.get('wireframe', {})
        analysis.ai_model = model
        analysis.ai_error = ai_error
        analysis.ai_prompt_chars = len(prompt)
        analysis.ai_input_tokens = input_tokens
        analysis.ai_output_tokens = output_tokens
        analysis.ai_total_tokens = input_tokens + output_tokens
        analysis.status = ContentGapAnalysis.STATUS_COMPLETED
        analysis.completed_at = timezone.now()
        analysis.save()
    except Exception as exc:
        analysis.status = ContentGapAnalysis.STATUS_FAILED
        analysis.error_message = str(exc)
        analysis.completed_at = timezone.now()
        analysis.save(update_fields=['status', 'error_message', 'completed_at'])
        raise
