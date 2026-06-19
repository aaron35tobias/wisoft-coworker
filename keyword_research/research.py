import json
import os
import re
import time
from collections import Counter, deque
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from .models import KeywordCluster, KeywordIdea, KeywordPlannerMetric, KeywordResearchPage, KeywordResearchRun


USER_AGENT = 'WisoftCoWorkerKeywordResearch/1.0'
DEFAULT_HTML_READ_LIMIT_BYTES = 2 * 1024 * 1024
DEFAULT_ANTHROPIC_TIMEOUT_SECONDS = 90
DEFAULT_ANTHROPIC_MAX_TOKENS = 1800
KEYWORD_RESEARCH_TOOL_NAME = 'keyword_research_output'
HTML_CONTENT_TYPES = ('text/html', 'application/xhtml+xml')
STOPWORDS = {
    'about', 'above', 'after', 'again', 'against', 'also', 'and', 'are', 'because', 'been',
    'before', 'being', 'below', 'between', 'both', 'but', 'can', 'cannot', 'could', 'did',
    'does', 'doing', 'down', 'during', 'each', 'few', 'for', 'from', 'further', 'had',
    'has', 'have', 'having', 'here', 'how', 'into', 'its', 'itself', 'more', 'most', 'not',
    'now', 'off', 'once', 'only', 'other', 'our', 'out', 'over', 'same', 'should', 'some',
    'such', 'than', 'that', 'the', 'their', 'them', 'then', 'there', 'these', 'they',
    'this', 'those', 'through', 'too', 'under', 'until', 'very', 'was', 'were', 'what',
    'when', 'where', 'which', 'while', 'who', 'why', 'will', 'with', 'you', 'your', 'www',
    'com', 'contact', 'home', 'page', 'read', 'learn', 'more',
}


def get_html_read_limit_bytes():
    try:
        return int(os.environ.get('KEYWORD_RESEARCH_HTML_READ_LIMIT_BYTES', DEFAULT_HTML_READ_LIMIT_BYTES))
    except (TypeError, ValueError):
        return DEFAULT_HTML_READ_LIMIT_BYTES


def get_ai_timeout_seconds():
    try:
        return int(os.environ.get('KEYWORD_RESEARCH_ANTHROPIC_TIMEOUT_SECONDS', DEFAULT_ANTHROPIC_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_ANTHROPIC_TIMEOUT_SECONDS


def get_ai_max_tokens():
    try:
        return int(os.environ.get('KEYWORD_RESEARCH_ANTHROPIC_MAX_TOKENS', DEFAULT_ANTHROPIC_MAX_TOKENS))
    except (TypeError, ValueError):
        return DEFAULT_ANTHROPIC_MAX_TOKENS


class KeywordPageParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ''
        self.meta_description = ''
        self.headings = {'h1': [], 'h2': [], 'h3': []}
        self.links = []
        self.body_parts = []
        self._active_tag = None
        self._buffer = []
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = {name.lower(): (value or '') for name, value in attrs}
        if tag in {'script', 'style', 'noscript', 'svg'}:
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
        if tag == 'a':
            href = attrs_dict.get('href', '').strip()
            if href and not href.lower().startswith(('mailto:', 'tel:', 'javascript:')):
                self.links.append(normalize_url(urljoin(self.base_url, href)))

    def handle_data(self, data):
        if self._ignored_depth:
            return
        if self._active_tag:
            self._buffer.append(data)
        cleaned = normalize_text(data)
        if cleaned:
            self.body_parts.append(cleaned)

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
        elif tag in self.headings and text:
            self.headings[tag].append(text)
        self._active_tag = None
        self._buffer = []


def normalize_text(value):
    return ' '.join((value or '').split())


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


def extract_terms(text, limit=25):
    tokens = [
        token for token in re.findall(r'[a-zA-Z][a-zA-Z0-9-]{2,}', (text or '').lower())
        if token not in STOPWORDS and not token.isdigit()
    ]
    counts = Counter(tokens)
    return [{'term': term, 'count': count} for term, count in counts.most_common(limit)]


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
                'final_url': normalize_url(response.geturl()),
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
            'final_url': normalize_url(exc.url or url),
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


def crawl_site(run):
    root_url = normalize_url(run.project.website_url)
    root_netloc = urlparse(root_url).netloc.lower()
    queue = deque([root_url])
    seen = set()

    while queue and len(seen) < run.max_pages:
        url = normalize_url(queue.popleft())
        if url in seen or not same_site(url, root_netloc):
            continue
        seen.add(url)
        result = fetch_url(url)
        parser = None
        text = ''
        if not result['error_message'] and result['content_type'].lower().startswith(HTML_CONTENT_TYPES):
            parser = KeywordPageParser(result['final_url'])
            parser.feed(result['body'].decode('utf-8', errors='replace'))
            text = normalize_text(' '.join(parser.body_parts))
            for link in parser.links:
                if same_site(link, root_netloc) and link not in seen and len(seen) + len(queue) < run.max_pages:
                    queue.append(link)

        KeywordResearchPage.objects.create(
            run=run,
            url=url,
            title=parser.title[:500] if parser else '',
            meta_description=parser.meta_description if parser else '',
            h1=parser.headings['h1'][:8] if parser else [],
            h2=parser.headings['h2'][:20] if parser else [],
            h3=parser.headings['h3'][:20] if parser else [],
            word_count=len(text.split()),
            top_terms=extract_terms(text),
            content_excerpt=text[:2500],
            error_message=result['error_message'],
            raw_data={
                'status_code': result['status_code'],
                'final_url': result['final_url'],
                'content_type': result['content_type'],
                'load_time_ms': result['load_time_ms'],
                'truncated': result['truncated'],
            },
        )

    run.pages_crawled = run.pages.count()
    run.save(update_fields=['pages_crawled'])


def compact_page(page):
    return {
        'url': page.url,
        'title': page.title,
        'meta_description': page.meta_description[:300],
        'h1': page.h1[:5],
        'h2': page.h2[:12],
        'h3': page.h3[:12],
        'word_count': page.word_count,
        'top_terms': page.top_terms[:15],
        'content_excerpt': page.content_excerpt[:600],
    }


def build_fallback_ai_result(run):
    terms = Counter()
    for page in run.pages.all():
        for item in page.top_terms:
            if item.get('term'):
                terms[item['term']] += item.get('count', 1)
    keywords = []
    location = run.project.target_location
    for term, _count in terms.most_common(12):
        base = term.replace('-', ' ')
        keywords.append({
            'keyword': f'{base} {location}'.strip(),
            'intent': 'Commercial',
            'funnel_stage': 'Middle',
            'priority': 'Medium',
            'suggested_page': run.project.website_url,
            'content_angle': f'Build a location-aware page or section around {base}.',
            'reason': 'Derived from recurring website terms and target location.',
        })
    return {
        'summary': 'Keyword ideas were generated from the crawled website terms and target location. Use these as a starting point, then validate search volume with Keyword Planner when configured.',
        'keyword_ideas': keywords[:12],
        'clusters': [
            {
                'cluster_name': 'Core Service Keywords',
                'intent': 'Commercial',
                'keywords': [item['keyword'] for item in keywords[:8]],
                'recommended_page_type': 'Service landing page',
                'recommended_action': 'Map these keywords to commercial service pages and add supporting FAQs.',
            }
        ],
    }


def build_keyword_tool():
    return {
        'name': KEYWORD_RESEARCH_TOOL_NAME,
        'description': 'Return keyword research ideas and clusters based on website crawl data.',
        'input_schema': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'summary': {'type': 'string', 'maxLength': 1500},
                'keyword_ideas': {
                    'type': 'array',
                    'maxItems': 30,
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'keyword': {'type': 'string', 'maxLength': 255},
                            'intent': {'type': 'string', 'maxLength': 100},
                            'funnel_stage': {'type': 'string', 'maxLength': 100},
                            'priority': {'type': 'string', 'enum': ['High', 'Medium', 'Low']},
                            'suggested_page': {'type': 'string', 'maxLength': 500},
                            'content_angle': {'type': 'string', 'maxLength': 700},
                            'reason': {'type': 'string', 'maxLength': 700},
                        },
                        'required': ['keyword', 'intent', 'funnel_stage', 'priority', 'suggested_page', 'content_angle', 'reason'],
                    },
                },
                'clusters': {
                    'type': 'array',
                    'maxItems': 8,
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'cluster_name': {'type': 'string', 'maxLength': 255},
                            'intent': {'type': 'string', 'maxLength': 100},
                            'keywords': {'type': 'array', 'maxItems': 12, 'items': {'type': 'string', 'maxLength': 255}},
                            'recommended_page_type': {'type': 'string', 'maxLength': 255},
                            'recommended_action': {'type': 'string', 'maxLength': 700},
                        },
                        'required': ['cluster_name', 'intent', 'keywords', 'recommended_page_type', 'recommended_action'],
                    },
                },
            },
            'required': ['summary', 'keyword_ideas', 'clusters'],
        },
    }


def build_ai_prompt(run):
    payload = {
        'website_url': run.project.website_url,
        'target_location': run.project.target_location,
        'language': run.project.language,
        'seed_topic': run.project.seed_topic,
        'notes': run.project.notes,
        'pages': [compact_page(page) for page in run.pages.all()[:30]],
    }
    return (
        'You are an expert SEO keyword strategist. Based only on this crawled website data and user input, '
        'generate keyword ideas, intent details, funnel stage, priority, suggested page mapping, content angle, '
        'and reason. Include local modifiers where the target location matters. Return structured tool output only. '
        'Avoid inventing services that are not supported by the crawl data.\n\n'
        f'{json.dumps(payload, ensure_ascii=True)[:16000]}'
    )


def call_anthropic_keyword_research(run):
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        return None, '', 'ANTHROPIC_API_KEY is not configured.', {}
    model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022').strip()
    prompt = build_ai_prompt(run)
    body = json.dumps({
        'model': model,
        'max_tokens': get_ai_max_tokens(),
        'tools': [build_keyword_tool()],
        'tool_choice': {'type': 'tool', 'name': KEYWORD_RESEARCH_TOOL_NAME},
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
    except Exception as exc:
        return None, model, str(exc), {'prompt_chars': len(prompt)}

    usage = data.get('usage', {}) or {}
    usage['prompt_chars'] = len(prompt)
    for item in data.get('content', []):
        if item.get('type') == 'tool_use' and item.get('name') == KEYWORD_RESEARCH_TOOL_NAME:
            tool_input = item.get('input')
            if isinstance(tool_input, dict):
                return tool_input, model, '', usage
    return None, model, 'Claude returned no structured keyword output.', usage


def save_ai_results(run, result):
    run.ai_summary = result.get('summary', '')
    run.save(update_fields=['ai_summary'])
    for item in result.get('keyword_ideas', []):
        keyword = (item.get('keyword') or '').strip()
        if not keyword:
            continue
        KeywordIdea.objects.create(
            run=run,
            keyword=keyword[:255],
            intent=(item.get('intent') or '')[:100],
            funnel_stage=(item.get('funnel_stage') or '')[:100],
            priority=(item.get('priority') or '')[:20],
            suggested_page=(item.get('suggested_page') or '')[:500],
            content_angle=item.get('content_angle') or '',
            reason=item.get('reason') or '',
        )
    for cluster in result.get('clusters', []):
        if not cluster.get('cluster_name'):
            continue
        KeywordCluster.objects.create(
            run=run,
            cluster_name=cluster.get('cluster_name', '')[:255],
            intent=cluster.get('intent', '')[:100],
            keywords=cluster.get('keywords', []),
            recommended_page_type=cluster.get('recommended_page_type', '')[:255],
            recommended_action=cluster.get('recommended_action', ''),
        )


def get_google_ads_yaml_path():
    configured_path = os.environ.get('GOOGLE_ADS_YAML_PATH', '').strip()
    if configured_path:
        return Path(configured_path)
    return Path(settings.BASE_DIR) / 'google-ads.yaml'


def load_google_ads_client(GoogleAdsClient):
    yaml_path = get_google_ads_yaml_path()
    if yaml_path.exists():
        return GoogleAdsClient.load_from_storage(str(yaml_path)), ''

    old_env_fields = [
        'GOOGLE_ADS_DEVELOPER_TOKEN',
        'GOOGLE_ADS_CLIENT_ID',
        'GOOGLE_ADS_CLIENT_SECRET',
        'GOOGLE_ADS_REFRESH_TOKEN',
    ]
    missing = [name for name in old_env_fields if not os.environ.get(name, '').strip()]
    if missing:
        return None, (
            'Google Ads is not configured. Add google-ads.yaml in the project root, '
            'or set GOOGLE_ADS_YAML_PATH to its location. GOOGLE_ADS_CUSTOMER_ID is also required.'
        )

    config = {
        'developer_token': os.environ['GOOGLE_ADS_DEVELOPER_TOKEN'].strip(),
        'client_id': os.environ['GOOGLE_ADS_CLIENT_ID'].strip(),
        'client_secret': os.environ['GOOGLE_ADS_CLIENT_SECRET'].strip(),
        'refresh_token': os.environ['GOOGLE_ADS_REFRESH_TOKEN'].strip(),
        'use_proto_plus': True,
    }
    login_customer_id = os.environ.get('GOOGLE_ADS_LOGIN_CUSTOMER_ID', '').strip().replace('-', '')
    if login_customer_id:
        config['login_customer_id'] = login_customer_id
    return GoogleAdsClient.load_from_dict(config), ''


def run_google_keyword_planner(run):
    customer_id = os.environ.get('GOOGLE_ADS_CUSTOMER_ID', '').strip().replace('-', '')
    if not customer_id:
        run.planner_status = 'not_configured'
        run.planner_error = 'Missing GOOGLE_ADS_CUSTOMER_ID. This is the Google Ads account id used for Keyword Planner.'
        run.save(update_fields=['planner_status', 'planner_error'])
        return
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except Exception:
        run.planner_status = 'library_missing'
        run.planner_error = 'google-ads package is not installed. Install google-ads and configure credentials to enable Keyword Planner metrics.'
        run.save(update_fields=['planner_status', 'planner_error'])
        return

    try:
        client, client_error = load_google_ads_client(GoogleAdsClient)
    except Exception as exc:
        client, client_error = None, str(exc)
    if client_error:
        run.planner_status = 'not_configured'
        run.planner_error = client_error
        run.save(update_fields=['planner_status', 'planner_error'])
        return

    keywords = list(
        run.keyword_ideas.exclude(keyword='').values_list('keyword', flat=True).distinct()[:20]
    )
    if not keywords:
        run.planner_status = 'skipped'
        run.planner_error = 'No AI keyword ideas were available to validate in Keyword Planner.'
        run.save(update_fields=['planner_status', 'planner_error'])
        return

    language_id = os.environ.get('GOOGLE_ADS_LANGUAGE_ID', '1000').strip()
    location_id = os.environ.get('GOOGLE_ADS_LOCATION_ID', '').strip()
    try:
        keyword_plan_idea_service = client.get_service('KeywordPlanIdeaService')
        googleads_service = client.get_service('GoogleAdsService')
        request = client.get_type('GenerateKeywordIdeasRequest')
        request.customer_id = customer_id
        if language_id:
            request.language = googleads_service.language_constant_path(language_id)
        if location_id:
            request.geo_target_constants.append(googleads_service.geo_target_constant_path(location_id))
        request.include_adult_keywords = False
        request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH_AND_PARTNERS
        request.keyword_seed.keywords.extend(keywords)
        response = keyword_plan_idea_service.generate_keyword_ideas(request=request)
    except Exception as exc:
        run.planner_status = 'failed'
        run.planner_error = str(exc)
        run.save(update_fields=['planner_status', 'planner_error'])
        return

    KeywordPlannerMetric.objects.filter(run=run, source='google_keyword_planner').delete()
    for idea in response:
        metrics = idea.keyword_idea_metrics
        low_bid = metrics.low_top_of_page_bid_micros / 1000000 if metrics.low_top_of_page_bid_micros else None
        high_bid = metrics.high_top_of_page_bid_micros / 1000000 if metrics.high_top_of_page_bid_micros else None
        KeywordPlannerMetric.objects.create(
            run=run,
            keyword=idea.text[:255],
            avg_monthly_searches=metrics.avg_monthly_searches or None,
            competition=str(metrics.competition.name) if metrics.competition else '',
            competition_index=metrics.competition_index or None,
            low_top_of_page_bid=low_bid,
            high_top_of_page_bid=high_bid,
            currency_code=os.environ.get('GOOGLE_ADS_CURRENCY_CODE', '').strip(),
            source='google_keyword_planner',
            raw_data={
                'source_keywords': keywords,
                'location_id': location_id,
                'language_id': language_id,
            },
        )
    run.planner_status = 'completed'
    run.planner_error = ''
    run.save(update_fields=['planner_status', 'planner_error'])


def save_placeholder_planner_rows(run):
    if run.planner_metrics.exists():
        return
    for idea in run.keyword_ideas.all()[:30]:
        KeywordPlannerMetric.objects.create(
            run=run,
            keyword=idea.keyword,
            source='google_keyword_planner',
            raw_data={'status': run.planner_status, 'message': run.planner_error},
        )


def run_keyword_research(run):
    try:
        crawl_site(run)
        fallback = build_fallback_ai_result(run)
        ai_result, model, ai_error, usage = call_anthropic_keyword_research(run)
        result = ai_result or fallback
        save_ai_results(run, result)
        run.ai_model = model
        run.ai_error = ai_error
        run.ai_prompt_chars = usage.get('prompt_chars', 0)
        run.ai_input_tokens = usage.get('input_tokens') or 0
        run.ai_output_tokens = usage.get('output_tokens') or 0
        run.ai_total_tokens = run.ai_input_tokens + run.ai_output_tokens
        run.save(update_fields=['ai_model', 'ai_error', 'ai_prompt_chars', 'ai_input_tokens', 'ai_output_tokens', 'ai_total_tokens'])
        run_google_keyword_planner(run)
        save_placeholder_planner_rows(run)
        run.status = KeywordResearchRun.STATUS_COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'completed_at'])
    except Exception as exc:
        run.status = KeywordResearchRun.STATUS_FAILED
        run.error_message = str(exc)
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'error_message', 'completed_at'])
        raise
