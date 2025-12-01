import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "1"

import asyncio
import tempfile
import threading
import time
import atexit
import logging
import platform
import subprocess
import shutil
from typing import Optional

try:
    import src.logger as logger
except Exception:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("voice_io")

try:
    import edge_tts
except Exception:
    edge_tts = None

try:
    from gtts import gTTS
except Exception:
    gTTS = None

try:
    import pygame
except Exception:
    pygame = None

try:
    import speech_recognition as sr
except Exception:
    sr = None

class VoiceHandler:
    """
    Compatible replacement for original voice_io.VoiceHandler with improved robustness.
    Public methods preserved:
      - listen_async(timeout, phrase_time_limit)
      - listen_sync()
      - speak(text, voice=None, filename=None)  # async
      - speak_sync(text)                        # sync wrapper

    IMPORTANT BEHAVIOR:
    - While TTS audio is playing (speak), the handler will NOT take any mic input.
      listen_async() waits until speaking is finished (plus a short cool-down)
      before opening the microphone.
    """

    def __init__(self, tts_voice: str = "en-GB-RyanNeural"):
        self.recognizer = sr.Recognizer() if sr else None
        self.mic = None
        if sr:
            try:
                self.mic = sr.Microphone()
            except Exception:
                self.mic = None
                logger.error("Microphone not available (speech_recognition).")

        self.tts_voice = tts_voice

        self._tmpdir_obj = tempfile.TemporaryDirectory(prefix="edge_tts_")
        self._temp_dir = self._tmpdir_obj.name
        atexit.register(self.cleanup_tempdir)

        self.loop: Optional[asyncio.AbstractEventLoop] = None

        self._mixer_ready = False
        self._mixer_lock = threading.Lock()
        self._init_mixer()
        
        self._listen_lock = threading.Lock() 
        self._speaking_flag = threading.Event() 
        self._post_speech_silence = 0.4 
        self._stop_playback_flag = threading.Event() 

    def cleanup_tempdir(self):
        try:
            self._tmpdir_obj.cleanup()
        except Exception:
            pass

    def _init_mixer(self):
        """
        Initialize pygame.mixer if pygame is available. Do not crash if init fails.
        """
        if pygame is None:
            self._mixer_ready = False
            return

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._mixer_ready = True
            logger.debug("pygame.mixer initialized for audio playback")
        except Exception as e:
            self._mixer_ready = False
            logger.error(f"Warning: pygame.mixer init failed: {e}")

    async def listen_async(self, timeout: float = 5.0, phrase_time_limit: float = 10.0) -> str:
        """
        Async wrapper around blocking speech_recognition listen/recognize functions.
        Returns recognized text (empty string on failure).

        Guarantees:
        - Will NOT listen while TTS is speaking (see _speaking_flag).
        - Only one concurrent listener can use the mic (see _listen_lock).
        """
        if sr is None or self.recognizer is None or self.mic is None:
            logger.error("speech_recognition is not available or microphone missing.")
            return ""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._listen_blocking, timeout, phrase_time_limit)

    def _listen_blocking(self, timeout: float, phrase_time_limit: float) -> str:
        """
        Blocking listening function using speech_recognition.
        Uses Google free recognizer and returns empty string on errors.

        Behavior additions:
        - Waits while _speaking_flag is set (agent is talking).
        - Enforces exclusive access to the Microphone via _listen_lock.
        """
        if self.recognizer is None or self.mic is None:
            return ""
        
        max_wait = 10.0  
        waited = 0.0
        while self._speaking_flag.is_set() and waited < max_wait:
            time.sleep(0.05)
            waited += 0.05
            
        if waited > 0.0 or self._speaking_flag.is_set():
            time.sleep(self._post_speech_silence)

        with self._listen_lock:
            with self.mic as source:
                try:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                except Exception:
                    pass

                logger.voice("Listening...")
                try:
                    audio = self.recognizer.listen(
                        source,
                        timeout=timeout,
                        phrase_time_limit=phrase_time_limit,
                    )
                except Exception:
                    return ""

        try:
            text = self.recognizer.recognize_google(audio)
            logger.voice(f"You said: {text}")
            return text
        except sr.UnknownValueError:
            logger.voice("Could not understand audio.")
            return ""
        except sr.RequestError:
            logger.error("Speech recognition request failed.")
            return ""
        except Exception:
            return ""

    def listen_sync(self) -> str:
        """Synchronous wrapper for existing/legacy code."""
        return self._listen_blocking(timeout=5.0, phrase_time_limit=10.0)

    async def speak(self, text: str, voice: Optional[str] = None, filename: Optional[str] = None):
        """
        Convert text -> speech and play it.
        - If 'edge_tts' available, use it (async API).
        - Otherwise attempt gTTS in a thread (blocking).
        - Playback uses pygame.mixer.music in a background thread (blocking there).
        - Removes temporary file after playback.

        While this method is running, _speaking_flag is set so all listeners
        know that the assistant is talking and should NOT open the microphone.
        """
        if not text:
            return

        voice_to_use = voice or self.tts_voice

        if filename:
            out_path = filename
        else:
            fd, out_path = tempfile.mkstemp(suffix=".mp3", prefix="edge_tts_", dir=self._temp_dir)
            os.close(fd)
            
        self._speaking_flag.set()
        try:
            if edge_tts is not None:
                try:
                    communicate = edge_tts.Communicate(text, voice_to_use)
                    await communicate.save(out_path)
                except Exception as e:
                    logger.error(f"Edge-TTS failed: {e}")
                    await self._gtts_fallback_async(text, out_path)
            else:
                await self._gtts_fallback_async(text, out_path)

            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._play_blocking, out_path)
            except Exception as e:
                logger.error(f"Playback failed: {e}")
        finally:
            try:
                if os.path.exists(out_path) and (not filename):
                    os.remove(out_path)
            except Exception:
                pass

            self._speaking_flag.clear()

    async def _gtts_fallback_async(self, text: str, out_path: str):
        """
        Run gTTS save inside executor (blocking operation off the event loop).
        Preserves original audio format (mp3).
        """
        if gTTS is None:
            logger.error("gTTS not available as fallback. Install 'edge-tts' or 'gTTS'.")
            return

        def _save_mp3():
            try:
                tts = gTTS(text=text, lang="en", slow=False)
                tts.save(out_path)
            except Exception as e:
                logger.error(f"gTTS fallback failed to save audio: {e}")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _save_mp3)

    def speak_sync(self, text: str):
        """Synchronous wrapper for speak (runs async speak and waits)."""
        loop = self.loop or asyncio.get_event_loop()
        return loop.run_until_complete(self.speak(text))

    def _play_blocking(self, filepath: str):
        """
        Blocking audio playback using pygame.mixer.music.
        Behavior and audio characteristics preserved to match your original sound.
        """
        if not os.path.exists(filepath):
            logger.error(f"Audio file not found: {filepath}")
            return

        with self._mixer_lock:
            if pygame is None:
                logger.error("pygame not available for playback.")
                return
            try:
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                    self._mixer_ready = True
            except Exception as e:
                logger.error(f"Failed to init pygame mixer before playback: {e}")
                self._mixer_ready = False

            if not self._mixer_ready:
                logger.error("Mixer not ready; cannot play audio.")
                return

            try:
                pygame.mixer.music.load(filepath)
                pygame.mixer.music.play()

                while pygame.mixer.music.get_busy():
                    if self._stop_playback_flag.is_set():
                        pygame.mixer.music.stop()
                        break
                    time.sleep(0.05)

                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error during playback: {e}")
                
    def stop_speaking(self) -> None:
        """
        Immediately stop any currently playing TTS audio.
        Safe to call from GUI thread.
        """
        try:
            self._stop_playback_flag.set()
            if pygame is not None and pygame.mixer.get_init():
                with self._mixer_lock:
                    try:
                        pygame.mixer.music.stop()
                        try:
                            pygame.mixer.music.unload()
                        except Exception:
                            pass
                    except Exception as e:
                        logger.error(f"Error stopping playback: {e}")
        finally:
            self._speaking_flag.clear()
            self._stop_playback_flag.clear()

_default_voice_handler: Optional[VoiceHandler] = None

def get_voice_handler() -> VoiceHandler:
    global _default_voice_handler
    if _default_voice_handler is None:
        _default_voice_handler = VoiceHandler()
    return _default_voice_handler

def speak_sync(text: str):
    get_voice_handler().speak_sync(text)

def listen_sync() -> str:
    return get_voice_handler().listen_sync()

if __name__ == "__main__":
    vh = get_voice_handler()
    vh.speak_sync("Hello — this is a quick test to verify T T S and playback.")
