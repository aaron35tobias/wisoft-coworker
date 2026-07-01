# SEO AI Workflows

This document explains how the platform currently handles Technical SEO Audits and Content Gap Analysis, where AI is used, what data is sent to AI providers, and how to estimate usage cost.

## Shared AI Configuration

Both modules read AI configuration from `.env`.

```env
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6
CONTENT_GAP_ANTHROPIC_TIMEOUT_SECONDS=120
CONTENT_GAP_ANTHROPIC_MAX_TOKENS=1600
```

Technical SEO also supports OpenAI as a fallback if these variables are configured:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1
```

Do not commit real API keys. Keep production keys in environment configuration only.

## Technical SEO Audit

### User Flow

1. User opens `Technical SEO Audit > Run Audit`.
2. User enters:
   - Website URL
   - Optional note
   - Max pages to crawl
3. The platform creates a `TechnicalSEOAudit`.
4. The crawler scans internal pages up to the max page limit.
5. Deterministic rules identify SEO issues.
6. AI receives the structured audit results and writes a client-ready summary.
7. Results are saved and displayed in the audit detail screen.

### Crawl Workflow

The crawl starts from the submitted website URL.

For each internal page, the platform records:

- HTTP status code
- Final URL after redirects
- Content type
- Title tag
- Meta description
- Canonical URL
- Robots meta directives
- H1 count and H1 text
- H2 count
- Internal and external link counts
- Image count
- Missing image alt count
- Page depth
- Fetch time
- Crawl error message, if any

The crawler respects `robots.txt` when available.

### Deterministic SEO Checks

The platform identifies issues before AI is used. Current checks include:

- Server errors
- 404 pages
- Redirecting URLs
- Crawl failures
- Pages blocked by robots.txt
- HTML too large to fully parse
- Missing or long title tags
- Missing or long meta descriptions
- Missing or multiple H1 headings
- Noindex directives
- Missing canonical tags
- Canonical mismatch
- Images missing alt text
- Slow page response
- Duplicate title tags
- Duplicate meta descriptions

Each issue stores:

- Severity
- Issue type
- Title
- Evidence
- Corrective recommendation
- Related page

### Where AI Comes In

AI is used after the deterministic crawl and issue detection are complete.

The system sends Claude a structured payload containing:

- Website URL
- Pages crawled
- Total issue count
- Severity counts
- Up to 80 issue records
- For each issue:
  - Page URL
  - Severity
  - Issue type
  - Issue title
  - Evidence
  - Deterministic recommendation

AI does not crawl the site. It summarizes and prioritizes the audit findings already detected by the platform.

### Technical SEO AI Output

AI produces a concise consultant-style summary with:

- Executive summary
- Top priorities
- Corrective actions
- Developer notes

If Claude fails, the module tries OpenAI if configured. If no AI provider works, the system uses a deterministic fallback summary.

### Technical SEO Cost Behavior

Technical SEO usually has lower AI usage than Content Gap because it sends structured issue data, not page body content.

Approximate usage depends on how many issues exist:

- Small audit: around 1,000 to 2,500 input tokens
- Larger audit with many issues: around 3,000 to 6,000 input tokens
- Output is capped at about 1,200 tokens

Current Technical SEO does not yet save exact provider token usage in the database. Cost should be estimated from prompt size and provider dashboard usage.

## Content Gap Analysis

### User Flow

1. User opens `Content Gaps > Gap Analysis`.
2. User enters:
   - Own page URL
   - Optional target topic
   - Optional target market
   - One to three competitor URLs
   - Optional notes
3. The platform creates a `ContentGapProject`.
4. The platform creates a `ContentGapAnalysis`.
5. The system fetches the own page and competitor pages.
6. The system extracts page-level content signals.
7. Deterministic comparison generates baseline recommendations.
8. Claude receives a compact structured prompt.
9. Claude returns structured results through tool output.
10. The platform saves the result and displays it in the detail screen.

### Page Extraction Workflow

For each URL, the platform extracts:

- URL
- Status code
- Final URL
- Content type
- Load time
- Title tag
- Meta description
- H1 headings
- H2 headings
- H3 headings
- Word count
- Top terms
- Short body excerpt
- Fetch or parsing error message

The platform does not send full HTML to Claude. It parses the page first and sends a compact page snapshot.

### Deterministic Comparison

Before AI is used, the system compares the own page against competitor snapshots.

It identifies:

- Competitor terms not present strongly on the own page
- Competitor headings not covered by the own page
- Potential missing sections
- Keyword opportunities
- A baseline execution plan
- A baseline wireframe

This means the feature still produces useful recommendations if AI is unavailable or returns an invalid response.

### Where AI Comes In

Claude receives a compact prompt containing:

- Target topic
- Target market
- User notes
- Compact own-page snapshot
- Compact competitor snapshots
- Baseline recommendations generated by the platform

Each compact page snapshot includes:

- URL
- Status code
- Title
- Meta description, capped
- H1 samples
- H2 samples
- H3 samples
- Word count
- Top terms
- Short body excerpt, capped
- Error message, if any

Claude is asked to return structured tool output, not free-form JSON text. This reduces malformed JSON errors and makes the result easier to save safely.

### Content Gap AI Output

The saved AI/fallback result includes:

- AI Summary
- Content gaps
- Keyword opportunities
- Recommended sections
- Execution plan
- Page wireframe

The Page Snapshots section is not AI output. It is extracted crawl data used to support the analysis.

### Content Gap Cost Behavior

Content Gap can use more tokens than Technical SEO because it sends summaries of multiple pages.

Current safeguards:

- Prompt is capped at about 9,000 characters
- Body excerpt per page is capped
- H2/H3 and top terms are capped
- Claude output is capped by `CONTENT_GAP_ANTHROPIC_MAX_TOKENS`
- Current configured output cap is `1600`

Approximate normal usage:

- Input: around 2,000 to 3,000 tokens
- Output: up to 1,600 tokens
- Total: usually around 3,000 to 4,600 tokens

The exact usage is saved on each `ContentGapAnalysis` record:

- AI prompt size in characters
- Input tokens
- Output tokens
- Total tokens

These values are shown in the Content Gap detail page.

### Handling AI Failures

If Claude times out, fails, or returns malformed data:

1. The platform keeps the deterministic fallback recommendations.
2. The detail page shows a clean AI note.
3. The raw malformed AI response is not shown to users.
4. The analysis still completes unless the crawl or save process fails.

## Cost Formula

AI providers generally price by input and output tokens.

Use this formula:

```text
estimated_cost =
  (input_tokens / 1,000,000 * input_price_per_million)
  +
  (output_tokens / 1,000,000 * output_price_per_million)
```

Example:

```text
input_tokens = 3,000
output_tokens = 1,000

estimated_cost =
  (3,000 / 1,000,000 * input_price_per_million)
  +
  (1,000 / 1,000,000 * output_price_per_million)
```

Use the current Anthropic pricing page or provider dashboard for the exact per-million token prices, because model pricing can change.

## Data Privacy Notes

Data sent to AI providers is limited to what is needed for the recommendation.

Technical SEO sends:

- URLs
- Issue evidence
- Deterministic recommendations
- Severity and issue metadata

Content Gap sends:

- URLs
- Titles and meta descriptions
- Heading samples
- Top extracted terms
- Short page text excerpts
- User-entered topic, market, and notes

The platform does not intentionally send:

- Raw full HTML
- Database credentials
- API keys
- User passwords

## Improvement Ideas

Recommended next improvements:

1. Save exact token usage for Technical SEO as well.
2. Add a per-run estimated cost field using configured model pricing.
3. Move long-running audits to a background job queue.
4. Add retry buttons for failed AI-only summaries.
5. Add export to PDF for client-ready audit and content gap reports.
