from urllib.parse import urlparse


def normalize_url(value):
    """Return a URL with a scheme, prepending ``https://`` to bare input.

    Accepts bare domains like ``example.com`` or ``example.com/page`` (as
    typed into the SEO forms) and returns ``https://example.com`` /
    ``https://example.com/page``. Values that already have a scheme are left
    untouched, and empty input is returned as an empty string so optional
    fields stay optional.
    """
    value = (value or '').strip()
    if value and not urlparse(value).scheme:
        value = f'https://{value}'
    return value
