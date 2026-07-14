"""Agent runtime tunables — sourced from Settings (previously scattered
os.getenv calls at the top of the monolith). Single source of truth."""
from src.config.settings import get_settings

_s = get_settings()

MAX_CONTEXTS = _s.max_conversation_contexts
CONTEXT_TTL_HOURS = _s.context_ttl_hours
MAX_AGENT_STEPS = _s.max_agent_steps
