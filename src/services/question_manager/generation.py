"""Question generation (from data + n8n/LLM) and de-duplication."""
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
from src.services.question_manager.queue import get_all_questions, add_question


async def generate_new_question_from_data(db: "AsyncIOMotorDatabase") -> Optional[str]:
    """Generate new question from loaded data"""
    try:
        topic = random.choice(DATA["topics"]) if DATA["topics"] else "Indonesian economy"
        sector = random.choice(DATA["sectors"]) if DATA["sectors"] else "banking"
        company = random.choice(DATA["companies"]) if DATA["companies"] else "companies"
        commodity = random.choice(DATA["commodities"]) if DATA["commodities"] else "commodities"
        indicator = random.choice(DATA["indicators"]) if DATA["indicators"] else "economic indicators"
        region = random.choice(DATA["regions"]) if DATA["regions"] else "Indonesia"
        event = random.choice(DATA["events"]) if DATA["events"] else "market developments"
        
        templates = [
            f"What are the latest trends in {topic} and what are the implications for Indonesia's economy?",
            f"How is {indicator} performing in {region} and what does it signal for monetary policy?",
            f"What is the current valuation and outlook for the {sector} sector in Indonesia?",
            f"What are the latest earnings and performance of {company}?",
            f"What is the current price and outlook for {commodity}?",
            f"How are {region} market developments affecting Indonesian stocks?",
            f"What is the impact of {event} on the markets?",
            f"What are the top investment opportunities in {sector}?",
            f"How will {topic} impact {region}'s economy?",
            f"What is the market sentiment toward {sector} right now?"
        ]
        
        question = random.choice(templates).strip()
        if not question.endswith('?'):
            question += '?'
        
        existing = await get_all_questions(db, limit=20)
        if await is_duplicate_question(question, existing):
            logger.warning("⚠️ Generated duplicate question, trying again...")
            return await get_random_fallback_question_async(db)
        
        await add_question(db, question, source="generated")
        logger.info(f"✨ Generated: {question[:60]}...")
        return question
        
    except Exception as e:
        logger.error(f"Error generating question: {e}")
        return await get_random_fallback_question_async(db)

async def is_duplicate_question(
    new_question: str,
    existing_questions: List[Dict[str, Any]],
    threshold: float = 0.6
) -> bool:
    """Check if question is duplicate"""
    if not existing_questions:
        return False
    
    stop_words = {
        'what', 'is', 'are', 'the', 'of', 'to', 'for', 'on', 'at', 'from',
        'by', 'in', 'with', 'and', 'or', 'but', 'nor', 'into', 'through'
    }
    
    new_words = set([
        w.lower() for w in new_question.split()
        if w.lower() not in stop_words and len(w) > 3
    ])
    
    for existing in existing_questions[-15:]:
        existing_text = existing.get("text", "")
        existing_words = set([
            w.lower() for w in existing_text.split()
            if w.lower() not in stop_words and len(w) > 3
        ])
        
        if not new_words or not existing_words:
            continue
        
        overlap = len(new_words.intersection(existing_words)) / len(new_words.union(existing_words))
        
        if overlap > threshold:
            return True
    
    return False

async def get_random_fallback_question_async(db: "AsyncIOMotorDatabase") -> str:
    """Get random fallback question"""
    fallbacks = [
        "What is the current Rupiah exchange rate against USD and what are the key drivers?",
        "What is the latest JCI performance and which sectors are leading the market?",
        "What is the current oil price and how does it impact Indonesia's trade balance?",
        "What are the latest earnings from major Indonesian banks?",
        "What is the current inflation rate and how is BI responding?",
        "What are the latest foreign investment trends in Indonesia?",
        "What is the outlook for commodity prices and their impact on Indonesia?",
        "What are the most promising sectors for investment in Indonesia right now?",
        "What is the impact of global supply chain disruptions on Indonesia?",
        "What are the key themes driving the Indonesian market this quarter?"
    ]
    question = random.choice(fallbacks)
    await add_question(db, question, source="fallback")
    return question

def get_default_fallback_questions() -> List[str]:
    """Get default fallback questions"""
    return [
        "What is the current Rupiah exchange rate against USD and what are the key drivers?",
        "What is the latest JCI performance and which sectors are leading the market?",
        "What is the current oil price and how does it impact Indonesia's trade balance?",
        "What are the latest earnings from major Indonesian banks?",
        "What is the current inflation rate and how is BI responding?",
        "What are the latest foreign investment trends in Indonesia?",
        "What is the outlook for commodity prices and their impact on Indonesia?",
        "What are the most promising sectors for investment in Indonesia right now?",
        "What is the impact of global supply chain disruptions on Indonesia?",
        "What are the key themes driving the Indonesian market this quarter?"
    ]

async def n8n_generate_questions_with_llm(
    db: "AsyncIOMotorDatabase",
    topic: Optional[str] = None,
    complexity: str = "medium",
    num_questions: int = 1
) -> List[str]:
    """
    N8N: Generate intelligent questions using LLM based on data context
    
    This uses the agent/LLM to generate context-aware questions
    based on economic data, documents, and previous context.
    """
    try:
        from src.services.agent import ask_agent
        
        context = _get_data_context_for_questions()
        
        prompt = _build_question_generation_prompt(
            context=context,
            topic=topic,
            complexity=complexity,
            num_questions=num_questions
        )
        
        result = await ask_agent(
            question=prompt,
            db=db,
            language="en",
            channel="api" 
        )
        
        if not result.get("success"):
            logger.error(f"Failed to generate questions: {result.get('error')}")
            return _get_fallback_questions(num_questions)
        
        answer = result.get("answer", "")
        questions = _parse_generated_questions(answer)
        
        if not questions:
            logger.warning("No questions parsed from LLM response, using fallback")
            return _get_fallback_questions(num_questions)
        
        questions = questions[:num_questions]
        
        logger.info(f"✨ Generated {len(questions)} questions using LLM")
        return questions
        
    except Exception as e:
        logger.error(f"Error generating questions with LLM: {str(e)}")
        return _get_fallback_questions(num_questions)

def _get_data_context_for_questions() -> str:
    """Get context from loaded data for question generation"""
    try:
        context_parts = []
        
        if DATA.get("topics"):
            topics_sample = random.sample(DATA["topics"], min(10, len(DATA["topics"])))
            context_parts.append(f"Key topics: {', '.join(topics_sample)}")
        
        if DATA.get("sectors"):
            sectors_sample = random.sample(DATA["sectors"], min(8, len(DATA["sectors"])))
            context_parts.append(f"Key sectors: {', '.join(sectors_sample)}")
        
        if DATA.get("companies"):
            companies_sample = random.sample(DATA["companies"], min(5, len(DATA["companies"])))
            context_parts.append(f"Key companies: {', '.join(companies_sample)}")
        
        if DATA.get("indicators"):
            indicators_sample = random.sample(DATA["indicators"], min(8, len(DATA["indicators"])))
            context_parts.append(f"Economic indicators: {', '.join(indicators_sample)}")
        
        if DATA.get("commodities"):
            commodities_sample = random.sample(DATA["commodities"], min(5, len(DATA["commodities"])))
            context_parts.append(f"Commodities: {', '.join(commodities_sample)}")
        
        return "\n".join(context_parts) if context_parts else "Indonesian economy and financial markets"
        
    except Exception as e:
        logger.error(f"Error getting data context: {str(e)}")
        return "Indonesian economy and financial markets"

def _build_question_generation_prompt(
    context: str,
    topic: Optional[str],
    complexity: str,
    num_questions: int
) -> str:
    """Build prompt for LLM question generation"""
    
    complexity_instructions = {
        "simple": "simple, straightforward questions about current economic conditions",
        "medium": "moderately complex questions that require analysis and synthesis of economic data",
        "complex": "advanced, strategic questions that require deep analysis and forecasting"
    }
    
    instruction = complexity_instructions.get(complexity, complexity_instructions["medium"])
    
    prompt = f"""Based on the following economic data and context, generate {num_questions} relevant, insightful questions.

Data Context:
{context}

{f"Focus on the topic: {topic}" if topic else "Generate questions covering various aspects of the economy."}

Requirements:
1. Questions should be {instruction}
2. Questions should be specific and data-driven
3. Questions should be relevant for investment/economic analysis
4. Each question should be a complete sentence ending with a question mark

Generate {num_questions} questions, one per line, numbered or separated by newlines:

Questions:
"""
    
    return prompt.strip()

def _parse_generated_questions(answer: str) -> List[str]:
    """Parse questions from LLM response"""
    questions = []
    
    lines = answer.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        cleaned = re.sub(r'^[\d\s\.]+[\.\:]\s*', '', line)
        cleaned = re.sub(r'^Q[\d]+\s*[:\.]\s*', '', cleaned, flags=re.IGNORECASE)
        
        if cleaned.endswith('?'):
            questions.append(cleaned)
        elif cleaned and not cleaned.endswith('.'):
            questions.append(cleaned + '?')
    
    if not questions:
        sentences = answer.split('. ')
        for sent in sentences:
            sent = sent.strip()
            if '?' in sent:
                parts = sent.split('?')
                for part in parts:
                    if part.strip():
                        questions.append(part.strip() + '?')
    
    return questions

def _get_fallback_questions(num_questions: int) -> List[str]:
    """Get fallback questions if LLM generation fails"""
    fallbacks = get_default_fallback_questions()
    
    if len(fallbacks) <= num_questions:
        return fallbacks[:num_questions]
    
    return random.sample(fallbacks, num_questions)
