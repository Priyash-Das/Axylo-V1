"""
Diagnostics / self-test framework for Axylo.

- Provides a registry of diagnostic checks.
- Any feature can register its own check via @register_diagnostic(...)
- GUI can call run_all_diagnostics_sync(...) and render the results.

Statuses:
    ok       -> ✅ everything fine
    warning  -> ⚠️ non-fatal issue / degraded mode
    error    -> ❌ something important is broken
    info     -> ℹ️ purely informational
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import platform
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

import logging

try:
    import src.logger as tlog 
except Exception: 
    tlog = logging.getLogger("diagnostics")

try:
    from src.user_profile import load_user_profile
except Exception:
    load_user_profile = None  

Status = str  

@dataclass
class DiagnosticResult:
    id: str
    status: Status
    message: str
    details: Optional[str] = None

@dataclass
class DiagnosticCheck:
    id: str
    description: str
    func: Callable[[Dict[str, Any]], Any] 

_REGISTRY: List[DiagnosticCheck] = []

def register_diagnostic(id: str, description: str) -> Callable:
    """
    Decorator to register a new diagnostic check.

    Usage in any module:

        from src.diagnostics import register_diagnostic, DiagnosticResult

        @register_diagnostic("my_feature", "Checks my new feature")
        def _check_my_feature(ctx: dict) -> DiagnosticResult:
            ...

    As soon as that module is imported anywhere, the check is auto-registered.
    The diagnostics GUI button will run it without any further changes.
    """
    def decorator(fn: Callable[[Dict[str, Any]], Any]) -> Callable:
        _REGISTRY.append(DiagnosticCheck(id=id, description=description, func=fn))
        return fn
    return decorator

def get_registered_checks() -> List[DiagnosticCheck]:
    return list(_REGISTRY)

async def run_all_diagnostics(context: Optional[Dict[str, Any]] = None) -> List[DiagnosticResult]:
    """
    Run all registered diagnostics and return a list of results.
    Designed to be called from an async context.
    """
    ctx: Dict[str, Any] = context or {}
    results: List[DiagnosticResult] = []

    for check in get_registered_checks():
        try:
            value = check.func(ctx)
            if inspect.isawaitable(value):
                value = await value 

            if not isinstance(value, DiagnosticResult):
                raise TypeError(f"Diagnostic '{check.id}' did not return DiagnosticResult")

            results.append(value)
        except Exception as e:
            results.append(
                DiagnosticResult(
                    id=check.id,
                    status="error",
                    message=f"{check.description} failed with an internal error.",
                    details=str(e),
                )
            )

    return results

def run_all_diagnostics_sync(context: Optional[Dict[str, Any]] = None) -> List[DiagnosticResult]:
    """
    Synchronous wrapper for environments without an event loop.
    Safe to call from a worker thread in the GUI.
    """
    return asyncio.run(run_all_diagnostics(context))

@register_diagnostic("environment", "Basic environment and OS sanity")
def _check_environment(ctx: Dict[str, Any]) -> DiagnosticResult:
    os_name = platform.system()
    python_ver = platform.python_version()
    msg = f"OS={os_name}, Python={python_ver}"
    return DiagnosticResult(id="environment", status="ok", message=msg)

@register_diagnostic("gemini_api", "Gemini / Smart Writer configuration")
def _check_gemini(ctx: Dict[str, Any]) -> DiagnosticResult:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return DiagnosticResult(
            id="gemini_api",
            status="warning",
            message="GEMINI_API_KEY not set; Smart Writer and some LLM tools may not work.",
        )

    try:
        importlib.import_module("google.generativeai")
        return DiagnosticResult(
            id="gemini_api",
            status="ok",
            message="Gemini client available and GEMINI_API_KEY is set.",
        )
    except Exception as e:
        return DiagnosticResult(
            id="gemini_api",
            status="warning",
            message="GEMINI_API_KEY is set but google.generativeai import failed.",
            details=str(e),
        )

@register_diagnostic("google_adk", "Google ADK agent framework availability")
def _check_google_adk(ctx: Dict[str, Any]) -> DiagnosticResult:
    try:
        importlib.import_module("google.adk.runners")
        return DiagnosticResult(
            id="google_adk",
            status="ok",
            message="google.adk.runners import succeeded.",
        )
    except Exception as e:
        return DiagnosticResult(
            id="google_adk",
            status="error",
            message="google.adk.runners is not available; core agent cannot run.",
            details=str(e),
        )

@register_diagnostic("speech_stack", "Speech recognition stack")
def _check_speech(ctx: Dict[str, Any]) -> DiagnosticResult:
    try:
        sr = importlib.import_module("speech_recognition")
        if getattr(sr, "Recognizer", None) is None:
            raise RuntimeError("speech_recognition.Recognizer missing")
        return DiagnosticResult(
            id="speech_stack",
            status="ok",
            message="speech_recognition import OK.",
        )
    except Exception as e:
        return DiagnosticResult(
            id="speech_stack",
            status="warning",
            message="Speech recognition stack not fully available.",
            details=str(e),
        )

@register_diagnostic("tts_stack", "Text-to-speech stack")
def _check_tts(ctx: Dict[str, Any]) -> DiagnosticResult:
    ok_backends = []
    problems = []

    for mod_name, label in [("edge_tts", "Edge TTS"), ("gtts", "gTTS")]:
        try:
            importlib.import_module(mod_name)
            ok_backends.append(label)
        except Exception as e:
            problems.append(f"{label}: {e}")

    if ok_backends:
        return DiagnosticResult(
            id="tts_stack",
            status="ok",
            message=f"TTS backends available: {', '.join(ok_backends)}",
            details="\n".join(problems) if problems else None,
        )

    return DiagnosticResult(
        id="tts_stack",
        status="warning",
        message="No TTS backends (edge_tts / gTTS) could be imported.",
        details="\n".join(problems) if problems else None,
    )

@register_diagnostic("search_engine", "Web search engine")
def _check_search_engine(ctx: Dict[str, Any]) -> DiagnosticResult:
    try:
        from src.search_engine import EnhancedSearchEngine  

        engine = EnhancedSearchEngine(cache_dir=".search_cache", cache_ttl=10)
        if not os.path.isdir(engine.cache_dir):
            return DiagnosticResult(
                id="search_engine",
                status="warning",
                message=f"Search cache directory '{engine.cache_dir}' does not exist or is not a directory.",
            )
        return DiagnosticResult(
            id="search_engine",
            status="ok",
            message="EnhancedSearchEngine import OK and cache directory present.",
        )
    except Exception as e:
        return DiagnosticResult(
            id="search_engine",
            status="warning",
            message="EnhancedSearchEngine could not be initialized.",
            details=str(e),
        )

@register_diagnostic("user_profile", "Persistent user profile")
def _check_user_profile(ctx: Dict[str, Any]) -> DiagnosticResult:
    if load_user_profile is None:
        return DiagnosticResult(
            id="user_profile",
            status="info",
            message="User profile module not available.",
        )
    try:
        profile = load_user_profile()
        if not isinstance(profile, dict):
            raise TypeError("load_user_profile did not return a dict")

        non_empty_keys = [k for k, v in profile.items() if v not in (None, "", [])]
        if non_empty_keys:
            msg = f"Profile loaded with fields: {', '.join(non_empty_keys)}"
            status: Status = "ok"
        else:
            msg = "Profile file present but empty. You can fill it via the 'My profile' button."
            status = "info"

        return DiagnosticResult(
            id="user_profile",
            status=status,
            message=msg,
        )
    except Exception as e:
        return DiagnosticResult(
            id="user_profile",
            status="warning",
            message="Failed to load user profile.",
            details=str(e),
        )

@register_diagnostic("gui_context", "Current GUI / agent runtime state")
def _check_gui_context(ctx: Dict[str, Any]) -> DiagnosticResult:
    agent_running = ctx.get("agent_running")
    mic_enabled = ctx.get("mic_enabled")
    voice_enabled = ctx.get("voice_enabled")

    bits = []
    if agent_running is True:
        bits.append("agent=running")
    elif agent_running is False:
        bits.append("agent=stopped")

    if mic_enabled is True:
        bits.append("mic=on")
    elif mic_enabled is False:
        bits.append("mic=off")

    if voice_enabled is True:
        bits.append("voice=on")
    elif voice_enabled is False:
        bits.append("voice=off")

    msg = ", ".join(bits) if bits else "No GUI context provided."
    return DiagnosticResult(
        id="gui_context",
        status="info",
        message=msg,
    )





# Place the code inside the module of the specific feature to diagnose.

# from src.diagnostics import register_diagnostic, DiagnosticResult

# @register_diagnostic("my_new_feature", "Checks my new feature health")
# def _check_my_feature(ctx: dict) -> DiagnosticResult:
#     # run whatever tests you want
#     return DiagnosticResult(
#         id="my_new_feature",
#         status="ok",
#         message="My feature looks good.",
#     )
