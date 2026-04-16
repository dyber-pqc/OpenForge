"""Local-LLM AI helpers (Ollama client, hardware-design skills)."""

from openforge.ai.ollama_client import OllamaClient  # noqa: F401
from openforge.ai.skills import (  # noqa: F401
    SKILLS,
    AiContext,
    AiSkill,
)

__all__ = ["OllamaClient", "AiSkill", "AiContext", "SKILLS"]
