import asyncio
import os
import time
import tempfile
from pathlib import Path

import src.logger as logger

GEMINI_MODEL = None
DOCX_AVAILABLE = False

try:
    import google.generativeai as genai

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    if not GEMINI_API_KEY:
        logger.error("[SmartWriter] GEMINI_API_KEY is not set in environment.")
    else:
        genai.configure(api_key=GEMINI_API_KEY)

        gemini_model_name = os.getenv(
            "SMART_WRITER_GEMINI_MODEL",
            "gemini-2.0-flash",
        )

        GEMINI_MODEL = genai.GenerativeModel(
            model_name=gemini_model_name,
            generation_config={
                "temperature": 0.6,
            },
        )
        logger.info(f"[SmartWriter] Gemini model initialised: {gemini_model_name}")

except Exception as e:
    GEMINI_MODEL = None
    logger.error(f"[SmartWriter] Failed to configure Gemini client: {e}")

try:
    from docx import Document

    DOCX_AVAILABLE = True
except Exception as e:
    DOCX_AVAILABLE = False
    logger.info(f"[SmartWriter] python-docx not available, will use .txt instead: {e}")


def _call_gemini_blocking(prompt: str) -> str:
    """
    Blocking: call Gemini 2.0 Flash and return plain text.
    Includes simple retry logic.
    """
    if GEMINI_MODEL is None:
        raise RuntimeError(
            "Gemini model is not configured. "
            "Check GEMINI_API_KEY and internet connection."
        )

    max_retries = 3
    backoff_seconds = 2.0
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.tools(
                f"[SmartWriter] Calling Gemini (attempt {attempt}/{max_retries})."
            )

            resp = GEMINI_MODEL.generate_content(prompt)

            text = ""
            if hasattr(resp, "text") and resp.text:
                text = resp.text
            elif getattr(resp, "candidates", None):
                try:
                    text = resp.candidates[0].content.parts[0].text
                except Exception:
                    pass

            text = (text or "").strip()
            if not text:
                raise RuntimeError("Gemini returned an empty response.")

            logger.debug(
                f"[SmartWriter] Gemini response length={len(text)} characters."
            )
            return text

        except Exception as e:
            last_error = e
            logger.error(f"[SmartWriter] Gemini error on attempt {attempt}: {e}")
            if attempt < max_retries:
                time.sleep(backoff_seconds)
            else:
                break

    raise RuntimeError(f"Gemini failed after {max_retries} attempts: {last_error}")


def _open_in_word_or_notepad_blocking(text: str) -> None:
    """
    Blocking: create a temp .docx (if possible) or .txt file and open it.
    """
    if not text or not text.strip():
        raise ValueError("No text to write into document.")

    ts = int(time.time())
    temp_dir = Path(tempfile.gettempdir())

    if DOCX_AVAILABLE:
        try:
            doc = Document()
            for line in text.splitlines():
                doc.add_paragraph(line)
            doc_path = temp_dir / f"smart_writer_{ts}.docx"
            doc.save(doc_path)
            logger.tools(f"[SmartWriter] Opening Word document: {doc_path}")
            os.startfile(str(doc_path))
            return
        except Exception as e:
            logger.error(
                f"[SmartWriter] Failed to create/open .docx, falling back to .txt: {e}"
            )

    txt_path = temp_dir / f"smart_writer_{ts}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.tools(f"[SmartWriter] Opening text document: {txt_path}")
    os.startfile(str(txt_path))


async def _safe_speak(voice, text: str) -> None:
    """
    Speak text using your VoiceHandler, ignoring minor TTS errors.
    """
    if not voice:
        return
    try:
        await voice.speak(text)
    except Exception as e:
        logger.error(f"[SmartWriter] speak failed: {e}")


async def handle_smart_ai_writing(query: str, voice) -> None:
    """
    Main entry to Smart AI Writing.
    - Called when user says "write ..."
    - Uses Gemini to generate writing
    - Opens result in a fresh document.
    """
    clean_query = (query or "").strip()
    logger.voice(f"[SmartWriter] Triggered with query: {clean_query}")

    if not clean_query:
        await _safe_speak(voice, "I didn't hear what to write. Please say it again.")
        return

    await _safe_speak(voice, "Okay. Processing your request.")
    await _safe_speak(voice, "I am using Gemini to generate your content.")

    try:
        ai_text = await asyncio.to_thread(_call_gemini_blocking, clean_query)
    except Exception as e:
        logger.error(f"[SmartWriter] Gemini API call failed: {e}")
        await _safe_speak(
            voice,
            "I could not get a response from Gemini. "
            "Please check your internet connection or Gemini API key and try again.",
        )
        return

    if not ai_text or not ai_text.strip():
        await _safe_speak(
            voice,
            "Gemini returned an empty response. Please try rephrasing your request.",
        )
        return

    try:
        await asyncio.to_thread(_open_in_word_or_notepad_blocking, ai_text)
        await _safe_speak(
            voice,
            "I have put the generated content into a new document for you.",
        )
    except Exception as e:
        logger.error(f"[SmartWriter] Failed to open document: {e}")
        await _safe_speak(
            voice,
            "I generated the content, but I could not open a document to show it.",
        )
