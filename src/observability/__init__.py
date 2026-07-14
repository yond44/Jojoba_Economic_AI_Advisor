"""Observability package: tracing + span helpers."""
from src.observability.tracing import setup_tracing, traced, get_tracer, add_span_attrs

__all__ = ["setup_tracing", "traced", "get_tracer", "add_span_attrs"]
