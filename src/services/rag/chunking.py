"""
Document chunking strategies — extracted verbatim from the original rag.py.
Each MASTER file type keeps its bespoke strategy (FIX #5 sanity checks intact).
"""
from __future__ import annotations

import logging
from typing import Dict, List

from llama_index.core import Document
from llama_index.core.node_parser import SimpleNodeParser

from src.services.rag.config import CHUNK_SIZE, CHUNK_OVERLAP

logger = logging.getLogger(__name__)


def setup_node_parser():
    return SimpleNodeParser.from_defaults(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )


def chunk_documents_by_type(documents: List[Document]) -> List[Document]:
    """Route documents to a chunking strategy based on MASTER file names."""
    chunked_docs = []

    for doc in documents:
        file_name = doc.metadata.get('file_name', '').lower()

        if 'qa_pairs' in file_name:
            strategy, chunks = "qa_pair", chunk_qa_document(doc)
        elif 'glossary' in file_name:
            strategy, chunks = "glossary", chunk_glossary_document(doc)
        elif 'scenario_playbooks' in file_name:
            strategy, chunks = "scenario", chunk_scenario_document(doc)
        elif 'structured_analysis' in file_name:
            strategy, chunks = "structured", chunk_structured_document(doc)
        elif 'deep_dive' in file_name:
            strategy, chunks = "deep_dive", chunk_deep_document(doc)
        elif 'quant' in file_name or 'financial_data' in file_name:
            strategy, chunks = "quant", chunk_quant_document(doc)
        else:
            strategy, chunks = "default", chunk_default_document(doc)

        _warn_if_chunking_suspicious(file_name, strategy, doc, chunks)

        chunked_docs.extend(chunks)
        logger.info(f"  📄 {file_name}: {len(chunks)} chunks ({strategy})")

    return chunked_docs


def _warn_if_chunking_suspicious(file_name: str, strategy: str,
                                 doc: Document, chunks: List[Document]):
    """Loud warning when a specialized strategy probably failed (format drift)."""
    if strategy == "default":
        return

    doc_len = len(doc.text)
    if len(chunks) == 1 and doc_len > CHUNK_SIZE * 2:
        logger.warning(
            f"⚠️ CHUNKING SUSPICIOUS: '{file_name}' ({doc_len} chars) produced "
            f"only 1 chunk under the '{strategy}' strategy. The file format "
            f"may have drifted (missing/renamed markers). Retrieval quality "
            f"will degrade silently — check the file!"
        )
    else:
        avg = sum(len(c.text) for c in chunks) / len(chunks)
        if avg > CHUNK_SIZE * 4:
            logger.warning(
                f"⚠️ CHUNKING SUSPICIOUS: '{file_name}' avg chunk is {avg:.0f} "
                f"chars (config CHUNK_SIZE={CHUNK_SIZE}). Markers may be "
                f"partially broken."
            )


def chunk_qa_document(doc: Document) -> List[Document]:
    """Chunk QA pairs — each Q&A pair stays together as one chunk."""
    chunks = []
    pairs = doc.text.split('\nQ: ')

    for i, pair in enumerate(pairs):
        pair = pair.strip()
        if not pair:
            continue
        if not pair.startswith('Q:'):
            pair = 'Q: ' + pair
        if len(pair) > 50:
            chunks.append(Document(
                text=pair,
                metadata={**doc.metadata, "chunk_type": "qa_pair", "pair_index": i}
            ))

    return chunks if chunks else [doc]


def chunk_glossary_document(doc: Document) -> List[Document]:
    """Chunk glossary — each definition is its own chunk."""
    chunks = []
    lines = doc.text.split('\n')

    def flush(entry_lines):
        entry_text = '\n'.join(entry_lines)
        if len(entry_text) > 30:
            chunks.append(Document(
                text=entry_text,
                metadata={**doc.metadata, "chunk_type": "glossary_entry"}
            ))

    current_entry = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        is_new_entry = False
        if stripped[0].isupper() and (':' in stripped[:80] or '(' in stripped[:80]):
            words_before_colon = stripped.split(':')[0].split('(')[0].strip()
            if words_before_colon.isupper() or words_before_colon.replace(' ', '').replace('-', '').replace('/', '').isupper():
                is_new_entry = True

        if is_new_entry and current_entry:
            flush(current_entry)
            current_entry = [stripped]
        elif stripped.startswith('#'):
            if current_entry:
                flush(current_entry)
                current_entry = []
        else:
            current_entry.append(stripped)

    if current_entry:
        flush(current_entry)

    return chunks if chunks else [doc]


def chunk_scenario_document(doc: Document) -> List[Document]:
    """Chunk scenario playbooks — each full scenario stays together."""
    chunks = []
    scenarios = doc.text.split('[SCENARIO PLAYBOOK]')

    for i, scenario in enumerate(scenarios):
        scenario = scenario.strip()
        if not scenario or len(scenario) < 100:
            continue
        chunks.append(Document(
            text='[SCENARIO PLAYBOOK] ' + scenario,
            metadata={**doc.metadata, "chunk_type": "scenario_playbook", "scenario_index": i}
        ))

    return chunks if chunks else [doc]


def chunk_structured_document(doc: Document) -> List[Document]:
    """Chunk structured analysis — each row with its header as context."""
    chunks = []
    lines = doc.text.split('\n')

    header = ""
    for line in lines:
        if 'CATEGORY' in line and 'DATE' in line and '|' in line:
            header = line
            break

    for i, line in enumerate(lines):
        line = line.strip()
        if not line or line == header:
            continue
        if line.startswith('#') or line.startswith('='):
            continue
        if '|' in line and 'CATEGORY' not in line:
            parts = [p.strip() for p in line.split('|')]
            category = parts[0] if len(parts) > 0 else "unknown"
            title = parts[2] if len(parts) > 2 else "unknown"
            chunks.append(Document(
                text=f"{header}\n{line}",
                metadata={
                    **doc.metadata,
                    "chunk_type": "structured_row",
                    "category": category,
                    "title": title[:100],
                    "row_index": i
                }
            ))

    return chunks if chunks else [doc]


def chunk_deep_document(doc: Document) -> List[Document]:
    """Chunk deep dive reports — each report (marked by [DATE:]) stays together."""
    chunks = []
    reports = doc.text.split('[DATE:')

    for i, report in enumerate(reports):
        report = report.strip()
        if not report or len(report) < 100:
            continue

        report_text = '[DATE: ' + report
        topic = "unknown"
        if '[TOPIC:' in report_text:
            try:
                topic = report_text.split('[TOPIC:')[1].split(']')[0].strip()
            except IndexError:
                pass

        chunks.append(Document(
            text=report_text,
            metadata={
                **doc.metadata,
                "chunk_type": "deep_dive_report",
                "topic": topic[:100],
                "report_index": i
            }
        ))

    return chunks if chunks else [doc]


def chunk_quant_document(doc: Document) -> List[Document]:
    """Chunk quantitative data — each TABLE stays together as one chunk."""
    chunks = []
    sections = []
    current_section = []
    current_title = ""

    for line in doc.text.split('\n'):
        if '=' * 20 in line:
            if current_section:
                content = '\n'.join(current_section)
                if len(content.strip()) > 50 and '|' in content:
                    sections.append((current_title, content))
                current_section = []
                current_title = ""
            continue

        stripped = line.strip()
        if stripped.startswith('TABLE') or stripped.startswith('#'):
            current_title = stripped
            continue
        if stripped:
            current_section.append(line)

    if current_section:
        content = '\n'.join(current_section)
        if len(content.strip()) > 50:
            sections.append((current_title, content))

    for i, (title, content) in enumerate(sections):
        chunk_text = f"{title}\n{content}" if title else content
        chunks.append(Document(
            text=chunk_text,
            metadata={
                **doc.metadata,
                "chunk_type": "quant_table",
                "table_title": title[:100] if title else "unknown",
                "table_index": i
            }
        ))

    return chunks if chunks else [doc]


def chunk_default_document(doc: Document) -> List[Document]:
    """Chunk generic documents — standard approach."""
    parser = SimpleNodeParser.from_defaults(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    nodes = parser.get_nodes_from_documents([doc])
    return [
        Document(text=node.text, metadata={**doc.metadata, "chunk_type": "default"})
        for node in nodes
    ]
