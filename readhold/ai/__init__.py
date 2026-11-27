"""The AI layer. Milestones 1.1 and 1.2 of docs/ai/PLAN.md: the LLM port, its adapters, profiles, key storage, the AI log and the guardrails.

Twelve features exist: the Resume briefing (`resume.py`), Explain selection (`explain.py`), the digest (`digest.py`),
Ask this document (`ask.py`), Ask my library (`library.py`), Study notes (`notes.py`), the reading plan (`plan.py`),
Brainstorm (`brainstorm.py`), Organize (`organize.py`), Tidy (`tidy.py`), the Plan chat (`chat.py`) and the note
chat (`notechat.py`). Each has a
version without a model. A feature calls
`guard.ask(...)`, which runs every guard and then `port.complete(...)`; it never sees a provider, a key or an HTTP client.

- `port.py`      the port: off switch, profiles, timeout, one retry, output cap, 2 at once, daily budget, cancel
- `adapters.py`  the only file in Readhold that may open a network connection (Ollama, OpenAI-compatible, Anthropic, OpenAI)
- `profiles.py`  per-task model profiles (`profiles.json`, changes in `data/ai_profiles.json`)
- `keys.py`      API keys, in the operating system's credential store only
- `settings.py`  the `ai_*` settings and their checks
- `log.py`       the `ai_log` table: one row per call, kept 1, 7 or 30 days, "Clear AI history"
- `api.py`       the `/api/ai/...` routes of the Settings page
- `guard.py`     milestone 1.2: what may reach a model and what may come back (fencing, budgets, secrets, citations)
- `prompts.py`   the prompt registry: one file per version in `prompts/`
- `resume.py`    milestone 1.3, the first feature: "where you left off" (facts without a model, a recap with one)
"""
from . import ask, brainstorm, chat, digest, explain, guard, keys, library, log, notechat, notes, organize, plan, privacy, profiles, prompts, results, resume, settings, tidy
from .adapters import MAX_REPLY_BYTES, endpoint_warning
from .api import register
from .port import (
    AIError,
    AIOff,
    BudgetReached,
    Cancelled,
    CouldNotGenerate,
    NoKey,
    NotSetUp,
    Port,
    ProviderError,
    Reply,
    TimedOut,
    TooLong,
)

__all__ = [
    "AIError", "AIOff", "BudgetReached", "Cancelled", "CouldNotGenerate", "MAX_REPLY_BYTES", "NoKey", "NotSetUp", "Port",
    "ProviderError", "Reply", "TimedOut", "TooLong", "endpoint_warning", "keys", "log", "privacy", "profiles", "register", "settings",
]
