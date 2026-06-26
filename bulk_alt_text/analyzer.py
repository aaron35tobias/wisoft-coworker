from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen
import os
import re


BULK_ALT_TEXT_TIMEOUT = 20


class PageImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts = []
        self.capture_title = False
        self.images = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag.lower() == 'title':
            self.capture_title = True

        if tag.lower() == 'img':
            self.images.append({
                'src': attrs.get('src', '').strip(),
                'alt': attrs.get('alt', '').strip(),
                'width': attrs.get('width', '').strip(),
                'height': attrs.get('height', '').strip(),
                'class': attrs.get('class', '').strip(),
            })

    def handle_endtag(self, tag):
        if tag.lower() == 'title':
            self.capture_title = False

    def handle_data(self, data):
        if self.capture_title:
            self.title_parts.append(data.strip())

    @property
    def page_title(self):
        return ' '.join(part for part in self.title_parts if part).strip()


def normalize_page_url(page_url):
    page_url = page_url.strip()
    if not urlparse(page_url).scheme:
        page_url = f'https://{page_url}'
    return page_url


def clean_words(value):
    value = unquote(value or '')
    value = os.path.splitext(value)[0]
    value = re.sub(r'[_\-]+', ' ', value)
    value = re.sub(r'\b\d{2,}\b', ' ', value)
    value = re.sub(r'[^a-zA-Z0-9 ]+', ' ', value)
    value = re.sub(r'\s+', ' ', value).strip()
    return value


def build_alt_text(image_url, page_title):
    parsed_url = urlparse(image_url)
    filename_words = clean_words(os.path.basename(parsed_url.path))
    title_words = clean_words(page_title)

    if filename_words:
        alt_text = filename_words
    elif title_words:
        alt_text = title_words
    else:
        alt_text = 'Website image'

    if title_words and title_words.lower() not in alt_text.lower():
        alt_text = f'{alt_text} - {title_words}'

    return alt_text[:155]


def run_bulk_alt_text_analysis(analysis):
    page_url = normalize_page_url(analysis.page_url)
    request = Request(page_url, headers={'User-Agent': 'WisoftCoWorkerBot/1.0'})

    with urlopen(request, timeout=BULK_ALT_TEXT_TIMEOUT) as response:
        html_content = response.read().decode('utf-8', errors='ignore')

    parser = PageImageParser()
    parser.feed(html_content)

    page_title = parser.page_title
    images = []

    for index, image in enumerate(parser.images, start=1):
        src = image.get('src', '')
        if not src or src.startswith(('data:', 'blob:')):
            continue

        image_url = urljoin(page_url, src)
        current_alt_text = image.get('alt', '').strip()
        suggested_alt_text = current_alt_text or build_alt_text(image_url, page_title)

        images.append({
            'index': index,
            'image_url': image_url,
            'current_alt_text': current_alt_text,
            'suggested_alt_text': suggested_alt_text,
            'has_alt_text': bool(current_alt_text),
            'width': image.get('width', ''),
            'height': image.get('height', ''),
            'class': image.get('class', ''),
        })

    analysis.page_url = page_url
    analysis.page_title = page_title
    analysis.images_json = images
    analysis.total_images = len(images)
    analysis.missing_alt_count = len([image for image in images if not image['has_alt_text']])
    analysis.generated_alt_count = len([image for image in images if image['suggested_alt_text']])
    return analysis
