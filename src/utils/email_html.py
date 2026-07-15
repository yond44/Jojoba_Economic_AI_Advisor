import re
import html as html_lib
from datetime import datetime
from typing import Optional

# Bump this whenever the file changes — lets you confirm in production
# (via `python3 -c "import email_html; print(email_html.__version__)"`)
# that the server is actually running this version and not a stale copy.
__version__ = "2026-07-15.3-bold-fix"

try:
    import markdown as _markdown_lib
    _MARKDOWN_AVAILABLE = True
except ImportError:
    _MARKDOWN_AVAILABLE = False


def markdown_to_html(text: str) -> str:
    """
    Convert (possibly slightly malformed) Markdown into HTML suitable for
    embedding in the email template.

    The AI agent's raw answer text sometimes arrives with a specific defect:
    a closing "**" bold marker gets split across a line break into a
    lone "*" + newline + "*" (e.g. "**bold text*\\n*  \\n"). A normal
    Markdown parser treats those as two separate, unmatched italic markers,
    which produces garbled output. We repair that pattern before parsing.

    Args:
        text: Raw markdown/plain text from the AI agent

    Returns:
        Sanitized HTML string (safe to insert into the email template)
    """
    if not text:
        return ""

    text = str(text)

    # Normalize line endings FIRST. If the raw text arrives with CRLF
    # (\r\n) — common when it's passed through certain DB drivers, Windows
    # -originated tooling, or some HTTP/JSON round-trips — the repair
    # regexes below (which look for a literal \n) would silently fail to
    # match, leaving the split "*\r\n*" marker broken and unfixed.
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # Escape any literal HTML so the answer can't inject markup/scripts,
    # while leaving markdown syntax characters (*, -, #, etc.) untouched.
    text = html_lib.escape(text, quote=False)

    # Repair a closing "**" that got split across a line break into
    # "*\n*" (with optional stray whitespace around the newline).
    # FIX: Changed replacement from '**\n' to '**' so the bold marker
    # is restored without an extra newline that breaks the markdown parser.
    text = re.sub(r'\*[ \t]*\n[ \t]*\*(?!\*)', '**', text)

    # Collapse 3+ consecutive asterisks down to a plain "**" bold marker,
    # since stray extra asterisks are a common artifact of the same bug.
    text = re.sub(r'\*{3,}', '**', text)

    # A single leading "*" immediately followed by non-whitespace (and not
    # part of a "**" pair) is very likely an orphaned bold marker left over
    # from the same split-marker bug — drop it rather than render italics.
    text = re.sub(r'^\*(?!\*)(?=\S)', '', text)

    if not _MARKDOWN_AVAILABLE:
        # Fallback: no markdown library installed, just preserve line
        # breaks so the text isn't a single unreadable blob.
        return "<p>" + text.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"

    return _markdown_lib.markdown(
        text,
        extensions=["tables", "sane_lists", "nl2br"]
    )


def _add_drop_cap(content_html: str) -> str:
    """
    Wrap the first real character of the first paragraph in a span so it
    can be styled as a large drop cap, skipping over any leading inline
    tags (e.g. if the answer opens with **bold** text).
    """
    p_match = re.search(r'<p[^>]*>', content_html)
    if not p_match:
        return content_html

    i = p_match.end()
    n = len(content_html)

    while i < n and content_html[i] == '<':
        end_tag = content_html.find('>', i)
        if end_tag == -1:
            return content_html
        i = end_tag + 1

    if i >= n or content_html[i] == '<':
        return content_html

    first_char = content_html[i]
    if not first_char.isalnum():
        return content_html

    return (
        content_html[:i]
        + f'<span class="dropcap">{first_char}</span>'
        + content_html[i + 1:]
    )


def generate_economic_news_email(
    question: str,
    answer: str,
    processing_time: float = 0,
    iterations: int = 0,
    queue_remaining: int = 0,
    next_question: Optional[str] = None,
    email_count: int = 0,
    sources_count: int = 0,
    subtitle: Optional[str] = None
) -> str:
    """
    Generate an editorial, newspaper-style HTML email for Jojoba Economic
    News — masthead, byline, drop cap, and section headers.

    Args:
        question: The economic question asked
        answer: The AI-generated answer/analysis (markdown supported)
        processing_time: Time taken to process (seconds)
        iterations: Number of iterations used
        queue_remaining: Questions left in queue
        next_question: The next question in queue
        email_count: Number of recipients this email is sent to
        sources_count: Number of sources consulted for the analysis
        subtitle: Optional override for the italic dek/subtitle line

    Returns:
        HTML string for email body
    """

    now = datetime.now()
    date_line = now.strftime('%A, %d %B %Y').upper()
    time_line = now.strftime('%H:%M') + ' WIB'

    question_safe = html_lib.escape(str(question), quote=False)
    answer_html = markdown_to_html(answer)
    answer_html = _add_drop_cap(answer_html)

    dek = subtitle or (
        "An AI-assisted analysis prepared in response to a reader's inquiry, "
        "drawing on current economic data, sector indicators, and contextual "
        "market intelligence."
    )

    if next_question:
        next_display = next_question if len(next_question) <= 60 else next_question[:60] + '...'
    else:
        next_display = None

    next_up_html = (
        f'<div class="next-up">⏭️ <strong>Coming up next:</strong> {html_lib.escape(next_display, quote=False)} '
        f'&nbsp;&bull;&nbsp; {queue_remaining} remaining in queue</div>'
        if next_display else ''
    )

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Jojoba Economic Review - {question_safe}</title>
<style>
    body {{
        font-family: Georgia, 'Times New Roman', Times, serif;
        background: #e9e3d3;
        margin: 0;
        padding: 0;
        color: #1a1a1a;
    }}
    .container {{
        max-width: 640px;
        margin: 0 auto;
        background: #fdfbf5;
    }}
    .masthead {{
        text-align: center;
        padding: 26px 25px 18px 25px;
        background: #fdfbf5;
    }}
    .masthead h1 {{
        margin: 0;
        font-size: 34px;
        font-weight: 700;
        color: #14110c;
        line-height: 1.15;
        letter-spacing: 0.2px;
    }}
    .masthead h1 .accent {{
        font-style: italic;
        font-weight: 700;
        color: #a9781f;
    }}
    .masthead .tagline {{
        margin-top: 6px;
        font-style: italic;
        font-size: 13px;
        color: #6b6455;
        letter-spacing: 0.3px;
    }}
    .datebar {{
        background: #14110c;
        color: #ffffff;
        font-family: Georgia, 'Times New Roman', Times, serif;
    }}
    .datebar td {{
        padding: 10px 25px;
        font-size: 11px;
        letter-spacing: 0.8px;
    }}
    .datebar .edition {{
        color: #d8af3f;
        text-align: center;
        font-weight: 700;
    }}
    .datebar .right {{
        text-align: right;
    }}
    .content {{
        padding: 26px 30px 10px 30px;
    }}
    .eyebrow {{
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
        color: #a9781f;
        border-bottom: 1px solid #e2dbc8;
        padding-bottom: 10px;
        margin-bottom: 14px;
    }}
    .headline {{
        font-size: 26px;
        font-weight: 700;
        color: #14110c;
        line-height: 1.25;
        margin: 0 0 10px 0;
    }}
    .dek {{
        font-style: italic;
        font-size: 14px;
        color: #55503f;
        line-height: 1.55;
        margin: 0 0 16px 0;
    }}
    .byline {{
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.4px;
        text-transform: uppercase;
        color: #6b6455;
        border-top: 1px solid #e2dbc8;
        border-bottom: 1px solid #e2dbc8;
        padding: 10px 0;
        margin-bottom: 22px;
    }}
    .byline .sep {{
        color: #c9bfa4;
        margin: 0 6px;
        font-weight: 400;
    }}
    .article-body {{
        font-size: 16px;
        line-height: 1.75;
        color: #201c14;
    }}
    .article-body p {{
        margin: 0 0 16px 0;
    }}
    .article-body p:last-child {{
        margin-bottom: 0;
    }}
    .article-body .dropcap {{
        float: left;
        font-family: Georgia, 'Times New Roman', Times, serif;
        font-weight: 700;
        font-size: 54px;
        line-height: 0.85;
        color: #a9781f;
        padding: 4px 6px 0 0;
    }}
    .article-body h1,
    .article-body h2,
    .article-body h3 {{
        font-size: 19px;
        font-weight: 700;
        color: #a9781f;
        border-top: 1px solid #e2dbc8;
        margin: 26px 0 12px 0;
        padding-top: 16px;
    }}
    .article-body strong {{
        color: #14110c;
    }}
    .article-body ul,
    .article-body ol {{
        margin: 0 0 16px 0;
        padding-left: 4px;
        list-style: none;
    }}
    .article-body li {{
        margin: 0 0 10px 0;
        padding-left: 16px;
        position: relative;
    }}
    .article-body li::before {{
        content: "\\2022";
        color: #a9781f;
        position: absolute;
        left: 0;
    }}
    .article-body ol {{
        counter-reset: item;
    }}
    .article-body ol li::before {{
        content: counter(item) ".";
        counter-increment: item;
        color: #a9781f;
        font-weight: 700;
    }}
    .article-body table {{
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0 18px 0;
        font-size: 14px;
    }}
    .article-body table th,
    .article-body table td {{
        border: 1px solid #e2dbc8;
        padding: 8px 12px;
        text-align: left;
    }}
    .article-body table th {{
        background: #f4efe0;
        font-weight: 700;
        color: #14110c;
    }}
    .next-up {{
        clear: both;
        margin-top: 20px;
        padding: 12px 16px;
        background: #f4efe0;
        border-left: 3px solid #a9781f;
        font-size: 13px;
        color: #4a4534;
    }}
    .footer {{
        clear: both;
        padding: 18px 30px 24px 30px;
        border-top: 1px solid #e2dbc8;
        font-size: 11px;
        color: #8a8371;
        text-align: center;
        letter-spacing: 0.2px;
    }}
    .footer .disclaimer {{
        color: #a13a2f;
        font-weight: 700;
    }}

    @media only screen and (max-width: 480px) {{
        .masthead {{ padding: 20px 18px 14px 18px; }}
        .masthead h1 {{ font-size: 26px; }}
        .content {{ padding: 20px 18px 6px 18px; }}
        .headline {{ font-size: 21px; }}
        .article-body {{ font-size: 15px; }}
        .article-body .dropcap {{ font-size: 44px; }}
        .footer {{ padding: 16px 18px 20px 18px; }}
    }}
</style>
</head>
<body>
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#e9e3d3">
    <tr><td align="center" style="padding: 20px 0;">
        <div class="container">
            <div class="masthead">
                <h1>The Jojoba <span class="accent">Economic</span><br>Review</h1>
                <div class="tagline">&mdash; Intelligence for the Discerning Investor &mdash;</div>
            </div>
            <table width="100%" cellpadding="0" cellspacing="0" border="0" class="datebar">
                <tr>
                    <td>{date_line}</td>
                    <td class="edition">&#9733; AI EDITION &#9733;</td>
                    <td class="right">{time_line}</td>
                </tr>
            </table>
            <div class="content">
                <div class="eyebrow">Reader Inquiry &bull; Economic Intelligence</div>
                <div class="headline">{question_safe}</div>
                <div class="dek">{html_lib.escape(dek, quote=False)}</div>
                <div class="byline">
                    BY JOJOBA AI DESK
                    <span class="sep">|</span> FILED {time_line}
                    <span class="sep">|</span> {processing_time:.2f}s ANALYSIS
                    <span class="sep">|</span> {sources_count} SOURCES CONSULTED
                </div>
                <div class="article-body">{answer_html}</div>
                {next_up_html}
            </div>
            <div class="footer">
                <span class="disclaimer">&#9888; Not financial advice</span> &bull; For educational purposes only
                <br>Generated by Jojoba Economic Advisor AI
                <br>Sent to {email_count} recipient{'s' if email_count != 1 else ''}
            </div>
        </div>
    </td></tr>
</table>
</body>
</html>
    """

    return html_body


def generate_simple_email(
    question: str,
    answer: str,
    recipient_count: int = 0
) -> str:
    """
    Generate a simpler email template (fallback, no styling dependencies).

    Args:
        question: The economic question asked
        answer: The AI-generated answer/analysis (markdown supported)
        recipient_count: Number of recipients

    Returns:
        HTML string for email body
    """

    question_safe = html_lib.escape(str(question), quote=False)
    answer_html = markdown_to_html(answer)

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jojoba Economic News</title>
<style>
    body {{ font-family: Georgia, 'Times New Roman', Times, serif; background: #e9e3d3; margin: 0; padding: 20px; color: #1a1a1a; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #fdfbf5; border-radius: 4px; padding: 25px; }}
    .header {{ border-bottom: 2px solid #a9781f; padding-bottom: 15px; margin-bottom: 20px; }}
    .header h1 {{ margin: 0; color: #14110c; font-size: 22px; }}
    .header h1 span {{ font-style: italic; color: #a9781f; }}
    .header .date {{ color: #8a8371; font-size: 12px; }}
    .question {{ background: #f4efe0; padding: 12px 16px; border-radius: 4px; margin-bottom: 20px; border-left: 3px solid #a9781f; }}
    .question .label {{ font-size: 10px; text-transform: uppercase; color: #a9781f; font-weight: 700; }}
    .question .text {{ font-size: 15px; font-weight: 500; margin: 4px 0 0 0; }}
    .answer {{ font-size: 15px; line-height: 1.7; }}
    .answer p {{ margin: 0 0 12px 0; }}
    .answer p:last-child {{ margin-bottom: 0; }}
    .answer ul, .answer ol {{ margin: 8px 0; padding-left: 20px; }}
    .answer li {{ margin: 4px 0; }}
    .answer strong {{ color: #14110c; }}
    .footer {{ margin-top: 20px; padding-top: 15px; border-top: 1px solid #e2dbc8; font-size: 11px; color: #8a8371; }}
    .footer .disclaimer {{ color: #a13a2f; font-weight: 700; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>The Jojoba <span>Economic Review</span></h1>
        <div class="date">{datetime.now().strftime('%d %b %Y')} &bull; {datetime.now().strftime('%H:%M')}</div>
    </div>

    <div class="question">
        <div class="label">Question</div>
        <div class="text">{question_safe}</div>
    </div>

    <div class="answer">{answer_html}</div>

    <div class="footer">
        <span class="disclaimer">&#9888; Not financial advice</span> &bull; For educational purposes only
        <br>Generated by Jojoba Economic Advisor AI
        {f'<br>Sent to {recipient_count} recipients' if recipient_count > 0 else ''}
    </div>
</div>
</body>
</html>
    """

    return html_body