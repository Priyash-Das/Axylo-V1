import json
import os
from typing import Dict, Any

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROFILE_PATH = os.path.join(_PROJECT_ROOT, "user_profile.json")

_DEFAULT_PROFILE: Dict[str, Any] = {
    "name": None,
    "age": None,
    "role": None,
    "location": None,
    "notes": None,
}

def load_user_profile() -> Dict[str, Any]:
    """
    Load the user's profile from disk.
    Always returns a dict with the keys in _DEFAULT_PROFILE.
    """
    profile = _DEFAULT_PROFILE.copy()

    try:
        if os.path.exists(_PROFILE_PATH):
            with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if k in profile:
                        profile[k] = v
    except Exception:
        pass

    return profile

def save_user_profile(profile: Dict[str, Any]) -> None:
    """
    Persist the profile to disk in a safe, normalized way.
    """
    data = _DEFAULT_PROFILE.copy()
    if isinstance(profile, dict):
        for k, v in profile.items():
            if k in data:
                data[k] = v

    try:
        os.makedirs(os.path.dirname(_PROFILE_PATH), exist_ok=True)
    except Exception:
        pass

    try:
        with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def format_profile_for_system_instruction(profile: Dict[str, Any]) -> str:
    """
    Turn the profile dict into a short text snippet for the LLM system prompt.
    Returns "" if nothing useful is set.
    """
    if not isinstance(profile, dict):
        return ""

    fields = []

    name = (profile.get("name") or "").strip()
    age = (profile.get("age") or "").strip() if isinstance(profile.get("age"), str) else profile.get("age")
    role = (profile.get("role") or "").strip()
    location = (profile.get("location") or "").strip()
    notes = (profile.get("notes") or "").strip()

    if name:
        fields.append(f"Name: {name}")
    if age:
        fields.append(f"Age: {age}")
    if role:
        fields.append(f"Role: {role}")
    if location:
        fields.append(f"Location: {location}")
    if notes:
        fields.append(f"Notes: {notes}")

    if not fields:
        return ""

    lines = ["User profile:", *[f"- {line}" for line in fields]]
    return "\n".join(lines)
