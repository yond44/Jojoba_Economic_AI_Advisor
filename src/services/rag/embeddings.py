"""Embedding + LLM setup — extracted from the original rag.py."""
from __future__ import annotations

import os
import logging

from llama_index.llms.groq import Groq
from llama_index.embeddings.fastembed import FastEmbedEmbedding

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


def setup_llm():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not found")
    return Groq(model=get_settings().groq_model, api_key=api_key)


def setup_embeddings():
    return FastEmbedEmbedding(model_name=get_settings().embedding_model)
