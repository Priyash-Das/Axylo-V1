import asyncio
from typing import Optional

import pyautogui
import webbrowser

import src.logger as logger
from src.tools import control_app   

pyautogui.FAILSAFE = False

CONTACT_EMAILS = {
    "ram": "ram@gmail.com",
    "priyash": "priyash@gmail.com",
    "mom": "mom@gmail.com",
}

CONTACT_WHATSAPP = {
    "ram": "Ram",
    "priyash": "Priyash",
    "mom": "Mom",
}

async def start_voice_messaging(voice, initial_recipient: Optional[str] = None) -> None:
    """
    Main entry point for the voice-controlled messaging flow.

    - Asks: Email or WhatsApp.
    - Then runs the corresponding flow.
    - All interaction is voice-only.
    """
    await _safe_speak(voice,
        "Okay, I will help you send a message. "
        "Should I use email or WhatsApp?"
    )

    channel = await _choose_channel(voice)
    if channel is None:
        await _safe_speak(voice, "I couldn't understand the channel. Cancelling sending.")
        return

    if channel == "email":
        await _email_flow(voice, initial_recipient)
    elif channel == "whatsapp":
        await _whatsapp_flow(voice, initial_recipient)
    else:
        await _safe_speak(voice, "I don't support that method yet.")
        return

async def _safe_speak(voice, text: str) -> None:
    try:
        await voice.speak(text)
    except Exception as e:
        logger.error(f"[VoiceMsg] speak failed: {e}")

async def _listen_once(voice, timeout: int = 8, phrase_time_limit: int = 8) -> str:
    """Single listen with simple error protection."""
    try:
        text = await voice.listen_async(timeout=timeout, phrase_time_limit=phrase_time_limit)
        if not text:
            logger.voice("[VoiceMsg] Empty / unclear audio.")
            return ""
        logger.user(f"[VoiceMsg] Heard: {text}")
        return text.strip()
    except Exception as e:
        logger.error(f"[VoiceMsg] listen failed: {e}")
        return ""

async def _ask_and_listen(
    voice,
    prompt: str,
    retries: int = 3,
    timeout: int = 8,
    phrase_time_limit: int = 8,
) -> Optional[str]:
    """Speak a prompt and wait up to `retries` times for a non-empty answer."""
    for attempt in range(retries):
        await _safe_speak(voice, prompt)
        text = await _listen_once(voice, timeout=timeout, phrase_time_limit=phrase_time_limit)
        if text:
            return text
        await _safe_speak(voice, "Sorry, I didn't catch that.")
    return None

async def _wait_for_send_confirmation(voice) -> bool:
    """
    Wait for user to say 'send' or 'cancel'.
    Returns True if user confirms sending, False otherwise.
    """
    await _safe_speak(voice, "Say 'send' to send the message, or 'cancel' to cancel.")

    while True:
        text = await _listen_once(voice, timeout=10, phrase_time_limit=5)
        if not text:
            await _safe_speak(voice, "I didn't hear anything. Say 'send' or 'cancel'.")
            continue

        cmd = text.lower()
        if "send" in cmd:
            await _safe_speak(voice, "Sending now.")
            return True
        if "cancel" in cmd or "stop" in cmd:
            await _safe_speak(voice, "Okay, I cancelled the message.")
            return False

        await _safe_speak(voice, "Please say clearly 'send' or 'cancel'.")

async def _choose_channel(voice) -> Optional[str]:
    """
    Ask user for 'email' or 'whatsapp'.
    Returns 'email', 'whatsapp', or None.
    """
    for _ in range(3):
        text = await _listen_once(voice, timeout=10, phrase_time_limit=5)
        if not text:
            await _safe_speak(voice, "Please say 'email' or 'WhatsApp'.")
            continue

        t = text.lower()
        if "email" in t or "gmail" in t or "mail" in t:
            return "email"
        if "whatsapp" in t or "whats app" in t:
            return "whatsapp"

        await _safe_speak(voice, "I heard something else. Please say 'email' or 'WhatsApp'.")
    return None

def _normalize_name(text: str) -> str:
    """Lowercase, strip, and take only first word for name mapping."""
    if not text:
        return ""
    return text.strip().lower().split()[0]

def _get_email_address(name_or_email: str) -> str:
    """
    Map a spoken name to an email address.

    Rules:
    - If it already contains '@', assume it's a full email.
    - Else: check CONTACT_EMAILS mapping.
    - Else: treat as gmail username → xyz -> xyz@gmail.com
    """
    raw = name_or_email.strip()
    lower = raw.lower()

    if "@" in lower:
        return raw.replace(" ", "")

    key = _normalize_name(lower)
    if key in CONTACT_EMAILS:
        return CONTACT_EMAILS[key]

    return f"{key}@gmail.com"

async def _email_flow(voice, initial_recipient: Optional[str]) -> None:
    """
    Complete email sending flow via Gmail in Chrome.
    We control keyboard using pyautogui.
    """
    await _safe_speak(voice, "Alright, I will send an email using Gmail.")

    gmail_url = "https://mail.google.com/mail/u/0/#inbox?compose=new"

    try:
        msg = control_app("chrome", "open")
        logger.tools(f"[VoiceMsg] control_app(chrome, open) -> {msg}")
    except Exception as e:
        logger.error(f"[VoiceMsg] Failed to open Chrome for Gmail: {e}")
        await _safe_speak(voice, "I could not open Chrome.")
        return

    await asyncio.sleep(5)

    try:
        webbrowser.open(gmail_url, new=2)
    except Exception as e:
        logger.error(f"[VoiceMsg] webbrowser.open Gmail failed: {e}")
        await _safe_speak(voice, "I could not open Gmail in the browser.")
        return

    await asyncio.sleep(7)  

    if initial_recipient:
        spoken_recipient = initial_recipient
    else:
        spoken_recipient = await _ask_and_listen(
            voice,
            "Who is the recipient? You can say a name like Ram, or say the full email address.",
        )
        if not spoken_recipient:
            await _safe_speak(voice, "I couldn't get the recipient. Cancelling email.")
            return

    email_address = _get_email_address(spoken_recipient)
    await _safe_speak(voice, f"Sending to {email_address}. What is your message?")

    message_body = await _ask_and_listen(
        voice,
        "Please speak the message.",
        retries=3,
        timeout=10,
        phrase_time_limit=10,
    )
    if not message_body:
        await _safe_speak(voice, "I couldn't hear the message. Cancelling email.")
        return

    await _safe_speak(voice, f"You said: {message_body}. I will prepare the email.")

    try:
        pyautogui.typewrite(email_address, interval=0.03)
        pyautogui.press("tab")
        pyautogui.typewrite("Voice message from Axylo", interval=0.03)
        pyautogui.press("tab")
        pyautogui.typewrite(message_body, interval=0.03)
    except Exception as e:
        logger.error(f"[VoiceMsg] Failed to type into Gmail: {e}")
        await _safe_speak(voice, "I had trouble typing the email into Gmail.")
        return

    confirmed = await _wait_for_send_confirmation(voice)
    if not confirmed:
        return

    try:
        pyautogui.hotkey("ctrl", "enter")
        logger.tools("[VoiceMsg] Email send hotkey pressed (Ctrl+Enter).")
    except Exception as e:
        logger.error(f"[VoiceMsg] Failed to press send in Gmail: {e}")
        await _safe_speak(voice, "I tried to send the email but something went wrong.")
        return

    await _safe_speak(voice, "Your email should be sent now.")

def _resolve_whatsapp_name(spoken: str) -> str:
    """
    Map spoken contact name to a WhatsApp search string.
    Just checks the CONTACT_WHATSAPP mapping, otherwise returns original.
    """
    key = _normalize_name(spoken)
    return CONTACT_WHATSAPP.get(key, spoken)

async def _whatsapp_flow(voice, initial_recipient: Optional[str]) -> None:
    """
    WhatsApp message flow using WhatsApp Web in Chrome.

    Simpler + safer version:
    - I open WhatsApp Web in Chrome.
    - YOU manually click the contact chat.
    - Then you say "ready".
    - After that I take your message by voice and send it.
    """
    await _safe_speak(voice, "Okay, I will send a WhatsApp message.")

    whatsapp_url = "https://web.whatsapp.com/"

    try:
        msg = control_app("chrome", "open")
        logger.tools(f"[VoiceMsg] control_app(chrome, open) -> {msg}")
    except Exception as e:
        logger.error(f"[VoiceMsg] Failed to open Chrome for WhatsApp: {e}")
        await _safe_speak(voice, "I could not open Chrome.")
        return

    await asyncio.sleep(5)

    try:
        webbrowser.open(whatsapp_url, new=2)
    except Exception as e:
        logger.error(f"[VoiceMsg] webbrowser.open WhatsApp failed: {e}")
        await _safe_speak(voice, "I could not open WhatsApp Web in the browser.")
        return

    await _safe_speak(
        voice,
        "Make sure WhatsApp Web is logged in. "
        "Now click on the chat of the person you want to message. "
        "When the correct chat is open on the screen, say 'ready'."
    )

    while True:
        text = await _listen_once(voice, timeout=15, phrase_time_limit=4)
        if not text:
            await _safe_speak(voice, "Say 'ready' when the chat is open, or 'cancel' to stop.")
            continue

        t = text.lower()
        if "ready" in t:
            break
        if "cancel" in t or "stop" in t:
            await _safe_speak(voice, "Okay, I will not send a WhatsApp message.")
            return

        await _safe_speak(voice, "Please say 'ready' when the chat is open, or 'cancel' to stop.")

    message_body = await _ask_and_listen(
        voice,
        "What is your message?",
        retries=3,
        timeout=10,
        phrase_time_limit=10,
    )
    if not message_body:
        await _safe_speak(voice, "I couldn't hear the message. Cancelling WhatsApp message.")
        return

    await _safe_speak(voice, f"You said: {message_body}. I will type it in WhatsApp.")

    try:
        pyautogui.typewrite(message_body, interval=0.03)
    except Exception as e:
        logger.error(f"[VoiceMsg] Failed to type WhatsApp message: {e}")
        await _safe_speak(voice, "I couldn't type the message into WhatsApp.")
        return

    confirmed = await _wait_for_send_confirmation(voice)
    if not confirmed:
        return

    try:
        pyautogui.press("enter")
        logger.tools("[VoiceMsg] WhatsApp message send (Enter key).")
    except Exception as e:
        logger.error(f"[VoiceMsg] Failed to press send in WhatsApp: {e}")
        await _safe_speak(voice, "I tried to send the WhatsApp message but something went wrong.")
        return

    await _safe_speak(voice, "Your WhatsApp message should be sent now.")
