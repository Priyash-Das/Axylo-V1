import asyncio
import os
import logging
import signal
import contextlib
import time
import uuid  
import re

from dotenv import load_dotenv

load_dotenv()

import src.logger as logger

from src.voice_io import VoiceHandler
from src.agent import create_axylo_agent
from src.agent import _shorten_text, _sanitize_for_speech
from google.adk.runners import InMemoryRunner

from src.voice_typing import start_voice_typing
from src.voice_messaging import start_voice_messaging
from src.smart_writer import handle_smart_ai_writing

logging.getLogger().handlers.clear()
logging.getLogger().setLevel(logging.CRITICAL + 1)


async def run_agent_loop(shutdown_event: asyncio.Event):
    """
    Main agent loop.
    - shutdown_event: when set, loop ends and cleanup runs.
    """
    voice = VoiceHandler(tts_voice=os.getenv("TTS_VOICE", "en-GB-RyanNeural"))
    try:
        voice.loop = asyncio.get_running_loop()
    except RuntimeError:
        voice.loop = None

    agent = create_axylo_agent()
    runner = InMemoryRunner(agent=agent)

    runner.render_fn = lambda *args, **kwargs: None
    runner.debug = False

    try:
        await voice.speak("Hi! I'm Axylo. The voice of your smart world. How can I help you?")
    except Exception as e:
        logger.error(f"Startup speak failed: {e}")

    consecutive_empty = 0
    MAX_EMPTY_BEFORE_SLEEP = 20

    try:
        while not shutdown_event.is_set():
            try:
                user_input = await voice.listen_async(timeout=5, phrase_time_limit=10)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Listen error: {e}")
                user_input = ""

            if shutdown_event.is_set():
                break

            if not user_input:
                consecutive_empty += 1
                if consecutive_empty >= MAX_EMPTY_BEFORE_SLEEP:
                    await asyncio.sleep(1.0)
                    consecutive_empty = 0
                continue

            consecutive_empty = 0

            request_id = uuid.uuid4().hex[:8]
            logger.set_request_id(request_id)

            try:
                logger.user(user_input)
                lower_input = user_input.strip().lower()

                if (
                    "bye" in lower_input
                    or "bye bye" in lower_input
                    or "byebye" in lower_input
                    or "bye-bye" in lower_input
                    or "shut down" in lower_input
                    or "shutdown" in lower_input
                    or "shut-down" in lower_input
                ):
                    try:
                        await voice.speak("Bye!. Shutting down.")
                    except Exception:
                        pass
                    break

                if lower_input.startswith("write "):
                    await handle_smart_ai_writing(user_input, voice)
                    continue

                if lower_input in ("voice typing", "start voice typing"):
                    try:
                        await voice.speak("Starting voice typing in Notepad.")
                    except Exception:
                        pass
                    try:
                        await start_voice_typing(voice)
                    except Exception as e:
                        logger.error(f"Voice typing session error: {e}")
                        try:
                            await voice.speak("Voice typing failed because of an internal error.")
                        except Exception:
                            pass
                    continue

                if lower_input.startswith("send a message") or lower_input.startswith("send message"):
                    initial_recipient = None
                    if " to " in lower_input:
                        try:
                            initial_recipient = lower_input.split(" to ", 1)[1].strip()
                        except Exception:
                            initial_recipient = None
                    try:
                        await voice.speak("Okay, I will help you send a message.")
                    except Exception:
                        pass
                    try:
                        await start_voice_messaging(voice, initial_recipient=initial_recipient)
                    except Exception as e:
                        logger.error(f"Voice messaging session error: {e}")
                        try:
                            await voice.speak("Message sending failed because of an internal error.")
                        except Exception:
                            pass
                    continue

                try:
                    with open(os.devnull, "w") as devnull, \
                         contextlib.redirect_stdout(devnull), \
                         contextlib.redirect_stderr(devnull):
                        result = await runner.run_debug(user_input)

                    final_text = ""

                    if isinstance(result, (list, tuple)):
                        for event in result:
                            try:
                                if hasattr(event, "is_final_response") and event.is_final_response():
                                    if getattr(event, "content", None) and getattr(event.content, "parts", None):
                                        final_text = event.content.parts[0].text
                            except Exception:
                                if isinstance(event, str):
                                    final_text = event
                    else:
                        try:
                            if hasattr(result, "content"):
                                parts = getattr(result.content, "parts", None)
                                if parts:
                                    first = parts[0]
                                    final_text = getattr(first, "text", str(first))
                            elif isinstance(result, str):
                                final_text = result
                        except Exception:
                            final_text = str(result)

                    if final_text:
                        logger.agent(final_text)
                        
                        tts_text = make_tts_friendly(final_text)
    
                        try:
                            await voice.speak(final_text)
                        except Exception as e:
                            logger.error(f"Voice speak failed: {e}")
                    else:
                        try:
                            await voice.speak("I couldn't parse the agent's response. Check logs.")
                        except Exception:
                            pass

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Agent error: {e}")
                    try:
                        await voice.speak("I encountered an error executing that command.")
                    except Exception:
                        pass

            finally:
                logger.set_request_id(None)

    except asyncio.CancelledError:
        try:
            await voice.speak("Shutting down.")
        except Exception:
            pass
    finally:
        try:
            close_fn = getattr(runner, "close", None) or getattr(runner, "shutdown", None)
            if callable(close_fn):
                try:
                    maybe = close_fn()
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except Exception:
                    logger.debug(
                        "Runner close/shutdown raised an exception during cleanup.",
                    )
        except Exception:
            pass

        try:
            cleanup_fn = getattr(voice, "cleanup_tempdir", None) or getattr(voice, "cleanup", None)
            if callable(cleanup_fn):
                try:
                    maybe = cleanup_fn()
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except Exception:
                    logger.debug(
                        "Voice cleanup raised an exception during cleanup.",
                    )
        except Exception:
            pass

        logger.info("Agent loop has exited and cleanup completed.")

async def _main_with_signals():
    """
    Boot main loop and wire up signal handlers to set a shutdown event.
    """
    shutdown_event = asyncio.Event()

    def _signal_handler(sig):
        logger.info(f"Received signal {sig}. Initiating shutdown.")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, lambda: _signal_handler("SIGINT"))
    except (NotImplementedError, RuntimeError):
        pass
    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: _signal_handler("SIGTERM"))
    except (AttributeError, NotImplementedError, RuntimeError):
        pass

    agent_task = asyncio.create_task(run_agent_loop(shutdown_event))

    try:
        await asyncio.wait({agent_task}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        if not agent_task.done():
            agent_task.cancel()
        raise
    if not agent_task.done():
        agent_task.cancel()
        try:
            await agent_task
        except Exception:
            pass

def make_tts_friendly(text: str, max_len: int = 450) -> str:
    """
    Prepare agent text for speaking:
    - Strip markdown code fences ```...```
    - Keep a short natural-language summary.
    """
    if not text:
        return ""

    cleaned = re.sub(r"```.*?```", " I've put the full code in your chat window. ", text, flags=re.DOTALL)

    cleaned = re.sub(r"(^|\n)( {4,}.*)", r"\1", cleaned)

    cleaned = _sanitize_for_speech(cleaned)
    cleaned = _shorten_text(cleaned, max_len=max_len)
    return cleaned.strip()

if __name__ == "__main__":
    try:
        asyncio.run(_main_with_signals())
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Exiting.")
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
