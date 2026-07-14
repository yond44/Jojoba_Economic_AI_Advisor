"""Email-safe Markdown -> newspaper HTML rendering (escape-first, FIX #10)."""
import html
import re
from typing import List


def _esc(text: str) -> str:
    """HTML-escape untrusted text before putting it in the email template."""
    return html.escape(str(text), quote=True)

_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

def _md_inline(escaped: str) -> str:
    """Inline Markdown on already-escaped text: **bold** -> <strong>."""
    return _MD_BOLD_RE.sub(r'<strong style="color:#1a1a1a;">\1</strong>', escaped)

_P_STYLE = ("margin:0 0 14px 0;font-family:Georgia,'Times New Roman',serif;"
            "font-size:16px;line-height:1.75;color:#1a1a1a;")

_H_STYLE = ("margin:22px 0 10px 0;font-family:Georgia,'Times New Roman',serif;"
            "font-size:19px;font-weight:700;color:#8b6914;"
            "border-bottom:1px solid #e0d8c0;padding-bottom:4px;")

_DROP_SPAN = ('<span style="font-family:Georgia,serif;font-size:52px;font-weight:700;'
              'float:left;line-height:0.9;margin:6px 8px 0 0;color:#8b6914;">{ch}</span>')

def _apply_drop_cap(inner_html: str) -> str:
    """Wrap the first VISIBLE character in a drop cap without splitting any
    leading HTML tag (e.g. a paragraph that starts with <strong>)."""
    m = re.match(r"((?:<[^>]+>)*)(&[a-zA-Z0-9#]+;|.)(.*)", inner_html, re.S)
    if not m:
        return inner_html
    lead_tags, first_ch, rest = m.group(1), m.group(2), m.group(3)
    return f"{lead_tags}{_DROP_SPAN.format(ch=first_ch)}{rest}"

def _render_article_html(answer: str) -> str:
    """Render a Markdown answer into email-safe newspaper HTML.

    Line-oriented so headings, bullet lists, and paragraphs are detected even
    when the model doesn't separate them with blank lines. Escaping happens per
    line BEFORE Markdown translation (preserves FIX #10). Drop cap on the first
    body paragraph.
    """
    parts: List[str] = []
    para_buf: List[str] = []
    bullet_buf: List[str] = []
    drop_used = {"v": False}

    def flush_para():
        if not para_buf:
            return
        inner = _md_inline(_esc("\n".join(para_buf)).replace("\n", "<br/>"))
        para_buf.clear()
        if not drop_used["v"] and inner:
            drop_used["v"] = True
            inner = _apply_drop_cap(inner)
        parts.append(f'<p style="{_P_STYLE}">{inner}</p>')

    def flush_bullets():
        if not bullet_buf:
            return
        items = "".join(
            f'<tr><td style="vertical-align:top;padding:0 8px 6px 0;color:#8b6914;'
            f'font-family:Georgia,serif;">&bull;</td>'
            f'<td style="padding:0 0 6px 0;font-family:Georgia,serif;font-size:16px;'
            f'line-height:1.7;color:#1a1a1a;">{_md_inline(_esc(b))}</td></tr>'
            for b in bullet_buf)
        bullet_buf.clear()
        parts.append('<table role="presentation" cellpadding="0" cellspacing="0" '
                     'border="0" style="margin:0 0 14px 0;">' + items + "</table>")

    for raw in (answer or "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush_bullets(); flush_para(); continue
        if re.match(r"^#{2,4}\s+", line):
            flush_bullets(); flush_para()
            text = _md_inline(_esc(re.sub(r"^#{2,4}\s+", "", line)))
            parts.append(f'<p style="{_H_STYLE}">{text}</p>')
            continue
        if re.match(r"^[-*]\s+", line):
            flush_para()
            bullet_buf.append(re.sub(r"^[-*]\s+", "", line))
            continue
        flush_bullets()
        para_buf.append(line)

    flush_bullets(); flush_para()
    return "\n".join(parts) if parts else f'<p style="{_P_STYLE}">{_md_inline(_esc(answer or ""))}</p>'
