"""Reference-data loading + the shared read-only DATA snapshot."""
import os
import logging
import random
import re
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
from bson import ObjectId

logger = logging.getLogger(__name__)

CURRENT_DIR = Path(__file__).parent
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_data_files() -> Dict[str, Any]:
    """Load data from files for question generation"""
    data = {
        "topics": [],
        "sectors": [],
        "companies": [],
        "indicators": [],
        "commodities": [],
        "events": [],
        "regions": []
    }
    
    try:
        data_dir = PROJECT_ROOT / "data" / "raw"
        
        deep_dive_file = data_dir / "deep_dive_reports.txt"
        if deep_dive_file.exists():
            with open(deep_dive_file, 'r') as f:
                content = f.read()
                topics = re.findall(r'\$\$TOPIC: (.*?)\$\$', content)
                data["topics"] = list(set(topics))
        
        structured_file = data_dir / "structured_analysis.txt"
        if structured_file.exists():
            with open(structured_file, 'r') as f:
                for line in f:
                    if '|' in line:
                        parts = [p.strip() for p in line.split('|')]
                        if len(parts) >= 3:
                            category = parts[0].strip()
                            title = parts[2].strip() if len(parts) > 2 else ""
                            if category and category not in ["CATEGORY", "---", ""]:
                                data["topics"].append(f"{category}: {title}")
        
        quant_file = data_dir / "quant_financial_data.txt"
        if quant_file.exists():
            with open(quant_file, 'r') as f:
                content = f.read()
                
                sector_match = re.search(r'TABLE 1:.*?\n(.*?)\n\n', content, re.DOTALL)
                if sector_match:
                    lines = sector_match.group(1).split('\n')
                    for line in lines:
                        if '|' in line and 'SECTOR' not in line and '------' not in line:
                            parts = [p.strip() for p in line.split('|')]
                            if parts and parts[0] and parts[0] not in ['SECTOR', '']:
                                data["sectors"].append(parts[0])
                
                commodity_match = re.search(r'TABLE 3:.*?\n(.*?)\n\n', content, re.DOTALL)
                if commodity_match:
                    lines = commodity_match.group(1).split('\n')
                    for line in lines:
                        if '|' in line and 'COMMODITY' not in line and '------' not in line:
                            parts = [p.strip() for p in line.split('|')]
                            if parts and parts[0] and parts[0] not in ['COMMODITY', '']:
                                data["commodities"].append(parts[0])
                
                company_match = re.search(r'TABLE 8:.*?\n(.*?)\n\n', content, re.DOTALL)
                if company_match:
                    lines = company_match.group(1).split('\n')
                    for line in lines:
                        if '|' in line and 'COMPANY' not in line and '------' not in line:
                            parts = [p.strip() for p in line.split('|')]
                            if parts and parts[0] and parts[0] not in ['COMPANY', '']:
                                data["companies"].append(parts[0])
                
                indicator_match = re.search(r'TABLE 5:.*?\n(.*?)\n\n', content, re.DOTALL)
                if indicator_match:
                    lines = indicator_match.group(1).split('\n')
                    for line in lines:
                        if '|' in line and 'INDICATOR' not in line and '------' not in line:
                            parts = [p.strip() for p in line.split('|')]
                            if parts and parts[0] and parts[0] not in ['INDICATOR', '']:
                                data["indicators"].append(parts[0])
        
        data["topics"] = [t for t in data["topics"] if t and len(t) > 5][:50]
        data["sectors"] = list(set([s for s in data["sectors"] if s and len(s) > 2]))[:20]
        data["companies"] = list(set([c for c in data["companies"] if c and len(c) > 2]))[:20]
        data["commodities"] = list(set([c for c in data["commodities"] if c and len(c) > 2]))[:15]
        data["indicators"] = list(set([i for i in data["indicators"] if i and len(i) > 5]))[:20]
        
        data["regions"] = ["Indonesia", "US", "China", "ASEAN", "Europe", "Japan", "India", "Singapore"]
        data["events"] = [
            "BI rate decision", "Fed meeting", "inflation release", "GDP report",
            "trade balance announcement", "earnings season", "IPO pipeline",
            "central bank intervention", "commodity price rally", "market correction"
        ]
        
        logger.info(f"📊 Loaded {len(data['topics'])} topics, {len(data['sectors'])} sectors")
        return data
        
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        return data


DATA = load_data_files()


def get_file_paths() -> dict:
    """Get project file paths"""
    return {
        "project_root": str(PROJECT_ROOT),
        "data_dir": str(PROJECT_ROOT / "data" / "raw")
    }

def get_data_summary() -> dict:
    """Get summary of loaded data"""
    return {
        "topics_count": len(DATA["topics"]),
        "sectors_count": len(DATA["sectors"]),
        "companies_count": len(DATA["companies"]),
        "commodities_count": len(DATA["commodities"]),
        "indicators_count": len(DATA["indicators"]),
        "sample_topics": DATA["topics"][:5],
        "sample_sectors": DATA["sectors"][:5]
    }
