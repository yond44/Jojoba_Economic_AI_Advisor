"""
Offline RAG Index Builder — Thin CLI
====================================

PRODUCTION FIX #8 (see rag.py): this script used to carry its OWN copies
of setup_embeddings / setup_vector_store / setup_node_parser, with the
collection name HARDCODED as "my_collection" — while rag.py read it from
the CHROMA_COLLECTION env var. Two implementations of the same pipeline
always drift, and this drift had the nastiest failure mode possible:
builds succeed, deploys succeed, and retrieval quietly returns nothing
because the runtime is reading a different collection than the one the
build wrote to.

The build pipeline now lives in exactly one place: rag.build_index().
This file is only argument parsing + logging setup. The same function is
also callable from a FastAPI admin endpoint or a cron job, so you can
rebuild on a stronger server instead of embedding locally:

    # On the server (Python shell, admin endpoint, or cron):
    from src.services.rag import build_index, rebuild_index_async
    report = build_index(force=False)     # skips if data unchanged

    # FastAPI (non-blocking):
    @app.post("/admin/rebuild-index")
    async def rebuild(force: bool = False):
        return await rebuild_index_async(force=force)

If the process is already serving queries, build_index() hot-swaps the
new index into the live query engine — no restart needed.

Usage:
    python build_index.py            # build only if data content changed
    python build_index.py --force    # paksa rebuild walau data tidak berubah
"""

import sys
import logging
import argparse

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

from rag import build_index


def main():
    parser = argparse.ArgumentParser(description="Offline RAG index builder")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Paksa rebuild index walau data tidak berubah",
    )
    args = parser.parse_args()

    try:
        report = build_index(force=args.force)
    except FileNotFoundError as e:
        logger.error(f"❌ {e}")
        sys.exit(1)

    if not report["rebuilt"]:
        logger.info("📦 Data files unchanged sejak build terakhir — skip. "
                    "Gunakan --force untuk paksa rebuild.")
        return

    logger.info(f"✅ Selesai dalam {report['duration_s']}s — "
                f"{report['vectors']} vectors di collection '{report['collection']}'.")
    logger.info("👉 Folder chroma_db/ sudah berisi index terbaru. "
                "Commit ke git lalu deploy ke HF Spaces — atau, kalau build "
                "ini jalan di server yang sedang serving, index sudah "
                "otomatis hot-swapped tanpa restart.")


if __name__ == "__main__":
    main()