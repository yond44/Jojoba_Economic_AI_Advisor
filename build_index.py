#!/usr/bin/env python
"""
RAG Index Builder
=================
Builds the ChromaDB vector index from data/raw files.

Usage:
    python build_index.py              # Build if data changed
    python build_index.py --force      # Force rebuild
    python build_index.py --help       # Show help
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.services.rag.engine import build_index
from src.services.rag.cache import clear_query_cache


def main():
    parser = argparse.ArgumentParser(
        description="Build RAG vector index from data/raw files"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if data hasn't changed"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed progress information"
    )
    
    args = parser.parse_args()
    
    print("🚀 Building RAG Index...")
    print(f"   Force: {args.force}")
    print(f"   Verbose: {args.verbose}")
    print()
    
    try:
        clear_query_cache()
        print("🧹 Cleared query cache")
        
        result = build_index(force=args.force)
        
        print("\n✅ Index Build Complete!")
        print(f"   Rebuilt: {result.get('rebuilt', False)}")
        print(f"   Data directory: {result.get('raw_dir', 'N/A')}")
        print(f"   Vectors: {result.get('vectors', 0)}")
        print(f"   Duration: {result.get('duration_s', 0)}s")
        
        if not result.get('rebuilt'):
            print(f"   Reason: {result.get('reason', 'Data unchanged')}")
            
        print(f"\n📁 Index location: ./chroma_db/")
        print(f"📊 Collection: {result.get('collection', 'rag_collection')}")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure you have a data/raw directory with your documents.")
        print("Expected structure:")
        print("  project_root/")
        print("  ├── data/")
        print("  │   └── raw/")
        print("  │       ├── deep_dive_reports_MASTER...")
        print("  │       ├── financial_glossary_MASTER.txt")
        print("  │       └── ...")
        return 1
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())