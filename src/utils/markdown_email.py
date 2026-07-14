"""
Renders the agent's markdown answer into inline-styled HTML for the
Jojoba Economic Review newspaper email template.

Why this exists: n8n's `{{ $json.response }}` expression does plain string
interpolation. It does not parse markdown, and raw newlines get collapsed by
HTML whitespace rules once dropped inside a single <p>. The result is a wall
of text with literal ** and ## characters (see: scheduled-briefing emails).
This module does the markdown -> HTML conversion server-side, once, so every
consumer (the n8n template, a future non-n8n send path, etc.) gets the same
polished output the reader-inquiry emails already have.

Handles: **bold**, *italic*, "# / ## / ###" headers, "- " / "* " bullet
lists, "1. " numbered lists, and paragraph breaks. The lead (first)
paragraph gets the newspaper drop-cap + bold treatment.
"""
from __future__ import annotations

import html
import re

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\d+[.)]\s+(.*)$")

_BROKEN_BOLD_CLOSER_RE = re.compile(r"(?<!\*)\*(\s+)\*(?!\*)")

_LONE_HEADER_MARKER_RE = re.compile(r"^(#{1,6})$")

_INK = "#1a1a1a"
_GOLD = "#8b6914"
_MUTED = "#4a4233"
_SERIF = "Georgia,'Times New Roman',serif"

_P_STYLE = (
    f"margin:0 0 14px 0;font-family:{_SERIF};font-size:16px;"
    f"line-height:1.75;color:{_INK};"
)
_LEAD_P_STYLE = _P_STYLE + "font-weight:700;"
_HEADER_STYLE = (
    f"margin:22px 0 10px 0;padding-bottom:6px;border-bottom:2px solid {_GOLD};"
    f"font-family:{_SERIF};font-size:20px;font-weight:700;color:{_GOLD};"
    f"letter-spacing:0.2px;"
)
_LIST_STYLE = (
    f"margin:0 0 14px 0;padding-left:22px;font-family:{_SERIF};"
    f"font-size:16px;line-height:1.6;color:{_INK};"
)
_LI_STYLE = "margin-bottom:6px;"
_DROPCAP_STYLE = (
    f"float:left;font-family:{_SERIF};font-size:56px;line-height:0.82;"
    f"font-weight:700;color:{_GOLD};padding:2px 6px 0 0;"
)


def _inline_format(text: str) -> str:
    """Escape HTML, then convert **bold** / *italic* markdown to tags."""
    escaped = html.escape(text, quote=False)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC_RE.sub(r"<em>\1</em>", escaped)
    return escaped


def _normalize_markdown(text: str) -> str:
    """Repair two known corruption patterns seen in agent-generated markdown
    before we try to parse it into blocks:

    1. Broken bold closers — the model sometimes emits the closing "**" of
       a bold span as "* *" (asterisk, whitespace, asterisk) instead of two
       adjacent asterisks, e.g. "**8% annual growth* * in the 80-plus..."
       Left alone, `_BOLD_RE`/`_ITALIC_RE` keep scanning past the broken
       closer for the *next* real "**", swallowing unrelated text into one
       giant bold span and leaving a dangling, unmatched "**" later on
       (rendered as a stray literal asterisk). We collapse "* *" -> "**"
       wherever the two stars are separated by nothing but whitespace, which
       safely leaves genuine "* " bullet markers and legitimate italic spans
       like "*Why it matters: *" untouched (those have real words, not just
       whitespace, between the stars).

    2. Lone header markers — the model occasionally emits the "#"/"##"
       marker on its own line, with the heading text arriving as a
       separate line right after (sometimes itself looking like a numbered
       or bulleted item, e.g. "##\n\n1. Some Heading"). `_HEADER_RE` only
       matches when the marker and text share a line, so the marker line
       becomes an empty header and the real title falls through and gets
       misclassified as a list item. We stitch the marker back onto the
       next non-blank line.
    """
    text = _BROKEN_BOLD_CLOSER_RE.sub("**", text)

    lines = text.split("\n")
    merged: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if _LONE_HEADER_MARKER_RE.match(stripped):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                merged.append(f"{stripped} {lines[j].strip()}")
                i = j + 1
                continue
        merged.append(lines[i])
        i += 1
    return "\n".join(merged)


def _classify(line: str) -> tuple[str, str, int]:
    """Return (block_type, content, level). level is only used for headers."""
    if m := _HEADER_RE.match(line):
        return "header", m.group(2).strip(), len(m.group(1))
    if m := _BULLET_RE.match(line):
        return "bullet", m.group(1).strip(), 0
    if m := _NUMBERED_RE.match(line):
        return "numbered", m.group(1).strip(), 0
    return "paragraph", line.strip(), 0


def markdown_to_email_html(text: str) -> str:
    """Convert a markdown answer into inline-styled HTML block elements.

    The first paragraph rendered gets a drop cap + bold lead treatment
    (matches the existing reader-inquiry template look). Everything after
    is standard newspaper body copy.
    """
    if not text or not text.strip():
        return f'<p style="{_P_STYLE}">No analysis available at the time of publication.</p>'

    lines = [ln.rstrip() for ln in _normalize_markdown(text.strip()).split("\n")]

    blocks: list[tuple[str, list[str], int]] = []
    para_buf: list[str] = []

    def flush_para():
        if para_buf:
            blocks.append(("paragraph", [" ".join(para_buf)], 0))
            para_buf.clear()

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            flush_para()
            continue
        btype, content, level = _classify(stripped)
        if btype == "paragraph":
            para_buf.append(content)
            continue
        flush_para()
        if blocks and blocks[-1][0] == btype and btype in ("bullet", "numbered"):
            blocks[-1][1].append(content)
        else:
            blocks.append((btype, [content], level))
    flush_para()

    html_parts: list[str] = []
    lead_used = False

    for btype, items, level in blocks:
        if btype == "header":
            html_parts.append(f'<div style="{_HEADER_STYLE}">{_inline_format(items[0])}</div>')
        elif btype == "bullet":
            lis = "".join(f'<li style="{_LI_STYLE}">{_inline_format(i)}</li>' for i in items)
            html_parts.append(f'<ul style="{_LIST_STYLE}">{lis}</ul>')
        elif btype == "numbered":
            lis = "".join(f'<li style="{_LI_STYLE}">{_inline_format(i)}</li>' for i in items)
            html_parts.append(f'<ol style="{_LIST_STYLE}">{lis}</ol>')
        else:
            formatted = _inline_format(items[0])
            if not lead_used:
                lead_used = True
                plain = re.sub(r"</?strong>", "", formatted)
                first_char, rest = plain[0], plain[1:]
                html_parts.append(
                    f'<p style="{_LEAD_P_STYLE}">'
                    f'<span style="{_DROPCAP_STYLE}">{first_char}</span>{rest}</p>'
                )
            else:
                html_parts.append(f'<p style="{_P_STYLE}">{formatted}</p>')

    return "\n".join(html_parts)