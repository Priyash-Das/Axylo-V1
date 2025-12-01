import os
import platform
import logging
import time
import subprocess
import shlex
import webbrowser
from enum import Enum
from typing import Dict, Any, Optional, List
from urllib.parse import quote_plus
import pyautogui
import requests
import threading

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

import src.logger as tlog   

from src.app_launcher import launcher

_auto_scroll_thread = None
_auto_scroll_stop_event = threading.Event()

from src.search_engine import EnhancedSearchEngine

search_engine = EnhancedSearchEngine(cache_dir=".search_cache", cache_ttl=3600)

logger = logging.getLogger("Tools")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

APP_COMMANDS = {
    "Windows": {
        "chrome": ["cmd", "/c", "start", "chrome"],
        "youtube": ["cmd", "/c", "start", "chrome", "https://youtube.com"],
        "notepad": ["notepad"],
        "word": ["cmd", "/c", "start", "winword"],
        "excel": ["cmd", "/c", "start", "excel"],
        "powerpoint": ["cmd", "/c", "start", "powerpnt"],
        "vscode": ["cmd", "/c", "start", "Code"],
    },
    "Darwin": {
        "chrome": ["open", "-a", "Google Chrome"],
        "youtube": ["open", "https://youtube.com"],
        "notepad": ["open", "-a", "TextEdit"],
        "word": ["open", "-a", "Microsoft Word"],
        "excel": ["open", "-a", "Microsoft Excel"],
        "powerpoint": ["open", "-a", "Microsoft PowerPoint"],
    },
    "Linux": {
        "chrome": ["google-chrome"],
        "youtube": ["xdg-open", "https://youtube.com"],
        "notepad": ["gedit"],
        "word": ["libreoffice", "--writer"],
        "excel": ["libreoffice", "--calc"],
        "powerpoint": ["libreoffice", "--impress"],
    },
}

APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "browser": "chrome",
    "youtube": "youtube",
    "yt": "youtube",
    "notepad": "notepad",
    "note pad": "notepad",
    "text editor": "notepad",

    "word": "word",
    "ms word": "word",
    "microsoft word": "word",
    "winword": "word",

    "excel": "excel",
    "microsoft excel": "excel",

    "powerpoint": "powerpoint",
    "power point": "powerpoint",
    "microsoft powerpoint": "powerpoint",
    "ppt": "powerpoint",

    "vs code": "vscode",
    "vscode": "vscode",
    "visual studio code": "vscode",
}

WINDOWS_PROCESS_NAMES = {
    "chrome": "chrome.exe",
    "youtube": "chrome.exe",   
    "notepad": "notepad.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "vscode": "Code.exe",
}

def _normalize_app_name(app_name: str) -> str:
    return (app_name or "").strip().lower()

def _resolve_app_key(app_name: str) -> Optional[str]:
    """
    Map a user-friendly app name (e.g. 'Microsoft Word', 'Open Excel app')
    to a whitelisted internal key, or return None if not allowed/available.

    This implements the "whitelist" concept: only apps present in
    APP_COMMANDS for the current OS (optionally via APP_ALIASES) are allowed.
    """
    raw = _normalize_app_name(app_name)

    for suffix in (" app", " application"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)].strip()

    os_key = _get_os_key()
    mapping = APP_COMMANDS.get(os_key, APP_COMMANDS["Windows"])

    if raw in APP_ALIASES:
        candidate = APP_ALIASES[raw]
        if candidate in mapping:
            return candidate
        return None

    if raw in mapping:
        return raw

    return None

def _get_os_key() -> str:
    p = platform.system()
    if p == "Darwin":
        return "Darwin"
    if p == "Linux":
        return "Linux"
    return "Windows"

def _get_os_cmd_list(
    app_key: str,
    additional_args: Optional[List[str]] = None,
) -> Optional[List[str]]:
    """
    Return a list of command arguments for subprocess.run based on OS mapping.
    additional_args (list of strings) will be appended safely.
    """
    os_key = _get_os_key()
    mapping = APP_COMMANDS.get(os_key, APP_COMMANDS["Windows"])
    cmd = mapping.get(app_key)
    if not cmd:
        return None
    cmd_list = list(cmd)
    if additional_args:
        cmd_list.extend([str(x) for x in additional_args])
    return cmd_list

def _run_cmd(cmd_list: List[str], timeout: int = 6) -> bool:
    """
    Run the command list safely using subprocess.run. Returns True on success.
    Non-fatal errors return False.
    """
    try:
        subprocess.run(cmd_list, check=False, timeout=timeout)
        logger.debug("Ran command: %s", cmd_list)
        return True
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out: %s", cmd_list)
        return False
    except FileNotFoundError:
        logger.warning("Executable not found for command: %s", cmd_list)
        return False
    except Exception as e:
        logger.exception("Error running command %s: %s", cmd_list, e)
        return False

def control_app(app_name: str, action: str) -> str:
    """
    Open or close an app.

    Logic:
    1. 'Close': Only allows apps in your Static Whitelist (Safe).
    2. 'Open':
       a. Tries Static Whitelist first (Fast & Accurate).
       b. If not found, tries Dynamic App Launcher (Scalable).
    """
    app_name_clean = (app_name or "").strip()
    action = (action or "").lower().strip()

    app_key = _resolve_app_key(app_name_clean)

    if action == "close":
        if app_key:
            try:
                if platform.system() == "Windows":
                    exe_name = WINDOWS_PROCESS_NAMES.get(app_key, f"{app_key}.exe")
                    _run_cmd(["taskkill", "/f", "/im", exe_name])

                    if app_key == "youtube":
                        _run_cmd(["taskkill", "/f", "/im", "chrome.exe"])
                else:
                    _run_cmd(["pkill", "-f", app_key])
                    if app_key == "youtube":
                        _run_cmd(["pkill", "-f", "chrome"])

                msg = f"Attempted to close {app_name_clean}."
                logger.info(msg)
                tlog.tools(msg)
                return msg
            except Exception as e:
                logger.error(f"Failed to close {app_name_clean}: {e}")
                return f"Error closing {app_name_clean}."

        logger.info(
            f"'{app_name_clean}' not configured in close whitelist. "
            f"Trying dynamic close via AppLauncher."
        )
        success, dyn_msg = launcher.find_and_close(app_name_clean)

        if success:
            tlog.tools(dyn_msg)
            return dyn_msg

        return (
            "I can only close applications I can safely identify by their process name. "
            + dyn_msg
        )

    if action == "open":
        if app_key:
            cmd_list = _get_os_cmd_list(app_key)
            if cmd_list:
                ok = _run_cmd(cmd_list)
                if ok:
                    msg = f"Opened {app_name_clean} (Standard)."
                    logger.info(msg)
                    tlog.tools(msg)
                    return msg

                try:
                    last_arg = cmd_list[-1]
                    if last_arg.startswith("http"):
                        webbrowser.open(last_arg, new=2)
                        return f"Opened {app_name_clean} via browser."
                except Exception:
                    pass

        logger.info(
            f"'{app_name_clean}' not in whitelist (or failed). "
            f"Searching installed apps..."
        )

        found, message = launcher.find_and_launch(app_name_clean)

        if found:
            msg = f"Opened {app_name_clean}."
            logger.info(msg)
            tlog.tools(msg)
            return msg

        msg = (
            f"I couldn't find an app named '{app_name_clean}' "
            f"installed on this computer."
        )
        logger.warning(msg)
        return msg

    return "Invalid action. Use 'open' or 'close'."

class MediaCommand(Enum):
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    PLAY_PAUSE = "play_pause"
    STOP = "stop"
    NEXT_TRACK = "next_track"
    PREVIOUS_TRACK = "previous_track"
    SEEK_FORWARD = "seek_forward"
    SEEK_BACKWARD = "seek_backward"

COMMAND_MAPPINGS = {
    MediaCommand.VOLUME_UP: "volumeup",
    MediaCommand.VOLUME_DOWN: "volumedown",
    MediaCommand.MUTE: "volumemute",
    MediaCommand.PLAY_PAUSE: "playpause",
    MediaCommand.STOP: "stop",
    MediaCommand.NEXT_TRACK: "nexttrack",
    MediaCommand.PREVIOUS_TRACK: "prevtrack",
    MediaCommand.SEEK_FORWARD: "right",
    MediaCommand.SEEK_BACKWARD: "left",
}

MEDIA_RESPONSES = {
    MediaCommand.VOLUME_UP: "Volume increased",
    MediaCommand.VOLUME_DOWN: "Volume decreased",
    MediaCommand.MUTE: "System audio muted/unmuted",
    MediaCommand.PLAY_PAUSE: "Playback toggled",
    MediaCommand.STOP: "Playback stopped",
    MediaCommand.NEXT_TRACK: "Next track",
    MediaCommand.PREVIOUS_TRACK: "Previous track",
    MediaCommand.SEEK_FORWARD: "Skipped forward 10 seconds",
    MediaCommand.SEEK_BACKWARD: "Rewound 10 seconds",
}

def control_media(command: str) -> str:
    normalized = (command or "").lower().strip()
    try:
        media_cmd = MediaCommand(normalized)
    except ValueError:
        msg = f"Invalid media command: {command}"
        logger.warning(msg)
        tlog.tools(msg)
        return f"{msg}. Supported: {[c.value for c in MediaCommand]}"

    key = COMMAND_MAPPINGS.get(media_cmd)
    try:
        pyautogui.press(key)
        return MEDIA_RESPONSES[media_cmd]
    except Exception as e:
        msg = f"Failed to execute media command {command}: {e}"
        logger.exception(msg)
        tlog.error(msg)
        return msg

def close_current_tab() -> str:
    """
    Close ONLY the currently focused tab/window using the standard shortcut:
    - Windows/Linux: Ctrl + W
    - macOS: Command + W

    Works for Chrome, Edge, VS Code, etc., as long as that window has focus.
    """
    try:
        os_type = platform.system()
        if os_type == "Darwin":  
            pyautogui.hotkey("command", "w")
        else:  
            pyautogui.hotkey("ctrl", "w")

        msg = "Closed the current tab."
        logger.info(msg)
        tlog.tools(msg)
        return msg
    except Exception as e:
        msg = f"Failed to close the current tab: {e}"
        logger.exception(msg)
        tlog.error(msg)
        return msg

def control_scroll(direction: str, count: int = 1) -> str:
    """
    Scroll the currently focused window using real mouse-wheel events.

    - direction: 'up' or 'down'
    - count: how many scroll "steps" to perform (higher = further)

    Uses pyautogui.scroll() so it works across websites (YouTube, GitHub, docs, etc.)
    as long as the browser window has focus and the mouse is over the scrollable area.
    """
    try:
        normalized_dir = (direction or "").lower().strip()
    except Exception:
        normalized_dir = "down"

    try:
        c = int(count)
    except (TypeError, ValueError):
        c = 1
    if c < 1:
        c = 1

    if normalized_dir not in ("up", "down"):
        msg = f"Invalid scroll direction: {direction}. Use 'up' or 'down'."
        tlog.warning(msg)
        return msg

    SCROLL_PER_STEP = 400  

    clicks = SCROLL_PER_STEP * c
    if normalized_dir == "down":
        clicks = -clicks

    try:
        pyautogui.scroll(clicks)
        msg = f"Scrolled {normalized_dir} {c} time(s)."
        logger.info(msg)
        tlog.tools(msg)
        return msg
    except Exception as e:
        logger.warning(f"scroll() failed, falling back to page keys: {e}")
        key = "pagedown" if normalized_dir == "down" else "pageup"

        try:
            for _ in range(c):
                pyautogui.press(key)
                time.sleep(0.1)
            msg = f"Scrolled {normalized_dir} {c} time(s) (fallback)."
            logger.info(msg)
            tlog.tools(msg)
            return msg
        except Exception as e2:
            msg = f"Failed to execute scroll command: {e2}"
            logger.exception(msg)
            tlog.error(msg)
            return msg

def _auto_scroll_worker(direction: str, step: int, delay: float):
    """
    Background worker that keeps scrolling until _auto_scroll_stop_event is set.
    Runs in a daemon thread so it doesn't block the main agent.
    """
    global _auto_scroll_stop_event

    try:
        normalized_dir = (direction or "").lower().strip()
    except Exception:
        normalized_dir = "down"

    if normalized_dir not in ("up", "down"):
        normalized_dir = "down"

    sign = 1 if normalized_dir == "up" else -1

    try:
        while not _auto_scroll_stop_event.is_set():
            pyautogui.scroll(sign * step)
            time.sleep(delay)
    except Exception as e:
        logger.exception(f"Auto scroll worker failed: {e}")

def start_auto_scroll(direction: str = "down", speed: str = "slow") -> str:
    """
    Start continuous auto-scrolling in the given direction.
    - direction: 'up' or 'down'
    - speed: 'slow' (default), can be extended later

    This returns immediately and scrolling continues in background
    until stop_auto_scroll() is called.
    """
    global _auto_scroll_thread, _auto_scroll_stop_event

    try:
        normalized_dir = (direction or "").lower().strip()
    except Exception:
        normalized_dir = "down"

    if normalized_dir not in ("up", "down"):
        msg = f"Invalid scroll direction: {direction}. Use 'up' or 'down'."
        tlog.warning(msg)
        return msg

    if (speed or "").lower().strip() == "slow":
        step = 80      
        delay = 0.35   
    else:
        step = 160
        delay = 0.25

    if _auto_scroll_thread is not None and _auto_scroll_thread.is_alive():
        msg = "Auto scrolling is already running. Say 'stop scrolling' first to stop."
        tlog.tools(msg)
        return msg

    _auto_scroll_stop_event.clear()
    _auto_scroll_thread = threading.Thread(
        target=_auto_scroll_worker,
        args=(normalized_dir, step, delay),
        daemon=True,
    )
    _auto_scroll_thread.start()

    msg = f"Started slow auto scrolling {normalized_dir}."
    logger.info(msg)
    tlog.tools(msg)
    return msg

def stop_auto_scroll() -> str:
    """
    Stop any active auto scrolling.
    """
    global _auto_scroll_thread, _auto_scroll_stop_event

    if _auto_scroll_thread is None or not _auto_scroll_thread.is_alive():
        msg = "Auto scrolling is not currently running."
        tlog.tools(msg)
        return msg

    _auto_scroll_stop_event.set()
    _auto_scroll_thread = None

    msg = "Stopped auto scrolling."
    logger.info(msg)
    tlog.tools(msg)
    return msg

def intelligent_web_search(query: str, mode: str = "terminal") -> str:
    """
    Builds a safe search URL (Google/Bing/DuckDuckGo) and either returns it
    or opens it in a browser (mode == "chrome" opens browser as before).
    Keeps same heuristics for quick answers and LLM fallback.
    """
    query = (query or "").strip()
    timestamp = search_engine.get_timestamp()
    q_lower = query.lower()

    if (mode or "").lower() == "chrome":
        search_url = ""
        try:
            clean_query = " ".join(query.split()[:20])
            search_url = f"https://www.google.com/search?q={quote_plus(clean_query)}"
            logger.info("Opening browser for: %s", clean_query)
            tlog.search(f"Opening browser for: {clean_query}")

            cmd_list = _get_os_cmd_list("chrome", additional_args=[search_url])
            if cmd_list and _run_cmd(cmd_list):
                return f"Browser opened for: {query}"

            webbrowser.open(search_url, new=2)
            return f"Browser opened for: {query}"
        except Exception as e:
            logger.exception("Failed to open browser automatically: %s", e)
            tlog.error(f"Failed to open browser automatically: {e}")
            try:
                if search_url:
                    webbrowser.open(search_url, new=2)
            except Exception:
                logger.exception("webbrowser fallback also failed.")
            return f"Browser opened for: {query}"

    if (
        query
        and (
            len(query.split()) < 4
            or q_lower.startswith("tell me about ")
            or q_lower.startswith("who is ")
            or q_lower.startswith("what is ")
        )
        and "news" not in q_lower
    ):
        try:
            quick = search_engine.quick_answer(query)
            return f"QUICK_ANSWER: {quick}"
        except Exception as e:
            logger.warning("Quick answer failed: %s", e)
            tlog.error(f"Quick answer failed: {e}")

    results = search_engine.search_and_fetch_parallel(query, num_pages=2)
    if not results:
        logger.info("No web search results; attempting LLM fallback answer.")
        tlog.search("No results found, using LLM fallback")
        try:
            fallback_prompt = f"Answer concisely: {query}"
            fallback_answer = search_engine.summarize_text(
                fallback_prompt,
                provider="auto",
                max_tokens=200,
            )
            if fallback_answer:
                return f"LLM_FALLBACK: {fallback_answer}"
        except Exception as e:
            logger.warning("LLM fallback failed: %s", e)
            tlog.error(f"LLM fallback failed: {e}")
        return "No results found and LLM fallback failed."

    formatted_results = []
    for i, res in enumerate(results):
        url = res.get("url", "") or ""
        full_content = res.get("full_content", "") or res.get("content", "") or ""
        try:
            summary_cache_key = search_engine.get_cache_key(
                f"summary_{url or res.get('title')}",
                "summary",
            )
            cached_summary = search_engine.get_cached_result(summary_cache_key)
            if cached_summary and cached_summary.get("summary"):
                summary = cached_summary["summary"]
            else:
                summary = search_engine.summarize_text(
                    full_content or res.get("snippet", ""),
                    provider="auto",
                    model=None,
                    max_tokens=200,
                )
                search_engine.cache_result(
                    summary_cache_key,
                    {"summary": summary, "url": url},
                )
        except Exception as e:
            logger.warning("Summarization failed for %s: %s", url, e)
            tlog.error(f"Summarization failed for {url}: {e}")
            summary = search_engine._simple_extractive_summary(
                full_content or res.get("snippet", ""),
                max_sentences=3,
            )

        formatted_results.append(
            f"""
        RESULT_{i+1}:
        TITLE: {res.get('title', 'No Title')}
        URL: {url}
        SUMMARY: {summary}
        SNIPPET: {res.get('snippet', '')}
        """
        )

    context_str = "\n".join(formatted_results)
    return f"""
    CONTEXT_FROM_WEB ({timestamp}):
    QUERY: {query}

    {context_str}
    """

def control_youtube(action: str, query: Optional[str] = None) -> str:
    """
    Control YouTube. Uses DuckDuckGo Video Search for robust link finding,
    plus 'autoplay=1' and spacebar injection to force playback.
    """
    action = (action or "").lower().strip()

    if action == "play":
        if not query:
            return "Please provide a search query to play."

        tlog.search(f"Searching YouTube (via DDG) for: {query}")

        found_url = None
        found_title = "Video"

        if DDGS:
            try:
                ddgs = DDGS()
                results = ddgs.videos(
                    query,
                    region="wt-wt",
                    safesearch="moderate",
                    max_results=1,
                )

                res_list = list(results)
                if res_list:
                    top_hit = res_list[0]
                    link = (
                        top_hit.get("content")
                        or top_hit.get("url")
                        or top_hit.get("href")
                    )
                    if link and "youtube.com/watch" in link:
                        found_url = link
                        found_title = top_hit.get("title", query)
            except Exception as e:
                logger.warning(f"DDG Video search failed: {e}")

        if not found_url:
            tlog.tools(
                f"Could not find direct video link. Opening search results for: {query}"
            )
            fallback_url = (
                f"https://www.youtube.com/results?search_query={quote_plus(query)}"
            )
            webbrowser.open(fallback_url, new=2)
            return f"Opened search results for {query} (Auto-play not available)."

        if "?" in found_url:
            found_url += "&autoplay=1"
        else:
            found_url += "?autoplay=1"

        tlog.tools(f"Opening Video: {found_title}")

        webbrowser.open(found_url, new=2)

        time.sleep(4)

        try:
            pyautogui.press("space")
        except Exception as e:
            logger.warning(f"Failed to send spacebar for autoplay: {e}")

        return f"Playing {found_title} on YouTube."

    yt_mappings = {
        "pause": "k",
        "resume": "k",
        "stop": "k",
        "seek_forward": "l",   
        "seek_backward": "j",  
        "fullscreen": "f",
        "mute": "m",
        "theater": "t",
    }

    if action in yt_mappings:
        key = yt_mappings[action]
        try:
            pyautogui.press(key)
            return f"YouTube command '{action}' sent."
        except Exception as e:
            return f"Failed to send command: {e}"

    if action == "next":
        try:
            pyautogui.hotkey("shift", "n")
            return "Skipped to next video."
        except Exception as e:
            return f"Failed to send 'next' command: {e}"

    if action == "previous":
        try:
            pyautogui.hotkey("shift", "p")
            return "Returned to previous video."
        except Exception as e:
            return f"Failed to send 'previous' command: {e}"

    return "Unknown YouTube command."