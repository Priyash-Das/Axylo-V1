import asyncio
import os
import re
from datetime import datetime
from typing import Tuple, Optional

import pyautogui

import src.logger as logger
from src.tools import control_app

LAST_SAVED_PATH: Optional[str] = None

pyautogui.FAILSAFE = False

VOICE_TYPING_END_CMDS = {"end voice typing", "stop voice typing"}
NEXT_LINE_CMDS = {"go next line", "go to next line"}
BACKSPACE_CMDS = {"back press", "backspace"}
DEL_WORD_CMDS = {"delete last word"}
DEL_SENT_CMDS = {"delete last sentence"}

SAVE_CMDS = {
    "save file",
    "save this file",
    "save this note",
    "save file now",
    "save this",
    "save file to desktop", 
    "save this file desktop",
    "save file in desktop",
    "ok save the file in desktop",
}

OPEN_LAST_FILE_CMDS = {
    "open last saved file",
    "open last file",
    "open last note",
    "open saved file",
    "open note",
    "open last safe file",
}

READ_LAST_NOTE_CMDS = {
    "read last saved note",
    "read last note",
    "read saved note",
    "read my last note",
}


async def start_voice_typing(voice) -> None:
    """
    Entry point for voice typing mode.
    - Opens Notepad.
    - Starts continuous dictation to Notepad.
    """
    try:
        msg = control_app("notepad", "open")
        logger.tools(f"[VoiceTyping] control_app(notepad, open) -> {msg}")
    except Exception as e:
        logger.error(f"[VoiceTyping] Error opening Notepad: {e}")
        await _safe_speak(voice, "I could not open Notepad. Cancelling voice typing.")
        return

    if "opened" not in str(msg).lower():
        await _safe_speak(voice, "I could not open Notepad. Voice typing cancelled.")
        return

    await asyncio.sleep(1.0)

    await voice_typing_session(voice)


async def voice_typing_session(voice) -> None:
    """
    Main loop:
    - Listens continuously.
    - Executes control commands.
    - Types normal dictation into Notepad.
    """
    typed_buffer = ""
    await _safe_speak(voice, "Voice typing is active. Say 'end voice typing' to stop.")

    while True:
        text = await voice.listen_async(timeout=8, phrase_time_limit=8)
        if not text:
            continue

        raw_text = text.strip()
        cmd = raw_text.lower().strip()

        cmd = cmd.replace("safe", "save").replace("safed", "saved")

        logger.user(f"[VoiceTyping] Heard: {raw_text}")

        if cmd in VOICE_TYPING_END_CMDS:
            await _safe_speak(voice, "Stopping voice typing.")
            break

        if cmd in NEXT_LINE_CMDS:
            _press_key("enter")
            typed_buffer += "\n"
            continue

        if cmd in BACKSPACE_CMDS:
            _press_key("backspace")
            if typed_buffer:
                typed_buffer = typed_buffer[:-1]
            continue

        if cmd in DEL_WORD_CMDS:
            typed_buffer, backspaces = _delete_last_word(typed_buffer)
            _press_backspaces(backspaces)
            continue

        if cmd in DEL_SENT_CMDS:
            typed_buffer, backspaces = _delete_last_sentence(typed_buffer)
            _press_backspaces(backspaces)
            continue

        if cmd in SAVE_CMDS:
            await _ask_and_save_file(voice, typed_buffer)
            continue

        if cmd in OPEN_LAST_FILE_CMDS:
            await _open_last_saved_file(voice)
            continue

        if cmd in READ_LAST_NOTE_CMDS:
            await _read_last_saved_note(voice)
            continue

        if not raw_text:
            continue

        to_type = raw_text + " "
        _type_text(to_type)
        typed_buffer += to_type


async def _safe_speak(voice, text: str) -> None:
    try:
        await voice.speak(text)
    except Exception as e:
        logger.error(f"[VoiceTyping] speak failed: {e}")


def _press_key(key: str) -> None:
    try:
        pyautogui.press(key)
    except Exception as e:
        logger.error(f"[VoiceTyping] Failed to press key '{key}': {e}")


def _press_backspaces(n: int) -> None:
    if n <= 0:
        return
    try:
        for _ in range(n):
            pyautogui.press("backspace")
    except Exception as e:
        logger.error(f"[VoiceTyping] Failed to press backspace {n} times: {e}")


def _type_text(text: str) -> None:
    try:
        pyautogui.typewrite(text, interval=0.01)
    except Exception as e:
        logger.error(f"[VoiceTyping] Failed to type text: {e}")


def _delete_last_word(buffer: str) -> Tuple[str, int]:
    """
    Return (new_buffer, num_chars_deleted) for 'delete last word'.
    """
    if not buffer.strip():
        return buffer, 0

    stripped = buffer.rstrip()
    trailing_spaces = len(buffer) - len(stripped)

    idx = stripped.rfind(" ")
    if idx == -1:

        deleted_len = len(stripped)
        return "", deleted_len + trailing_spaces

    new_buffer = stripped[: idx + 1]
    deleted_len = len(buffer) - len(new_buffer)
    return new_buffer, deleted_len


def _delete_last_sentence(buffer: str) -> Tuple[str, int]:
    """
    Very simple sentence deletion:
    - Looks for last '.', '!' or '?'.
    - Deletes from that punctuation to the end.
    If none found, deletes entire buffer.
    """
    if not buffer.strip():
        return buffer, 0

    stripped = buffer.rstrip()
    trailing_spaces = len(buffer) - len(stripped)

    last_dot = stripped.rfind(".")
    last_q = stripped.rfind("?")
    last_exc = stripped.rfind("!")
    last_delim = max(last_dot, last_q, last_exc)

    if last_delim == -1:
        deleted_len = len(stripped)
        return "", deleted_len + trailing_spaces

    new_buffer = stripped[: last_delim + 1]
    deleted_len = len(buffer) - len(new_buffer)
    return new_buffer, deleted_len


async def _ask_and_save_file(voice, buffer: str) -> None:
    """
    Ask the user by voice where to save, parse the answer into a drive + folder,
    create the folder, and save the buffer there.

    Example spoken answers:
      - "D drive"
      - "D drive in notes folder"
      - "E drive in ai notes"
    """
    global LAST_SAVED_PATH

    if not buffer.strip():
        await _safe_speak(voice, "There is no text to save yet.")
        return

    await _safe_speak(
        voice,
        "Where should I save this file? "
        "For example, say 'D drive in notes folder' or 'E drive'."
    )

    for attempt in range(3):
        answer = await voice.listen_async(timeout=8, phrase_time_limit=8)
        if not answer:
            continue

        raw_loc = answer.strip()
        cmd = raw_loc.lower().strip()
        logger.user(f"[VoiceTyping] Save location answer: {raw_loc}")

        directory = _parse_location_to_directory(cmd)
        if not directory:
            await _safe_speak(
                voice,
                "I did not understand the drive and folder. "
                "Please say something like 'D drive in notes folder'."
            )
            continue

        ok, full_path, err_msg = _write_buffer_to_directory(buffer, directory)
        if ok:
            LAST_SAVED_PATH = full_path
            await _safe_speak(voice, "File saved successfully.")
            logger.tools(f"[VoiceTyping] Saved note to: {full_path}")
            return

        logger.error(f"[VoiceTyping] Failed to save to {directory}: {err_msg}")
        await _safe_speak(voice, err_msg or "Saving failed. Please try again.")

    await _safe_speak(voice, "I could not understand where to save the file. Cancelling save.")


def _parse_location_to_directory(cmd: str) -> Optional[str]:
    """
    Parse a spoken location like:
      'd drive in notes folder'
      'e drive'
      'd drive in my ai notes'
    into a directory path like:
      'D:\\notes folder'
      'E:\\VoiceNotes'
    """
    m = re.search(r"\b([a-z])\s*drive\b", cmd)
    if not m:
        return None

    drive_letter = m.group(1).upper()
    drive_root = f"{drive_letter}:\\"

    if not os.path.exists(drive_root):
        return None

    after = cmd[m.end():].strip()
    if not after:
        return os.path.join(drive_root, "VoiceNotes")

    tokens = [t for t in after.split() if t not in {"in", "on", "the", "a", "an"}]
    if not tokens:
        return os.path.join(drive_root, "VoiceNotes")

    folder_name = " ".join(tokens)
    return os.path.join(drive_root, folder_name)


def _write_buffer_to_directory(buffer: str, directory: str) -> Tuple[bool, str, Optional[str]]:
    """
    Actually create the directory (if needed) and write the buffer as a file.
    Returns (ok, full_path, error_message).
    """
    try:
        drive, _ = os.path.splitdrive(directory)
        if not drive or not os.path.exists(drive + "\\"):
            return False, "", "That drive does not exist on this computer."

        os.makedirs(directory, exist_ok=True)

        fname = datetime.now().strftime("VoiceNotes_%Y%m%d_%H%M%S.txt")
        full_path = os.path.join(directory, fname)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(buffer or "")

        return True, full_path, None
    except Exception as e:
        return False, "", f"I had an internal error while saving: {e}"


async def _open_last_saved_file(voice) -> None:
    """
    Open the last saved note in the default text editor (Notepad on Windows).
    """
    try:
        if not LAST_SAVED_PATH:
            await _safe_speak(voice, "No saved file found yet. Please say 'save this file' first.")
            return

        if not os.path.exists(LAST_SAVED_PATH):
            await _safe_speak(voice, "I can't find the last saved file on disk.")
            return

        os.startfile(LAST_SAVED_PATH)
        await _safe_speak(voice, "Opening your last saved note.")
        logger.tools(f"[VoiceTyping] Opening last saved file: {LAST_SAVED_PATH}")
    except Exception as e:
        logger.error(f"[VoiceTyping] Failed to open last saved file: {e}")
        await _safe_speak(voice, "I could not open the last saved file.")


async def _read_last_saved_note(voice) -> None:
    """
    Read the content of the last saved note aloud (first few hundred characters).
    """
    try:
        if not LAST_SAVED_PATH:
            await _safe_speak(voice, "I don't have any saved note yet in this session.")
            return

        if not os.path.exists(LAST_SAVED_PATH):
            await _safe_speak(voice, "I can't find the last saved file on disk.")
            return

        with open(LAST_SAVED_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            await _safe_speak(voice, "The last saved note is empty.")
            return

        snippet = content[:600]
        await _safe_speak(voice, "Here is your last saved note.")
        await _safe_speak(voice, snippet)
    except Exception as e:
        logger.error(f"[VoiceTyping] Failed to read last saved note: {e}")
        await _safe_speak(voice, "I could not read the last saved note.")
