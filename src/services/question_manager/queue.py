"""Question queue operations (MongoDB-backed)."""
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
from src.services.question_manager.data_loader import DATA


async def initialize_question_file(db: "AsyncIOMotorDatabase") -> int:
    """Initialize question collection with default questions"""
    collection = db["questions"]
    
    count = await collection.count_documents({"status": "pending"})
    if count > 0:
        logger.info(f"📄 Question collection exists with {count} pending questions")
        return count
    
    default_questions = [
        "What is the current BI rate and what is its impact on the Rupiah exchange rate?",
        "What is the latest core inflation rate in Indonesia and how does it compare to BI's target?",
        "What is the current GDP growth forecast for Indonesia and key drivers?",
        "What are the latest policy signals from Bank Indonesia regarding future rates?",
        "What is the Federal Reserve's latest stance on interest rates and inflation?",
        "What is the current US inflation rate and its impact on global markets?",
        "What is the latest ECB policy decision and its effect on the Euro?",
        "What is the Bank of Japan's current monetary policy stance?",
        "What is the latest JCI (IDX Composite) performance and key movers?",
        "What are the top 5 performing stocks on IDX this week?",
        "What is the current foreign flow into Indonesian stock market?",
        "What are the latest earnings reports from major Indonesian banks?"
    ]
    
    questions_to_insert = [
        {
            "text": q,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "answered_at": None,
            "answer": None,
            "source": "default",
            "attempts": 0
        }
        for q in default_questions
    ]
    
    result = await collection.insert_many(questions_to_insert)
    logger.info(f"✅ Initialized {len(result.inserted_ids)} default questions")
    return len(result.inserted_ids)

async def get_question_count(db: "AsyncIOMotorDatabase") -> int:
    """Get count of pending questions"""
    collection = db["questions"]
    return await collection.count_documents({"status": "pending"})

async def get_next_question(db: "AsyncIOMotorDatabase") -> Optional[Dict[str, Any]]:
    """Get next pending question from database"""
    collection = db["questions"]
    
    question = await collection.find_one({"status": "pending"})
    
    if question:
        question["_id"] = str(question["_id"])
        logger.info(f"📨 Retrieved question: {question['text'][:50]}...")
        return question
    
    logger.warning("❌ No pending questions found")
    return None

async def add_question(db: "AsyncIOMotorDatabase", question: str, source: str = "manual") -> Optional[str]:
    """Add new question to database"""
    if not question or not question.strip():
        return None
    
    question = question.strip()
    if not question.endswith('?'):
        question += '?'
    
    collection = db["questions"]
    
    question_doc = {
        "text": question,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "answered_at": None,
        "answer": None,
        "source": source,
        "attempts": 0
    }
    
    result = await collection.insert_one(question_doc)
    logger.info(f"➕ Added question: {question[:50]}...")
    return str(result.inserted_id)

async def remove_first_question(db: "AsyncIOMotorDatabase") -> bool:
    """Remove and archive first pending question"""
    collection = db["questions"]
    
    question = await collection.find_one({"status": "pending"})
    if not question:
        return False
    
    await archive_question(db, str(question["_id"]), question["text"])
    
    await collection.update_one(
        {"_id": question["_id"]},
        {"$set": {"status": "archived", "answered_at": datetime.utcnow()}}
    )
    
    logger.info(f"🗑️ Archived question: {question['text'][:50]}...")
    return True

async def archive_question(
    db: "AsyncIOMotorDatabase",
    question_id: str,
    text: str
) -> bool:
    """Archive a question"""
    archive_collection = db["question_archive"]
    
    archive_doc = {
        "question_id": ObjectId(question_id) if ObjectId.is_valid(question_id) else question_id,
        "text": text,
        "archived_at": datetime.utcnow()
    }
    
    result = await archive_collection.insert_one(archive_doc)
    logger.info(f"📦 Archived: {text[:50]}...")
    return bool(result.inserted_id)

async def get_all_questions(db: "AsyncIOMotorDatabase", limit: int = 100, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get all questions with optional status filter"""
    collection = db["questions"]
    
    filter_query = {}
    if status:
        filter_query["status"] = status
    else:
        filter_query["status"] = {"$ne": "archived"}
    
    questions = []
    cursor = collection.find(filter_query).sort("created_at", -1).limit(limit)
    
    async for question in cursor:
        question["_id"] = str(question["_id"])
        questions.append(question)
    
    return questions

async def get_question_by_id(db: "AsyncIOMotorDatabase", question_id: str) -> Optional[Dict[str, Any]]:
    """Get a question by ID"""
    try:
        collection = db["questions"]
        if not ObjectId.is_valid(question_id):
            return None
        
        doc = await collection.find_one({"_id": ObjectId(question_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
            return doc
        return None
    except Exception as e:
        logger.error(f"Error getting question by ID: {str(e)}")
        return None

async def get_archive(db: "AsyncIOMotorDatabase", limit: int = 100) -> List[Dict[str, Any]]:
    """Get archived questions"""
    collection = db["question_archive"]
    
    archive = []
    cursor = collection.find({}).sort("archived_at", -1).limit(limit)
    
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        archive.append(doc)
    
    return archive

async def reset_question_queue(db: "AsyncIOMotorDatabase") -> int:
    """Reset question queue - delete all and reinitialize"""
    collection = db["questions"]
    archive_collection = db["question_archive"]
    
    await collection.delete_many({})
    await archive_collection.delete_many({})
    
    count = await initialize_question_file(db)
    logger.info(f"🔄 Queue reset with {count} questions")
    return count

async def get_question_stats(db: "AsyncIOMotorDatabase") -> Dict[str, Any]:
    """Get statistics on questions"""
    collection = db["questions"]
    archive_collection = db["question_archive"]
    
    pending = await collection.count_documents({"status": "pending"})
    archived = await archive_collection.count_documents({})
    total = pending + archived
    
    return {
        "pending_questions": pending,
        "archived_questions": archived,
        "total": total,
        "data_summary": {
            "topics_count": len(DATA.get("topics", [])),
            "sectors_count": len(DATA.get("sectors", [])),
            "companies_count": len(DATA.get("companies", [])),
            "commodities_count": len(DATA.get("commodities", [])),
            "indicators_count": len(DATA.get("indicators", []))
        }
    }

def get_question_count_sync(db: "AsyncIOMotorDatabase") -> int:
    """Sync wrapper"""
    return asyncio.run(get_question_count(db))

def get_next_question_sync(db: "AsyncIOMotorDatabase") -> Optional[Dict[str, Any]]:
    """Sync wrapper"""
    return asyncio.run(get_next_question(db))

def get_all_questions_sync(db: "AsyncIOMotorDatabase") -> List[Dict[str, Any]]:
    """Sync wrapper"""
    return asyncio.run(get_all_questions(db))
