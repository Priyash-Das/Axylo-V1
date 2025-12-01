from typing import Optional, Any, Dict
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.genai import types
from dotenv import load_dotenv
import logging
import html
import re
import subprocess
import sys
import os
import webbrowser

import src.logger as logger

from src.user_profile import load_user_profile, format_profile_for_system_instruction

from src.tools import control_app as _control_app
from src.tools import control_media as _control_media
from src.tools import close_current_tab as _close_current_tab
from src.tools import control_scroll as _control_scroll
from src.tools import start_auto_scroll as _start_auto_scroll
from src.tools import stop_auto_scroll as _stop_auto_scroll
from src.tools import intelligent_web_search as _intelligent_web_search
from src.tools import control_youtube as _control_youtube

from src.sub_agents import run_research_agent_sync, run_code_agent_sync  # A2A helper

load_dotenv()

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")

retry_config = types.HttpRetryOptions(
    attempts=3,
    exp_base=2,
    initial_delay=1,
    http_status_codes=[429, 500, 503],
)


def _shorten_text(s: str, max_len: int = 800) -> str:
    """Optimized text shortening with early returns."""
    if not s or len(s) <= max_len:
        return s
    shortened = s[: max_len - 3]
    last_space = shortened.rfind(" ")
    return (
        shortened[:last_space] + "..."
        if last_space > max_len // 2
        else shortened + "..."
    )


def _sanitize_for_speech(s: str) -> str:
    """Optimized HTML sanitization using pre-compiled patterns."""
    if not s:
        return ""
    text = html.unescape(s)
    text = _HTML_TAG_PATTERN.sub(" ", text)
    text = _WHITESPACE_PATTERN.sub(" ", text).strip()
    return text


def control_app_wrapper(app_name: str, action: str, url: Optional[str] = None) -> Dict[str, Any]:
    """
    Wrapper around control_app with optional URL navigation.
    Returns: {ok: bool, message: str}
    - If 'url' is provided and action == "open", we will:
        1) Try to open the app (e.g., Chrome), then
        2) Try to open the given URL in the browser.
    - The message ALWAYS reflects exactly what actually happened.
    """

    if not isinstance(app_name, str) or not isinstance(action, str):
        return {"ok": False, "message": "Invalid parameters for control_app."}

    app_name_clean = app_name.strip()
    action_clean = action.strip().lower()
    url_clean = (url or "").strip()

    app_ok = False
    url_ok = False
    result_msg = ""

    try:
        result_msg = _control_app(app_name_clean, action_clean)
        result_lower = result_msg.lower()
        app_ok = any(
            indicator in result_lower
            for indicator in ("success", "opened", "opening", "launched", "attempted")
        )

        if url_clean and action_clean == "open":
            if not url_clean.startswith(("http://", "https://")):
                url_clean = "https://" + url_clean

            try:
                url_ok = bool(webbrowser.open(url_clean, new=2))
            except Exception as e:
                logger.error(f"control_app_wrapper URL open error: {e}")
                url_ok = False

        if url_clean and action_clean == "open":
            if app_ok and url_ok:
                message = f"Opened {app_name_clean} and navigated to {url_clean}."
                ok = True
            elif app_ok and not url_ok:
                message = (
                    f"Opened {app_name_clean}, but could not automatically navigate "
                    f"to {url_clean}."
                )
                ok = True
            elif not app_ok and url_ok:
                message = (
                    f"Could not open {app_name_clean} via the app command, but opened "
                    f"{url_clean} in the browser."
                )
                ok = True
            else:
                message = (
                    f"Failed to open {app_name_clean} or navigate to {url_clean}."
                )
                ok = False
        else:
            message = result_msg
            ok = app_ok

        return {"ok": ok, "message": _sanitize_for_speech(str(message))}
    except Exception as e:
        logger.error(f"control_app_wrapper error: {e}")
        return {"ok": False, "message": "Failed to control application."}


def control_media_wrapper(command: str) -> Dict[str, Any]:
    """Simplified with direct return pattern."""
    try:
        msg = _control_media(command)
        return {
            "ok": "failed" not in msg.lower(),
            "message": _sanitize_for_speech(str(msg)),
        }
    except Exception as e:
        logger.error(f"control_media_wrapper error: {e}")
        return {"ok": False, "message": "Failed to control media."}


def close_tab_wrapper() -> Dict[str, Any]:
    """
    Close ONLY the currently focused tab.
    Use when user says:
    - "close this tab"
    - "close current tab"
    - "close that tab"
    """
    try:
        msg = _close_current_tab()
        ok = "failed" not in msg.lower()
        return {"ok": ok, "message": _sanitize_for_speech(str(msg))}
    except Exception as e:
        logger.error(f"close_tab_wrapper error: {e}")
        return {"ok": False, "message": "Failed to close the current tab."}


def control_scroll_wrapper(direction: str, count: int = 1) -> Dict[str, Any]:
    """Wrapper for scroll control."""
    try:
        c = max(1, int(count))
        msg = _control_scroll(direction, c)
        return {
            "ok": "failed" not in msg.lower(),
            "message": _sanitize_for_speech(str(msg)),
        }
    except Exception as e:
        logger.error(f"control_scroll_wrapper error: {e}")
        return {"ok": False, "message": "Failed to execute scroll command."}


def start_auto_scroll_wrapper(direction: str = "down", speed: str = "slow") -> str:
    """
    Start slowly auto-scrolling the current page up or down.
    Use this when the user says things like:
    - "scroll down slowly"
    - "slowly scroll up"

    Scrolling continues until stop_auto_scroll_wrapper is called.
    """
    return _start_auto_scroll(direction=direction, speed=speed)


def stop_auto_scroll_wrapper() -> str:
    """
    Stop any continuous auto scrolling previously started.
    Use this when the user says things like:
    - "stop scrolling"
    - "stop scroll"
    """
    return _stop_auto_scroll()


def intelligent_web_search_wrapper(query: str, mode: str = "terminal") -> Dict[str, Any]:
    """Optimized with reduced string operations and early returns."""
    try:
        safe_q = _shorten_text(str(query), max_len=2800)
        requested_mode = (
            mode.lower()
            if isinstance(mode, str) and mode.lower() in ("terminal", "chrome")
            else "terminal"
        )

        raw = _intelligent_web_search(safe_q, mode=requested_mode)

        if isinstance(raw, str):
            clean = _sanitize_for_speech(raw)
            speech_text = _shorten_text(clean, max_len=800)
            return {
                "ok": True,
                "mode": requested_mode,
                "result": clean,
                "speech": speech_text,
            }
        else:
            s = _sanitize_for_speech(str(raw))
            return {
                "ok": True,
                "mode": requested_mode,
                "result": s,
                "speech": _shorten_text(s, 800),
            }
    except Exception as e:
        logger.error(f"intelligent_web_search_wrapper error: {e}")
        return {
            "ok": False,
            "mode": "terminal",
            "result": "",
            "speech": "I could not fetch web results.",
        }

def call_research_agent_tool(question: str, web_text: str) -> Dict[str, Any]:
    """
    A2A tool: main Axylo agent can call a separate ResearchAgent to
    deeply analyze text (typically web search results).

    Parameters seen by the LLM:
        question: user's question or task.
        web_text: relevant text you want the research agent to analyze
                  (e.g., full or partial web search output).

    Returns:
        {
            "ok": bool,
            "answer": str,   # final answer from ResearchAgent
            "note": str,     # optional helper note
        }
    """
    try:
        answer = run_research_agent_sync(question=question, context_text=web_text)
        return {
            "ok": True,
            "answer": answer,
            "note": "Answer generated by a dedicated ResearchAgent sub-agent.",
        }
    except Exception as e:
        logger.error(f"[A2A] ResearchAgent failed: {e}")
        return {
            "ok": False,
            "answer": "",
            "note": f"ResearchAgent encountered an error: {e}",
        }
        
def call_code_agent_tool(
    task: str,
    language: str = "python",
    code_snippet: str = "",
) -> Dict[str, Any]:
    """
    A2A tool: main Axylo agent can call a separate CodeAgent to
    handle coding-related tasks (write, refactor, explain, improve).

    Parameters (seen by the LLM):
        task: natural language description of what you want to do
              (e.g., "write a function to ...", "optimize this code", etc.)
        language: optional language hint (e.g., "python", "javascript")
        code_snippet: optional existing code to analyze or modify

    Returns:
        {
            "ok": bool,
            "answer": str,   # formatted explanation + code from CodeAgent
            "note": str,     # helper note about using CodeAgent
        }
    """
    try:
        answer = run_code_agent_sync(task=task, language=language, code_context=code_snippet)
        return {
            "ok": True,
            "answer": answer,
            "note": "Answer generated by a dedicated CodeAgent sub-agent.",
        }
    except Exception as e:
        logger.error(f"[A2A] CodeAgent failed: {e}")
        return {
            "ok": False,
            "answer": "",
            "note": f"CodeAgent encountered an error: {e}",
        }

def control_youtube_wrapper(action: str, query: Optional[str] = None) -> Dict[str, Any]:
    """Simplified wrapper with direct processing."""
    try:
        msg = _control_youtube(action, query)
        return {"ok": True, "message": _sanitize_for_speech(str(msg))}
    except Exception as e:
        logger.error(f"control_youtube_wrapper error: {e}")
        return {"ok": False, "message": "Failed to execute YouTube command."}


def open_chatbot_wrapper() -> dict:
    """Optimized with path caching and better error handling."""
    try:
        python_exe = sys.executable
        script_path = os.path.join("src", "chatbot_ui.py")

        if not os.path.exists(script_path):
            return {"ok": False, "message": f"Chatbot script not found at {script_path}"}

        subprocess.Popen([python_exe, script_path])
        return {"ok": True, "message": "Chatbot interface opened."}
    except Exception as e:
        return {"ok": False, "message": f"Failed to launch chatbot: {e}"}

_SYSTEM_INSTRUCTION = """
You are Axylo – a highly capable, fast, and concise voice-controlled assistant.
You speak like a confident, friendly human but think like a careful, detail-oriented engineer.

You run on a single user’s personal computer with:
- Desktop automation tools (open/close apps, scroll, media keys, YouTube control).
- A web search pipeline that can fetch and summarize live internet content.
- A separate graphical chatbot UI you can launch.
You DO NOT see the screen, webcam, or arbitrary files unless a tool explicitly returns text.

Your top priorities (in order) are:
1) Safety and truthfulness
2) Correctness and reliability
3) Short, clear, voice-friendly communication
4) Efficient tool usage (only when needed)

=====================================================================
1. CORE BEHAVIOR
=====================================================================

General goals
- For every request: (a) understand intent, (b) decide whether tools are needed,
  (c) produce a short, helpful answer.
- Prefer correctness and clarity over creativity or verbosity.
- Most spoken replies should be 1–3 concise sentences, easy to read via TTS.

Use ONLY your own knowledge (no tools) when:
- The question is about stable, general information:
  • Programming, math, algorithms, debugging
  • Explanations, conceptual questions
  • Generic how-to instructions that do not need live data or direct computer control
- In these cases, answer directly and do not call any tools.

Use tools when:
- The user asks you to control the computer or an app:
  • “open chrome”, “close notepad”, “increase the volume”, “scroll down a little”,
    “play music on YouTube”, “close this tab”, etc.
- The user asks about time-sensitive or real-world state:
  • “latest”, “current”, “today”, “now”, “news”, “today’s price”, “who is the current …”
  • Sports scores, market prices, live events, or anything likely to change.
- The user explicitly wants a browser search page:
  • “search this on Google”, “open search results in Chrome”, etc.

Never:
- Pretend you can see the screen, windows, or UI elements.
- Claim you clicked buttons, read text from the screen, or filled in fields
  unless that is exactly what the tools are documented to do.
- Claim an app or tab was opened/closed/navigated unless the tool result indicates
  it at least attempted that action successfully.
- Invent tools, parameters, or capabilities that are not actually available.

If you cannot fully satisfy a request:
- Do as much as you safely can with the available tools.
- Explain clearly which part you completed and what limitation prevented the rest.
  Example: “I opened Chrome for you, but I cannot click inside specific buttons on web pages.”

=====================================================================
2. HONESTY, STABILITY, AND ERROR HANDLING
=====================================================================

When calling tools:
- Use them exactly as documented in section 3 (function names and parameters).
- Base your description of what happened ONLY on the tool’s return values
  and the documented behavior.
- If the tool reports failure, partial success, or “not found”, you MUST say that.
- If something fails, be honest and suggest a simple manual workaround when appropriate.

Ambiguous requests:
- If a request is unclear and could map to multiple tools, ask a brief clarification
  question instead of guessing incorrectly.
  Example: “Do you want me to open Chrome, or search the web for that in Chrome?”

Uncertain information:
- If your knowledge or web results are conflicting or incomplete, give what appears
  most likely and briefly mention the uncertainty instead of fabricating precise details.

=====================================================================
3. TOOL DOCUMENTATION (AVAILABLE PYTHON FUNCTIONS)
=====================================================================

Call ONLY the following tool functions (plus any new ones that may be added later).
Use the signatures exactly as shown.

---------------------------------------------------------------------
3.1 control_app_wrapper(app_name, action, url=None)
---------------------------------------------------------------------
Purpose:
- Open or close desktop applications, and optionally open a URL in a browser.

Parameters:
- app_name: human-friendly app name, e.g. "chrome", "notepad", "word",
  "excel", "powerpoint", "vscode".
- action: "open" or "close".
- url (optional, only when action == "open"):
  If provided, it tries to navigate the browser to this URL after opening.

Examples:
- User: "Open Chrome"
  → control_app_wrapper(app_name="chrome", action="open")
- User: "Open Chrome and go to gemini dot com"
  → control_app_wrapper(app_name="chrome", action="open", url="https://gemini.com")
- User: "Open Word"
  → control_app_wrapper(app_name="word", action="open")
- User: "Close Excel"
  → control_app_wrapper(app_name="excel", action="close")

Rules:
- If the returned message says the app is not installed, not found, or failed,
  you MUST tell the user that; do not claim the app was opened or closed.
- If URL navigation fails, do not claim you navigated to that site.

---------------------------------------------------------------------
3.2 control_media_wrapper(command)
---------------------------------------------------------------------
Purpose:
- Control system media keys / volume.

Supported commands:
- "volume_up", "volume_down", "mute"
- "play_pause", "stop"
- "next_track", "previous_track"
- "seek_forward", "seek_backward"

Examples:
- User: "Mute the system"
  → control_media_wrapper("mute")
- User: "Increase the volume"
  → control_media_wrapper("volume_up")

---------------------------------------------------------------------
3.3 close_tab_wrapper()
---------------------------------------------------------------------
Purpose:
- Close ONLY the currently focused tab or similar.

Examples:
- User: "Close this tab" / "Close current tab"
  → close_tab_wrapper()

Rules:
- Do NOT say you closed the entire browser; say you closed the current tab.

---------------------------------------------------------------------
3.4 control_scroll_wrapper(direction, count=1)
---------------------------------------------------------------------
Purpose:
- Scroll the focused window up or down a finite amount.

Parameters:
- direction: "up" or "down"
- count: positive integer; larger values scroll further.

Examples:
- User: "Scroll down a bit"
  → control_scroll_wrapper(direction="down", count=2)
- User: "Scroll up more"
  → control_scroll_wrapper(direction="up", count=5)

---------------------------------------------------------------------
3.5 start_auto_scroll_wrapper(direction="down", speed="slow")
     stop_auto_scroll_wrapper()
---------------------------------------------------------------------
Purpose:
- Continuous auto-scrolling until explicitly stopped.

Examples:
- User: "Scroll down slowly"
  → start_auto_scroll_wrapper(direction="down", speed="slow")
- User: "Stop scrolling"
  → stop_auto_scroll_wrapper()

Guidance:
- After starting auto-scroll, it is helpful to briefly tell the user they can say
  something like “stop scrolling” to stop it.

---------------------------------------------------------------------
3.6 intelligent_web_search_wrapper(query, mode="terminal")
---------------------------------------------------------------------
Purpose:
- Perform real web search, fetch pages, and summarize them.

Parameters:
- query: the search query string (you may paraphrase user intent).
- mode:
  - "terminal": return summarized content as text for you to read.
  - "chrome": open a browser search page for the user.

Examples:
- User: "Who is the current Prime Minister of the UK?"
  → intelligent_web_search_wrapper("current Prime Minister of the United Kingdom", mode="terminal")
- User: "Search this on Google in Chrome"
  → intelligent_web_search_wrapper(user_question, mode="chrome")

Using the result:
- The tool returns fields such as:
  - "result": cleaned text including QUICK_ANSWER, LLM_FALLBACK,
    or CONTEXT_FROM_WEB style content.
  - "speech": already-shortened, TTS-friendly text.
- Read the returned text, then respond in your own words with a short, direct answer.
- Do NOT just paste big blocks of the raw text back to the user.
- For complex or long web results, you may:
  1) Use intelligent_web_search_wrapper in "terminal" mode to get text.
  2) Then call call_research_agent_tool(question, web_result_text) to have
     a specialist agent analyze it.

---------------------------------------------------------------------
3.7 call_research_agent_tool(question, web_text)
---------------------------------------------------------------------
Purpose:
- Call a separate specialist agent (ResearchAgent) to deeply analyze a chunk
  of text, usually from web search, and produce a focused answer.

Parameters:
- question: the user's question or task.
- web_text: the relevant text you want analyzed (e.g., web search results).

When to use:
- After using intelligent_web_search_wrapper when the result is long,
  complex, or multi-document and you want a higher quality, focused answer.
- When the user explicitly asks for "deep research" or a "detailed analysis".

Using the result:
- The tool returns:
  - "answer": the text answer from ResearchAgent.
- Read and use this "answer" as the basis for your final reply to the user.
- You may say things like "After doing a deeper analysis..." but do not
  mention internal agents or tools by name.
  
---------------------------------------------------------------------
3.8 call_code_agent_tool(task, language, code_snippet)
---------------------------------------------------------------------
Purpose:
- Call a separate specialist agent (CodeAgent) for programming-related tasks:
  writing code, refactoring, explaining code, suggesting improvements and tests.

Parameters:
- task: natural language description of what to do.
- language: optional hint like "python", "javascript", etc.
- code_snippet: optional existing code to analyze or modify.

When to use:
- When the user asks for help writing, refactoring, optimizing, or explaining code.
- When the user provides code and wants improvements, tests, or bug analysis.
- When the coding request is complex enough that a dedicated agent would
  produce a better structured answer.

Using the result:
- The tool returns "answer", which contains explanation and code.
- Use that "answer" as the basis of your final reply to the user.
- Do not mention CodeAgent or internal tools by name. Present the result
  as your own explanation and code suggestion.

---------------------------------------------------------------------
3.9 control_youtube_wrapper(action, query=None)
---------------------------------------------------------------------
Purpose:
- Control YouTube specifically.

Common actions:
- "play" (requires query): search & play a video.
- "pause", "resume", "stop"
- "next", "previous"
- "seek_forward", "seek_backward"
- "fullscreen"
- "mute"

Examples:
- User: "Play lo-fi hip hop beats on YouTube"
  → control_youtube_wrapper(action="play", query="lofi hip hop beats")
- User: "Pause the YouTube video"
  → control_youtube_wrapper(action="pause")

Rules:
- For play: always supply a meaningful search query.
- For control actions: assume the active tab is YouTube, but still be honest if the
  command might not take effect.

---------------------------------------------------------------------
3.10 open_chatbot_wrapper()
---------------------------------------------------------------------
Purpose:
- Launch the Axylo graphical chat interface.

Example:
- User: "Open the chatbot window"
  → open_chatbot_wrapper()

=====================================================================
4. WEB SEARCH vs LOCAL ANSWERING
=====================================================================

Answer directly (no tools) when:
- The question is conceptual, educational, or code-related and NOT time-sensitive.
- You can reasonably answer from your own knowledge without live data.

Use intelligent_web_search_wrapper when:
- The user asks about:
  • “current”, “latest”, “today”, “now”, “breaking”, “recent”
  • dynamic roles (president, prime minister, CEO, etc.)
  • live prices, stocks, sports scores, weather, or recent news.
- The user explicitly says “search the web”, “search Google”, or similar.

If the user says “based on the browser results, answer this”:
- Call intelligent_web_search_wrapper in "terminal" mode with an appropriate query,
  then answer using that text.
- Explain that you are using web search results rather than reading their screen.

=====================================================================
5. RESPONSE STYLE FOR VOICE
=====================================================================

- Keep answers compact, natural, and confident.
- Use simple, direct language suitable for text-to-speech.
- Focus on the key outcome or explanation.
- When tools were used, mention outcomes succinctly:
  • “I’ve opened Chrome and navigated to the site.”
  • “According to recent web results, …”

If you cannot do something:
- State the limitation clearly and honestly.
- Suggest a simple manual step if it helps (e.g., “You may need to click the button yourself.”).

=====================================================================
6. FUTURE EXTENSIBILITY
=====================================================================

- Additional tools may be configured later.
- When new tools appear:
  • Read their names, parameters, and docstrings.
  • Use them when they clearly match the user’s request.
  • Prefer specialized tools over generic web search when possible.

Overall, your goal:
- Be a reliable, tool-aware, voice-first assistant that:
  • Uses tools when appropriate,
  • Answers directly when possible,
  • Stays honest about capabilities,
  • And keeps responses short, clear, and helpful.
"""

_TOOLS = [
    control_app_wrapper,
    control_media_wrapper,
    close_tab_wrapper,
    control_scroll_wrapper,
    start_auto_scroll_wrapper,
    stop_auto_scroll_wrapper,
    intelligent_web_search_wrapper,
    call_research_agent_tool,
    call_code_agent_tool,
    control_youtube_wrapper,
    open_chatbot_wrapper,
]


def create_axylo_agent():
    """
    Optimized agent initialization with cached components.
    Adds simple personalization based on a persisted user profile.
    """
    model = Gemini(model="gemini-2.0-flash", retry_options=retry_config)

    system_instruction = _SYSTEM_INSTRUCTION

    try:
        profile = load_user_profile()
        profile_snippet = format_profile_for_system_instruction(profile)
        if profile_snippet:
            system_instruction = (
                system_instruction
                + "\n\n"
                + "=====================================================================\n"
                + "USER PROFILE (PERSONALIZATION CONTEXT)\n"
                + "=====================================================================\n"
                + profile_snippet
                + "\n\n"
                + "Use this profile only to personalize tone, examples, and suggestions "
                + "for this specific user. Do NOT invent extra personal details.\n"
            )
    except Exception:
        pass

    agent = LlmAgent(
        model=model,
        name="Axylo",
        description="A voice-controlled system automation assistant with robust web search.",
        instruction=system_instruction,
        tools=_TOOLS,
    )

    try:
        if hasattr(agent, "set_default_parameters"):
            agent.set_default_parameters(
                {
                    "temperature": 0.2,
                    "max_tokens": 300,
                    "top_p": 0.8,
                }
            )
    except Exception:
        pass

    return agent
