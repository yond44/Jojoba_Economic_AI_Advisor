from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import random
import uuid
from enum import Enum
import time
import logging
from src.config.prompts import (
    detect_gratitude, get_fallback_response, 
    get_gratitude_response, get_off_topic_response, 
    get_no_data_response, format_response_with_disclaimer,
    format_response_with_sources, get_error_response, detect_greeting,
    detect_language, get_system_prompt, DISCLAIMER,
    IntelligentRecommender, format_complete_response, get_rate_limit_response,
    get_greeting_response, detect_human_expression, detect_question_request,
    QuestionGenerator
)

logger = logging.getLogger(__name__)

# ============================================
# PYDANTIC MODELS
# ============================================

class ChannelType(str, Enum):
    """Supported channels"""
    API = "api"
    WEB = "web"
    MOBILE = "mobile"
    EMAIL = "email"
    BATCH = "batch"


class QueryRequest(BaseModel):
    """Request model for user queries"""
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    thread_id: Optional[str] = Field(None, description="Conversation thread identifier")
    channel: Optional[ChannelType] = Field(ChannelType.API, description="Source channel")
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    username: Optional[str] = Field(None, description="Optional username")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    
    @validator('question')
    def question_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Question cannot be empty or whitespace')
        return v.strip()
    
    @validator('thread_id', pre=True, always=True)
    def set_thread_id(cls, v):
        return v or str(uuid.uuid4())


class QueryResponse(BaseModel):
    """Response model for queries"""
    question: str = Field(..., description="Original question")
    answer: str = Field(..., description="Generated answer")
    processing_time: float = Field(..., description="Time taken to process in seconds")
    iterations: int = Field(default=1, description="Number of reasoning iterations")
    thread_id: Optional[str] = Field(None, description="Conversation thread identifier")
    language_detected: str = Field(default="en", description="Detected language (en/id)")
    response_type: str = Field(default="answer", description="Type of response")
    success: bool = Field(default=True, description="Whether query was successful")
    validated: bool = Field(default=True, description="Whether query was validated")
    greeting: bool = Field(default=False, description="Whether this is a greeting")
    gratitude: bool = Field(default=False, description="Whether this is gratitude")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Referenced sources")
    source_documents: Optional[List[str]] = Field(None, description="Referenced source documents")
    confidence_score: Optional[float] = Field(None, ge=0, le=1, description="Answer confidence")
    recommendations: Optional[List[str]] = Field(default_factory=list, description="Follow-up recommendations")
    error: Optional[str] = Field(None, description="Error message if any")
    user_id: Optional[str] = Field(None, description="User identifier")
    attempts: int = Field(default=1, description="Number of attempts made")
    queue_info: Optional[Dict[str, Any]] = Field(None, description="Queue processing info")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    class Config:
        json_schema_extra = {
            "example": {
                "question": "What is the impact of interest rates on stock markets?",
                "answer": "Interest rates have a significant impact on stock valuations...",
                "processing_time": 1.23,
                "iterations": 1,
                "thread_id": "conv-123",
                "language_detected": "en",
                "response_type": "answer",
                "success": True,
                "validated": True,
                "greeting": False,
                "gratitude": False,
                "sources": [],
                "confidence_score": 0.85,
                "recommendations": [
                    "Learn more about bond markets",
                    "Explore portfolio diversification strategies"
                ],
                "error": None,
                "user_id": "user-123",
                "attempts": 1
            }
        }


class BatchEmailRequest(BaseModel):
    """Request model for batch email processing"""
    question: str = Field(..., min_length=1, max_length=2000, description="Question to analyze")
    emails: List[str] = Field(..., min_items=1, max_items=100, description="Email addresses")
    phone: Optional[str] = Field(None, description="Contact phone number")
    subject: Optional[str] = Field(None, description="Email subject line")
    include_pdf: Optional[bool] = Field(False, description="Include PDF report")
    frequency: Optional[str] = Field("once", description="Delivery frequency")
    language: Optional[str] = Field(None, description="Response language (auto-detect if None)")
    
    @validator('emails')
    def validate_emails(cls, v):
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        for email in v:
            if not re.match(email_pattern, email):
                raise ValueError(f'Invalid email format: {email}')
        return list(set(v))


class ConversationContext(BaseModel):
    """Track conversation context for intelligent recommendations"""
    thread_id: str
    user_id: Optional[str] = None
    username: Optional[str] = None
    questions_history: List[str] = Field(default_factory=list, max_items=50)
    topics_discussed: List[str] = Field(default_factory=list)
    user_level: str = Field(default="beginner")
    language: str = Field(default="en")
    channel: ChannelType = Field(default=ChannelType.API)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_interaction: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    interaction_count: int = Field(default=0)


# ============================================
# ADVANCED AGENT CLASS
# ============================================

class EconomicAdvisorAgent:
    def __init__(self):
        self.conversation_contexts: Dict[str, ConversationContext] = {}
        self.interaction_history: List[Dict[str, Any]] = []
        self.rate_limits: Dict[str, List[float]] = {}

    def _get_or_create_context(self, request: QueryRequest) -> ConversationContext:
        thread_id = request.thread_id
        lang = detect_language(request.question)

        if thread_id not in self.conversation_contexts:
            self.conversation_contexts[thread_id] = ConversationContext(
                thread_id=thread_id,
                user_id=request.user_id,
                username=request.username,
                language=lang,
                channel=request.channel
            )

        context = self.conversation_contexts[thread_id]
        context.last_interaction = datetime.utcnow().isoformat()
        context.interaction_count += 1
        context.language = lang
        return context

    def _check_rate_limit(self, user_id: Optional[str], channel: ChannelType, limit: int = 10) -> bool:
        key = f"{user_id or 'anonymous'}:{channel.value}"
        now = time.time()
        window = self.rate_limits.get(key, [])
        window = [ts for ts in window if now - ts < 60]
        if len(window) >= limit:
            self.rate_limits[key] = window
            return False
        window.append(now)
        self.rate_limits[key] = window
        return True

    def _detect_response_type(self, question: str, language: str = "en") -> str:
        q = question.lower()
        patterns_en = {
            "comparison": ["compare", "vs", "difference between"],
            "trend": ["trend", "going up", "going down"],
            "analysis": ["analysis", "analyze", "explain", "detail"],
            "recommendation": ["should i", "recommend", "suggest"],
            "how": ["how", "mechanism", "process"],
            "why": ["why", "reason", "cause"],
        }
        patterns_id = {
            "comparison": ["bandingkan", "perbedaan", "versus"],
            "trend": ["tren", "naik", "turun"],
            "analysis": ["analisis", "analisa", "jelaskan", "uraikan"],
            "recommendation": ["haruskah", "rekomendasikan", "sarankan"],
            "how": ["bagaimana", "proses", "mekanisme"],
            "why": ["mengapa", "alasan", "penyebab"],
        }
        patterns = patterns_id if language == "id" else patterns_en
        for rtype, pats in patterns.items():
            if any(p in q for p in pats):
                return rtype
        return "answer"

    def _extract_entities(self, question: str) -> Dict[str, Any]:
        entities = {"companies": [], "sectors": [], "assets": [], "metrics": [], "time_periods": []}
        import re
        tickers = re.findall(r'\b[A-Z]{1,5}\b', question)
        entities["companies"] = tickers

        q = question.lower()
        sectors = ["tech", "technology", "teknologi", "finance", "keuangan", "energy", "energi", "healthcare", "kesehatan"]
        entities["sectors"] = [s for s in sectors if s in q]

        assets = {
            "stocks": ["stock", "equity", "share", "company", "saham", "ekuitas"],
            "crypto": ["crypto", "bitcoin", "ethereum", "blockchain"],
            "commodities": ["commodity", "komoditas", "gold", "emas", "oil", "minyak"],
            "forex": ["currency", "mata uang", "dollar", "euro", "yen"],
        }
        for a, kws in assets.items():
            if any(k in q for k in kws):
                entities["assets"].append(a)

        metrics = ["pe ratio", "rasio", "revenue", "pendapatan", "profit", "laba", "margin", "dividend", "dividen"]
        entities["metrics"] = [m for m in metrics if m in q]

        periods = ["today", "yesterday", "week", "month", "quarter", "year", "hari ini", "kemarin", "minggu", "bulan", "kuartal", "tahun"]
        entities["time_periods"] = [p for p in periods if p in q]
        return entities

    def _update_context(self, context: ConversationContext, question: str, response_type: str, entities: Dict[str, Any]):
        context.questions_history.append(question)
        if entities.get("companies"):
            context.topics_discussed.extend(["company_analysis"] * len(entities["companies"]))
        if entities.get("sectors"):
            context.topics_discussed.extend(["sector_analysis"] * len(entities["sectors"]))
        if entities.get("assets"):
            context.topics_discussed.extend(entities["assets"])
        if len(context.questions_history) > 5:
            context.user_level = IntelligentRecommender.estimate_user_level(context.questions_history)

    def _is_in_scope(self, question: str) -> bool:
        q = question.lower()
        keywords = [
            "economics", "economic", "ekonomi", "investment", "investasi", "stock", "saham",
            "market", "pasar", "crypto", "komoditas", "commodity", "business", "bisnis",
            "trade", "perdagangan", "forex", "portfolio", "portofolio", "asset", "aset",
            "equity", "ekuitas", "fund", "dana", "bond", "obligasi", "dividend", "dividen",
            "profit", "laba", "revenue", "pendapatan", "analysis", "analisis", "risk", "risiko",
            "return", "inflation", "inflasi", "gdp", "interest rate", "suku bunga", "policy", "kebijakan",
            "sector", "sektor", "valuation", "valuasi"
        ]
        return any(k in q for k in keywords)

    def _generate_answer(self, question: str, entities: Dict[str, Any], response_type: str, context: ConversationContext, language: str) -> str:
        if language == "id":
            answer = f"Berdasarkan pertanyaan Anda tentang {response_type}...\n\n[Analisis/jawaban dari basis pengetahuan]\n"
        else:
            answer = f"Based on your question about {response_type}...\n\n[Your analysis/answer from the knowledge base]\n"
        return format_response_with_disclaimer(answer, language)

    def _log_interaction(self, request: QueryRequest, response: QueryResponse, context: ConversationContext):
        self.interaction_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "thread_id": request.thread_id,
            "user_id": request.user_id,
            "username": request.username,
            "channel": request.channel.value,
            "question": request.question,
            "response_type": response.response_type,
            "processing_time": response.processing_time,
            "language": response.language_detected,
            "confidence": response.confidence_score
        })

    def _calculate_confidence(self, response_type: str, interaction_count: int) -> float:
        base = {
            "answer": 0.85, "analysis": 0.85, "comparison": 0.8, "trend": 0.75,
            "greeting": 1.0, "gratitude": 1.0, "question_generation": 0.9,
            "error": 0.0, "off-topic": 0.5
        }
        c = base.get(response_type, 0.7)
        if interaction_count > 5:
            c = min(1.0, c + 0.05)
        return round(c, 2)

    def process_query(self, request: QueryRequest) -> QueryResponse:
        start = time.time()
        language = detect_language(request.question)

        if not self._check_rate_limit(request.user_id, request.channel):
            return QueryResponse(
                question=request.question,
                answer=get_rate_limit_response(language),
                processing_time=time.time() - start,
                iterations=0,
                thread_id=request.thread_id,
                language_detected=language,
                response_type="error",
                success=False,
                validated=False
            )

        context = self._get_or_create_context(request)

        topic = detect_question_request(request.question)
        if topic:
            questions = QuestionGenerator.generate_contextual_questions(
                topic=topic,
                user_level=context.user_level,
                language=language,
                previous_questions=context.questions_history,
                count=5
            )
            answer = QuestionGenerator.format_questions_response(
                questions=questions,
                topic=topic,
                user_level=context.user_level,
                language=language
            )
            resp = QueryResponse(
                question=request.question,
                answer=answer,
                processing_time=time.time() - start,
                iterations=1,
                thread_id=request.thread_id,
                language_detected=language,
                response_type="question_generation",
                success=True,
                validated=True,
                user_id=request.user_id,
                attempts=1
            )
            self._log_interaction(request, resp, context)
            return resp

        if detect_greeting(request.question):
            resp = QueryResponse(
                question=request.question,
                answer=get_greeting_response(language),
                processing_time=time.time() - start,
                iterations=1,
                thread_id=request.thread_id,
                language_detected=language,
                response_type="greeting",
                success=True,
                validated=True,
                greeting=True,
                user_id=request.user_id,
                attempts=1
            )
            self._log_interaction(request, resp, context)
            return resp

        if detect_gratitude(request.question):
            resp = QueryResponse(
                question=request.question,
                answer=get_gratitude_response(language),
                processing_time=time.time() - start,
                iterations=1,
                thread_id=request.thread_id,
                language_detected=language,
                response_type="gratitude",
                success=True,
                validated=True,
                gratitude=True,
                user_id=request.user_id,
                attempts=1
            )
            self._log_interaction(request, resp, context)
            return resp

        human_expr = detect_human_expression(request.question, language)
        if human_expr:
            resp = QueryResponse(
                question=request.question,
                answer=human_expr["response"],
                processing_time=time.time() - start,
                iterations=1,
                thread_id=request.thread_id,
                language_detected=language,
                response_type=human_expr["type"],
                success=True,
                validated=True,
                user_id=request.user_id,
                attempts=1
            )
            self._log_interaction(request, resp, context)
            return resp

        response_type = self._detect_response_type(request.question, language)
        entities = self._extract_entities(request.question)
        self._update_context(context, request.question, response_type, entities)

        if not self._is_in_scope(request.question):
            answer = get_off_topic_response(language)
            success, validated, response_type = False, False, "off-topic"
        else:
            answer = self._generate_answer(request.question, entities, response_type, context, language)
            success, validated = True, True

        recommendations = []
        if response_type not in ["greeting", "gratitude", "error", "off-topic", "question_generation"]:
            rec_text = IntelligentRecommender.generate_recommendations(
                request.question,
                user_level=context.user_level,
                previous_questions=context.questions_history,
                language=language
            )
            if rec_text:
                recommendations = [line.strip("• ").strip() for line in rec_text.split("\n") if line.strip("• ").strip()]

        resp = QueryResponse(
            question=request.question,
            answer=answer,
            processing_time=time.time() - start,
            iterations=1,
            thread_id=request.thread_id,
            language_detected=language,
            response_type=response_type,
            success=success,
            validated=validated,
            sources=[],
            recommendations=recommendations,
            confidence_score=self._calculate_confidence(response_type, len(context.questions_history)),
            user_id=request.user_id,
            attempts=1
        )
        self._log_interaction(request, resp, context)
        return resp

    def get_conversation_summary(self, thread_id: str) -> Optional[Dict[str, Any]]:
        context = self.conversation_contexts.get(thread_id)
        if not context:
            return None
        return {
            "thread_id": thread_id,
            "user_id": context.user_id,
            "username": context.username,
            "interaction_count": context.interaction_count,
            "topics": list(set(context.topics_discussed)),
            "user_level": context.user_level,
            "language": context.language,
            "duration": {"created_at": context.created_at, "last_interaction": context.last_interaction},
            "question_count": len(context.questions_history)
        }

    def clear_old_contexts(self, max_age_hours: int = 24) -> int:
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        to_remove = [tid for tid, ctx in self.conversation_contexts.items() if datetime.fromisoformat(ctx.last_interaction) < cutoff]
        for tid in to_remove:
            del self.conversation_contexts[tid]
        return len(to_remove)


# ============================================
# BATCH EMAIL PROCESSOR
# ============================================

class BatchEmailProcessor:
    def __init__(self, agent: EconomicAdvisorAgent):
        self.agent = agent

    def process_batch(self, request: BatchEmailRequest) -> Dict[str, Any]:
        batch_id = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())
        language = request.language or detect_language(request.question)

        query_request = QueryRequest(
            question=request.question,
            thread_id=thread_id,
            channel=ChannelType.BATCH,
            metadata={"language": language}
        )
        response = self.agent.process_query(query_request)

        _ = self._prepare_email_content(request.question, response, request.subject, language)

        return {
            "batch_id": batch_id,
            "thread_id": thread_id,
            "status": "scheduled",
            "email_count": len(request.emails),
            "emails": request.emails,
            "question": request.question,
            "response_preview": response.answer[:500],
            "frequency": request.frequency,
            "include_pdf": request.include_pdf,
            "language": language,
            "created_at": datetime.utcnow().isoformat()
        }

    def _prepare_email_content(self, question: str, response: QueryResponse, subject: Optional[str] = None, language: str = "en") -> str:
        if language == "id":
            return f"""
Subjek: {subject or f"Analisis Ekonomi: {question[:50]}..."}
Penerima yang Terhormat,

Terima kasih telah berlangganan layanan Analisis Ekonomi & Investasi kami.

Pertanyaan: {response.question}

{response.answer}

Waktu Pemrosesan: {response.processing_time:.2f}s
Kepercayaan Diri: {response.confidence_score}

Rekomendasi:
{chr(10).join([f"• {rec}" for rec in (response.recommendations or [])])}
"""
        return f"""
Subject: {subject or f"Economic Analysis: {question[:50]}..."}
Dear Recipient,

Thank you for subscribing to our Economic & Investment Analysis service.

Question: {response.question}

{response.answer}

Processing Time: {response.processing_time:.2f}s
Confidence: {response.confidence_score}

Recommendations:
{chr(10).join([f"• {rec}" for rec in (response.recommendations or [])])}
"""


# ============================================
# API INTEGRATION LAYER
# ============================================

class AgentAPI:
    def __init__(self):
        self.agent = EconomicAdvisorAgent()
        self.batch_processor = BatchEmailProcessor(self.agent)

    def query(self, request: QueryRequest) -> QueryResponse:
        return self.agent.process_query(request)

    def batch_email(self, request: BatchEmailRequest) -> Dict[str, Any]:
        return self.batch_processor.process_batch(request)

    def get_thread_summary(self, thread_id: str) -> Optional[Dict[str, Any]]:
        return self.agent.get_conversation_summary(thread_id)