import os
import sys
import threading
import asyncio
import logging
import time
import re
from datetime import datetime
from queue import Queue, Empty
from typing import Optional, Any, List

from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = current_dir
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

import subprocess
import customtkinter as ctk
from customtkinter import CTkInputDialog

import src.logger as logger

from src.user_profile import load_user_profile, save_user_profile

from src import diagnostics

from src.agent import create_axylo_agent
from src.agent import _shorten_text, _sanitize_for_speech
from src.voice_io import VoiceHandler
from src.voice_typing import start_voice_typing
from src.voice_messaging import start_voice_messaging
from src.smart_writer import handle_smart_ai_writing
from google.adk.runners import InMemoryRunner

BG_MAIN = "#020617"            
PANEL_MAIN = "#0F172A"        
PANEL_ELEVATED = "#111827"     
ACCENT_PRIMARY = "#F97316"      
ACCENT_SECONDARY = "#22D3EE"   
USER_BUBBLE = "#E5F2FF"        
BOT_BUBBLE = "#020617" 
TEXT_PRIMARY = "#0F172A"
TEXT_PRIMARY_ON_DARK = "#E5E7EB"
TEXT_MUTED = "#9CA3AF"
BORDER_SUBTLE = "#4B5563"

TITLE_FONT = ("Segoe UI", 20, "bold")
SUBTITLE_FONT = ("Segoe UI", 11)
MSG_FONT = ("Consolas", 13)
META_FONT = ("Segoe UI", 9)

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class GuiLogHandler(logging.Handler):
    """
    Logging handler that pushes formatted log lines into a thread-safe queue.
    GUI polls this queue and appends to the log panel.
    """

    def __init__(self, queue: Queue, level=logging.INFO):
        super().__init__(level=level)
        self.queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{record.levelname}] {msg}"
        try:
            self.queue.put_nowait(line)
        except Exception:
            pass

def attach_gui_logger(queue: Queue) -> None:
    """
    Attach GuiLogHandler to your main app logger (ai_agent) and root.
    This does NOT remove existing handlers (console/file remain intact).
    """
    gui_handler = GuiLogHandler(queue)
    gui_handler.setLevel(logging.INFO)
    gui_handler.setFormatter(logging.Formatter("%(message)s"))

    core_logger = logging.getLogger("ai_agent")
    core_logger.addHandler(gui_handler)

    logging.getLogger().addHandler(gui_handler)
    
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

class AgentGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Axylo Voice Agent")
        self.geometry("980x720")
        self.minsize(880, 640)
        self.configure(fg_color=BG_MAIN)

        self.grid_columnconfigure(0, weight=3)  
        self.grid_columnconfigure(1, weight=2)  
        self.grid_rowconfigure(2, weight=1)

        self.chat_row = 0
        self.agent_running = False
        self.voice_enabled = True
        self.mic_enabled = True

        self.voice: Optional[VoiceHandler] = None
        self.runner: Optional[InMemoryRunner] = None
        self.loop_thread: Optional[threading.Thread] = None
        self.agent_loop: Optional[asyncio.AbstractEventLoop] = None
        self.stop_event = threading.Event()

        self.in_session: bool = False

        self.last_response_ms: Optional[float] = None

        self.log_queue: Queue[str] = Queue()
        self.all_logs: List[str] = []
        self.current_log_filter: str = "All"
        self.current_log_search: str = ""
        
        self.user_profile = load_user_profile()

        self.mic_chip = None
        self.llm_chip = None
        self.tts_chip = None
        self.metrics_chip = None

        attach_gui_logger(self.log_queue)

        self._build_top_bar()
        self._build_quick_actions()
        self._build_chat_panel()
        self._build_log_panel()
        self._build_bottom_controls()

        self.display_message(
            "Click 'Start Agent'!",
            sender="bot",
        )

        self.after(150, self._poll_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_top_bar(self):
        self.top_bar = ctk.CTkFrame(
            self,
            fg_color=PANEL_MAIN,
            corner_radius=0,
        )
        self.top_bar.grid(row=0, column=0, columnspan=2, sticky="new")
        self.top_bar.grid_columnconfigure(0, weight=1)
        self.top_bar.grid_columnconfigure(1, weight=0)
        self.top_bar.grid_columnconfigure(2, weight=0)
        self.top_bar.grid_columnconfigure(3, weight=0)

        self.title_label = ctk.CTkLabel(
            self.top_bar,
            text="Axylo",
            font=TITLE_FONT,
            text_color=ACCENT_SECONDARY,
        )
        self.title_label.grid(row=0, column=0, padx=18, pady=(10, 0), sticky="w")

        self.status_dot = ctk.CTkLabel(
            self.top_bar,
            text="●",
            font=("Segoe UI", 18, "bold"),
            text_color="#FACC15", 
        )
        self.status_dot.grid(row=0, column=1, padx=(0, 8), pady=(8, 0), sticky="e")

        self.chat_btn = ctk.CTkButton(
            self.top_bar,
            text="Chat bot",
            width=110,
            height=30,
            command=self.open_chat_window,
            font=("Segoe UI", 11, "bold"),
            fg_color=PANEL_ELEVATED,
            hover_color="#1D4ED8",
            text_color=TEXT_PRIMARY_ON_DARK,
            corner_radius=999,
            border_width=1,
            border_color=BORDER_SUBTLE,
        )
        self.chat_btn.grid(row=0, column=2, padx=(0, 16), pady=(8, 0), sticky="e")
        
        self.profile_btn = ctk.CTkButton(
            self.top_bar,
            text="My profile",
            width=110,
            height=30,
            command=self.open_profile_dialog,
            font=("Segoe UI", 11, "bold"),
            fg_color=PANEL_ELEVATED,
            hover_color="#1D4ED8",
            text_color=TEXT_PRIMARY_ON_DARK,
            corner_radius=999,
            border_width=1,
            border_color=BORDER_SUBTLE,
        )
        self.profile_btn.grid(row=0, column=3, padx=(0, 16), pady=(8, 0), sticky="e")

        self.status_label = ctk.CTkLabel(
            self.top_bar,
            text="Idle • Agent not started",
            font=SUBTITLE_FONT,
            text_color=TEXT_MUTED,
        )
        self.status_label.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="w")

        divider = ctk.CTkFrame(
            self,
            fg_color=ACCENT_PRIMARY,
            height=2,
            corner_radius=0,
        )
        divider.grid(row=0, column=0, columnspan=2, sticky="sew", pady=(56, 0))

    def _build_quick_actions(self):
        frame = ctk.CTkFrame(
            self,
            fg_color=BG_MAIN,
            corner_radius=0,
        )
        frame.grid(row=1, column=0, columnspan=2, sticky="new", padx=10, pady=(4, 0))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=0)

        left = ctk.CTkFrame(
            frame,
            fg_color="transparent",
            corner_radius=0,
        )
        left.grid(row=0, column=0, sticky="w", padx=(6, 0), pady=4)

        qa_label = ctk.CTkLabel(
            left,
            text="Quick actions:",
            font=META_FONT,
            text_color=TEXT_MUTED,
        )
        qa_label.pack(side="left", padx=(2, 6))

        def make_qa_btn(text: str, cmd):
            return ctk.CTkButton(
                left,
                text=text,
                width=110,
                height=30,
                command=cmd,
                font=("Segoe UI", 11),
                fg_color=PANEL_ELEVATED,
                hover_color="#1F2937",
                text_color=TEXT_PRIMARY_ON_DARK,
                corner_radius=999,
                border_width=1,
                border_color=BORDER_SUBTLE,
            )

        btn_sw = make_qa_btn("Write code / mails", self._quick_smart_write)
        btn_sw.pack(side="left", padx=(0, 6))

        btn_vt = make_qa_btn("Voice Typing", self._quick_voice_typing)
        btn_vt.pack(side="left", padx=(0, 6))

        btn_vm = make_qa_btn("Send Msg", self._quick_voice_messaging)
        btn_vm.pack(side="left", padx=(0, 0))

        right = ctk.CTkFrame(
            frame,
            fg_color=PANEL_MAIN,
            corner_radius=999,
        )
        right.grid(row=0, column=1, sticky="e", padx=(4, 8), pady=4)
        right.grid_columnconfigure(0, weight=0)
        right.grid_columnconfigure(1, weight=0)
        right.grid_columnconfigure(2, weight=0)
        right.grid_columnconfigure(3, weight=0)

        self.mic_chip = ctk.CTkLabel(
            right,
            text="Mic: Continuous",
            font=META_FONT,
            text_color=ACCENT_SECONDARY,
        )
        self.mic_chip.grid(row=0, column=0, padx=(10, 6), pady=4)

        self.llm_chip = ctk.CTkLabel(
            right,
            text="LLM: Idle",
            font=META_FONT,
            text_color=TEXT_MUTED,
        )
        self.llm_chip.grid(row=0, column=1, padx=(6, 6), pady=4)

        self.tts_chip = ctk.CTkLabel(
            right,
            text="TTS: ON",
            font=META_FONT,
            text_color=ACCENT_SECONDARY,
        )
        self.tts_chip.grid(row=0, column=2, padx=(6, 6), pady=4)

        self.metrics_chip = ctk.CTkLabel(
            right,
            text="Last LLM: –",
            font=META_FONT,
            text_color=TEXT_MUTED,
        )
        self.metrics_chip.grid(row=0, column=3, padx=(6, 10), pady=4)

        self._update_chips_mic()
        self._update_chips_tts(error=False)
        self._update_chips_llm(state="idle")

    def _build_chat_panel(self):
        self.chat_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=BG_MAIN,
            border_width=0,
            corner_radius=0,
        )
        self.chat_frame.grid(row=2, column=0, padx=(16, 8), pady=(8, 12), sticky="nsew")
        self.chat_frame.grid_columnconfigure(0, weight=1)

    def _build_log_panel(self):
        outer = ctk.CTkFrame(
            self,
            fg_color=PANEL_MAIN,
            corner_radius=12,
        )
        outer.grid(row=2, column=1, padx=(8, 16), pady=(8, 12), sticky="nsew")
        outer.grid_rowconfigure(2, weight=1) 
        outer.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            outer,
            text="Agent Logs",
            font=("Segoe UI", 14, "bold"),
            text_color=ACCENT_SECONDARY,
        )
        title.grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")

        subtitle = ctk.CTkLabel(
            outer,
            text="Internal actions, tools, search, and status messages.",
            font=META_FONT,
            text_color=TEXT_MUTED,
        )
        subtitle.grid(row=0, column=0, padx=12, pady=(30, 4), sticky="w")

        filter_frame = ctk.CTkFrame(
            outer,
            fg_color="transparent",
            corner_radius=0,
        )
        filter_frame.grid(row=1, column=0, padx=10, pady=(4, 4), sticky="ew")
        filter_frame.grid_columnconfigure(0, weight=0)
        filter_frame.grid_columnconfigure(1, weight=0)
        filter_frame.grid_columnconfigure(2, weight=1)

        filter_label = ctk.CTkLabel(
            filter_frame,
            text="Filter:",
            font=META_FONT,
            text_color=TEXT_MUTED,
        )
        filter_label.grid(row=0, column=0, padx=(2, 6), pady=0, sticky="w")

        self.log_filter_combo = ctk.CTkComboBox(
            filter_frame,
            values=["All", "User", "Agent", "Voice", "Tools", "Search", "Error"],
            width=120,
            command=self._on_log_filter_change,
            font=("Segoe UI", 11),
            fg_color=PANEL_ELEVATED,
            button_color=PANEL_ELEVATED,
            text_color=TEXT_PRIMARY_ON_DARK,
            border_color=BORDER_SUBTLE,
        )
        self.log_filter_combo.set("All")
        self.log_filter_combo.grid(row=0, column=1, padx=(0, 8), pady=0, sticky="w")

        self.log_search_entry = ctk.CTkEntry(
            filter_frame,
            placeholder_text="Search logs…",
            fg_color=PANEL_ELEVATED,
            border_color=BORDER_SUBTLE,
            text_color=TEXT_PRIMARY_ON_DARK,
            height=28,
        )
        self.log_search_entry.grid(row=0, column=2, padx=(0, 2), pady=0, sticky="ew")
        self.log_search_entry.bind("<KeyRelease>", self._on_log_search_change)

        self.log_text = ctk.CTkTextbox(
            outer,
            fg_color=PANEL_ELEVATED,
            text_color=TEXT_PRIMARY_ON_DARK,
            font=("Consolas", 11),
            corner_radius=10,
            border_width=1,
            border_color=BORDER_SUBTLE,
        )
        self.log_text.grid(row=2, column=0, padx=10, pady=(4, 10), sticky="nsew")
        self.log_text.configure(state="disabled")

    def _build_bottom_controls(self):
        bottom = ctk.CTkFrame(
            self,
            fg_color=BG_MAIN,
            corner_radius=0,
        )
        bottom.grid(row=3, column=0, columnspan=2, sticky="sew", padx=10, pady=(0, 8))
        bottom.grid_columnconfigure(0, weight=0)
        bottom.grid_columnconfigure(1, weight=1)
        bottom.grid_columnconfigure(2, weight=0)
        bottom.grid_columnconfigure(3, weight=0)
        bottom.grid_columnconfigure(4, weight=0)
        bottom.grid_columnconfigure(5, weight=0)
        bottom.grid_columnconfigure(6, weight=0)
        bottom.grid_columnconfigure(7, weight=0)

        spacer = ctk.CTkLabel(
            bottom,
            text="",
            fg_color="transparent",
        )
        spacer.grid(row=0, column=0, sticky="w")
        
        self.stop_tts_btn = ctk.CTkButton(
            bottom,
            text="Stop talking",
            width=120,
            height=44,
            command=self.stop_tts_now,
            font=("Segoe UI", 12, "bold"),
            fg_color=PANEL_MAIN,
            hover_color="#374151",
            text_color=ACCENT_PRIMARY,
            corner_radius=999,
            border_width=1,
            border_color=BORDER_SUBTLE,
        )
        self.stop_tts_btn.grid(row=0, column=0, padx=(10, 10), pady=4, sticky="w")

        self.start_btn = ctk.CTkButton(
            bottom,
            text="Start Agent",
            width=120,
            height=44,
            command=self.start_agent,
            font=("Segoe UI", 12, "bold"),
            fg_color="#16A34A",
            hover_color="#22C55E",
            text_color="white",
            corner_radius=999,
        )
        self.start_btn.grid(row=0, column=2, padx=(0, 8), pady=4, sticky="e")

        self.stop_btn = ctk.CTkButton(
            bottom,
            text="Stop",
            width=80,
            height=44,
            command=self.stop_agent,
            font=("Segoe UI", 12, "bold"),
            fg_color="#DC2626",
            hover_color="#EF4444",
            text_color="white",
            corner_radius=999,
            state="disabled",
        )
        self.stop_btn.grid(row=0, column=3, padx=(0, 8), pady=4, sticky="e")

        self.restart_btn = ctk.CTkButton(
            bottom,
            text="Restart",
            width=90,
            height=44,
            command=self.restart_agent,
            font=("Segoe UI", 12, "bold"),
            fg_color="#F97316",
            hover_color="#FB923C",
            text_color="white",
            corner_radius=999,
            state="disabled",
        )
        self.restart_btn.grid(row=0, column=4, padx=(0, 8), pady=4, sticky="e")

        self.voice_btn = ctk.CTkButton(
            bottom,
            text="Voice: ON",
            width=120,
            height=44,
            command=self.toggle_voice,
            font=("Segoe UI", 12, "bold"),
            fg_color=PANEL_MAIN,
            hover_color="#374151",
            text_color=ACCENT_SECONDARY,
            corner_radius=999,
            border_width=1,
            border_color=BORDER_SUBTLE,
        )
        self.voice_btn.grid(row=0, column=5, padx=(0, 8), pady=4, sticky="e")

        self.mic_btn = ctk.CTkButton(
            bottom,
            text="Mic: ON",
            width=110,
            height=44,
            command=self.toggle_mic,
            font=("Segoe UI", 12, "bold"),
            fg_color=PANEL_MAIN,
            hover_color="#374151",
            text_color=ACCENT_SECONDARY,
            corner_radius=999,
            border_width=1,
            border_color=BORDER_SUBTLE,
        )
        self.mic_btn.grid(row=0, column=6, padx=(0, 0), pady=4, sticky="e")
        
        self.diag_btn = ctk.CTkButton(
            bottom,
            text="Run diagnostics",
            width=140,
            height=44,
            command=self._run_diagnostics_clicked,
            font=("Segoe UI", 12, "bold"),
            fg_color=PANEL_MAIN,
            hover_color="#4B5563",
            text_color=TEXT_MUTED,
            corner_radius=999,
            border_width=1,
            border_color=BORDER_SUBTLE,
        )
        self.diag_btn.grid(row=0, column=7, padx=(8, 0), pady=4, sticky="e")

    def display_message(self, text: str, sender: str = "bot"):
        """
        Render a chat bubble in the scrollable chat panel.
        sender: "user" or "bot"
        """
        if not hasattr(self, "chat_frame") or self.chat_frame is None:
            return

        row = self.chat_row
        self.chat_row += 1

        wrapper = ctk.CTkFrame(
            self.chat_frame,
            fg_color="transparent",
        )
        wrapper.grid(row=row, column=0, sticky="ew", padx=4, pady=(4, 2))
        wrapper.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(
            wrapper,
            fg_color="transparent",
        )
        inner.grid(row=0, column=0, sticky="e" if sender == "user" else "w")

        if sender == "user":
            bg_color = USER_BUBBLE
            text_color = TEXT_PRIMARY
            anchor_val = "e"
            meta_anchor = "e"
            label_name = "You"
        else:
            bg_color = BOT_BUBBLE
            text_color = TEXT_PRIMARY_ON_DARK
            anchor_val = "w"
            meta_anchor = "w"
            label_name = "Axylo"

        name_label = ctk.CTkLabel(
            inner,
            text=label_name,
            font=META_FONT,
            text_color=ACCENT_SECONDARY if sender == "bot" else ACCENT_PRIMARY,
        )
        name_label.grid(row=0, column=0, padx=10, pady=(2, 0), sticky=anchor_val)

        bubble = ctk.CTkLabel(
            inner,
            text=text,
            fg_color=bg_color,
            text_color=text_color,
            wraplength=420,
            corner_radius=18,
            padx=14,
            pady=10,
            justify="left" if sender == "bot" else "right",
            font=MSG_FONT,
        )
        bubble.grid(row=1, column=0, padx=10, pady=(2, 0), sticky=anchor_val)
        
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_columnconfigure(1, weight=0)

        timestamp = datetime.now().strftime("%H:%M:%S")
        meta = ctk.CTkLabel(
            inner,
            text=timestamp,
            font=META_FONT,
            text_color=TEXT_MUTED,
        )
        meta.grid(row=2, column=0, padx=10, pady=(0, 6), sticky=meta_anchor)
        
        if sender == "bot":
            copy_btn = ctk.CTkButton(
                inner,
                text="Copy",
                width=60,
                height=22,
                font=("Segoe UI", 9),
                fg_color="transparent",
                hover_color=PANEL_ELEVATED,
                text_color=TEXT_MUTED,
                command=lambda t=text: self.copy_to_clipboard(t),
                corner_radius=999,
                border_width=0,
            )

            copy_btn.grid(
                row=2,
                column=1,
                padx=(0, 10),
                pady=(0, 6),
                sticky="e",
            )

        self.chat_frame.update_idletasks()
        try:
            self.chat_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def copy_to_clipboard(self, text: str) -> None:
        """
        Copy the given text to the system clipboard.
        """
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def _poll_log_queue(self):
        new_lines = False
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.all_logs.append(line)
                new_lines = True
        except Empty:
            pass

        if new_lines:
            self._refresh_log_view()

        self.after(150, self._poll_log_queue)

    def _line_matches_filters(self, line: str) -> bool:
        mode = self.current_log_filter

        if mode == "User" and "[USER]" not in line:
            return False
        if mode == "Agent" and "[AGENT]" not in line:
            return False
        if mode == "Voice" and "[VOICE]" not in line:
            return False
        if mode == "Tools" and "[TOOLS]" not in line:
            return False
        if mode == "Search" and "[SEARCH]" not in line:
            return False
        if mode == "Error" and ("[ERROR]" not in line and "ERROR" not in line):
            return False

        if self.current_log_search:
            if self.current_log_search.lower() not in line.lower():
                return False

        return True

    def _refresh_log_view(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        for line in self.all_logs:
            if self._line_matches_filters(line):
                self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_log_filter_change(self, choice: str):
        self.current_log_filter = choice or "All"
        self._refresh_log_view()

    def _on_log_search_change(self, event):
        self.current_log_search = self.log_search_entry.get().strip()
        self._refresh_log_view()

    def _set_status(self, text: str, color: str = "#FACC15"):
        try:
            self.status_label.configure(text=text)
            self.status_dot.configure(text_color=color)
        except Exception:
            pass

    def _update_chips_llm(self, state: str):
        """
        state: "idle" or "thinking"
        """
        if not self.llm_chip or not self.metrics_chip:
            return

        if state == "thinking":
            self.llm_chip.configure(text="LLM: Thinking", text_color=ACCENT_PRIMARY)
        else:
            self.llm_chip.configure(text="LLM: Ready", text_color=TEXT_MUTED)

        if self.last_response_ms is not None:
            self.metrics_chip.configure(
                text=f"Last LLM: {int(self.last_response_ms)} ms",
                text_color=TEXT_MUTED,
            )
        else:
            self.metrics_chip.configure(text="Last LLM: –", text_color=TEXT_MUTED)

    def _update_chips_mic(self):
        if not self.mic_chip:
            return
        if self.mic_enabled:
            self.mic_chip.configure(text="Mic: Continuous", text_color=ACCENT_SECONDARY)
        else:
            self.mic_chip.configure(text="Mic: Muted", text_color=TEXT_MUTED)

    def _update_chips_tts(self, error: bool = False):
        if not self.tts_chip:
            return
        if not self.voice_enabled:
            self.tts_chip.configure(text="TTS: Muted", text_color=TEXT_MUTED)
        else:
            if error:
                self.tts_chip.configure(text="TTS: Error", text_color=ACCENT_PRIMARY)
            else:
                self.tts_chip.configure(text="TTS: ON", text_color=ACCENT_SECONDARY)

    def start_agent(self):
        """
        Start the full voice agent loop in a background thread.
        Behavior: same as your terminal main.py, but with GUI hooks.
        """
        if self.agent_running:
            self._set_status("Agent already running.", color="#22C55E")
            return

        self.stop_event.clear()
        self.agent_running = True
        self.last_response_ms = None
        self._set_status("Starting agent…", color="#FACC15")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.restart_btn.configure(state="normal")
        self._update_chips_llm(state="idle")
        self._update_chips_mic()
        self._update_chips_tts(error=False)

        self.loop_thread = threading.Thread(
            target=self._run_async_agent_loop_thread,
            daemon=True,
        )
        self.loop_thread.start()

    def stop_agent(self):
        """
        Request graceful shutdown of the agent loop.
        """
        if not self.agent_running:
            self._set_status("Agent is not running.", color="#FACC15")
            return

        self._set_status("Stopping agent…", color="#F97316")
        self.stop_event.set()
        self.stop_btn.configure(state="disabled")
        self.restart_btn.configure(state="disabled")

    def _restart_worker(self):
        """
        Runs in a background thread: wait for current loop to stop, then restart.
        """
        old_thread = self.loop_thread
        if old_thread and old_thread.is_alive():
            try:
                old_thread.join(timeout=3.0)
            except Exception:
                pass

        self.after(0, self._restart_after_stopped)

    def _restart_after_stopped(self):
        self._set_status("Restarting agent…", color="#F97316")
        self.stop_event.clear()
        self.agent_running = False
        self.start_agent()

    def restart_agent(self):
        """
        Restart the agent: stop current loop and start a fresh one.
        """
        if not self.agent_running:
            self.start_agent()
            return

        self.stop_event.set()
        self.stop_btn.configure(state="disabled")
        self.restart_btn.configure(state="disabled")
        t = threading.Thread(target=self._restart_worker, daemon=True)
        t.start()

    def toggle_voice(self):
        """
        Toggle TTS output on/off. Affects all voice.speak() calls via a wrapper.
        """
        self.voice_enabled = not self.voice_enabled
        if self.voice_enabled:
            self.voice_btn.configure(text="Voice: ON", text_color=ACCENT_SECONDARY)
            self._set_status("Voice output enabled.", color="#22C55E")
        else:
            self.voice_btn.configure(text="Voice: OFF", text_color=TEXT_MUTED)
            self._set_status("Voice output muted.", color="#FACC15")
        self._update_chips_tts(error=False)

    def toggle_mic(self):
        """
        Toggle microphone listening on/off. When OFF, the agent stays running
        but does not listen for new audio until re-enabled.
        """
        self.mic_enabled = not self.mic_enabled
        if self.mic_enabled:
            self.mic_btn.configure(text="Mic: ON", text_color=ACCENT_SECONDARY)
            self._set_status("Mic enabled.", color="#22C55E")
        else:
            self.mic_btn.configure(text="Mic: OFF", text_color=TEXT_MUTED)
            self._set_status("Online • Mic muted", color="#FACC15")
        self._update_chips_mic()

    def open_chat_window(self):
        """
        Launch the separate chatbot UI window (chatbot_ui.py).
        """
        try:
            script_path = os.path.join(project_root, "src", "chatbot_ui.py")
            if not os.path.exists(script_path):
                self.display_message(
                    "Chat window script not found at src/chatbot_ui.py.",
                    sender="bot",
                )
                return
            subprocess.Popen([sys.executable, script_path])
            self.display_message("Opened chat window.", sender="bot")
        except Exception as e:
            logger.error(f"Failed to open chat window: {e}")
            self.display_message("Failed to open chat window.", sender="bot")
            
    def open_profile_dialog(self):
        """
        Small window to edit persistent user info (name, age, etc.).
        Data is saved to user_profile.json and used by the agent for personalization.
        """
        win = ctk.CTkToplevel(self)
        win.title("Your profile")
        win.geometry("360x260")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        profile = self.user_profile or {}

        win.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(win, text="Name:").grid(row=0, column=0, padx=12, pady=(12, 4), sticky="e")
        name_entry = ctk.CTkEntry(win, width=220)
        name_entry.grid(row=0, column=1, padx=12, pady=(12, 4), sticky="ew")
        name_entry.insert(0, (profile.get("name") or ""))

        ctk.CTkLabel(win, text="Age:").grid(row=1, column=0, padx=12, pady=4, sticky="e")
        age_entry = ctk.CTkEntry(win, width=220)
        age_entry.grid(row=1, column=1, padx=12, pady=4, sticky="ew")
        age_val = profile.get("age")
        age_entry.insert(0, str(age_val) if age_val is not None else "")

        ctk.CTkLabel(win, text="Role:").grid(row=2, column=0, padx=12, pady=4, sticky="e")
        role_entry = ctk.CTkEntry(win, width=220)
        role_entry.grid(row=2, column=1, padx=12, pady=4, sticky="ew")
        role_entry.insert(0, (profile.get("role") or ""))

        ctk.CTkLabel(win, text="Location:").grid(row=3, column=0, padx=12, pady=4, sticky="e")
        loc_entry = ctk.CTkEntry(win, width=220)
        loc_entry.grid(row=3, column=1, padx=12, pady=4, sticky="ew")
        loc_entry.insert(0, (profile.get("location") or ""))

        ctk.CTkLabel(win, text="Notes:").grid(row=4, column=0, padx=12, pady=4, sticky="e")
        notes_entry = ctk.CTkEntry(win, width=220)
        notes_entry.grid(row=4, column=1, padx=12, pady=4, sticky="ew")
        notes_entry.insert(0, (profile.get("notes") or ""))

        def on_save():
            new_profile = {
                "name": name_entry.get().strip() or None,
                "age": age_entry.get().strip() or None,
                "role": role_entry.get().strip() or None,
                "location": loc_entry.get().strip() or None,
                "notes": notes_entry.get().strip() or None,
            }
            save_user_profile(new_profile)
            self.user_profile = new_profile
            win.destroy()
            self.display_message(
                "Got it. I'll remember this profile for future conversations.",
                sender="bot",
            )

        def on_cancel():
            win.destroy()

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.grid(row=5, column=0, columnspan=2, pady=(12, 10))

        save_btn = ctk.CTkButton(btn_frame, text="Save", width=80, command=on_save)
        save_btn.grid(row=0, column=0, padx=8)

        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=80,
            fg_color=PANEL_MAIN,
            hover_color="#374151",
            command=on_cancel,
        )
        cancel_btn.grid(row=0, column=1, padx=8)
        
    def stop_tts_now(self):
        """
        Immediately stop current speech playback, without stopping the agent.
        """
        if self.voice is not None:
            try:
                self.voice.stop_speaking()
                self._set_status("Speech stopped.", color="#FACC15")
                self._update_chips_tts(error=False)
            except Exception as e:
                logger.error(f"Failed to stop TTS: {e}")
        
    def _run_diagnostics_clicked(self):
        """
        Run all registered diagnostics in a background thread and show
        the results in a popup window (plus a short note in chat).
        """
        self.display_message("Running diagnostics…", sender="bot")

        try:
            self.diag_btn.configure(state="disabled")
        except Exception:
            pass

        def worker():
            context = {
                "agent_running": self.agent_running,
                "mic_enabled": self.mic_enabled,
                "voice_enabled": self.voice_enabled,
            }

            try:
                results = diagnostics.run_all_diagnostics_sync(context)
            except Exception as e:
                summary_text = f"Diagnostics failed with an unexpected error:\n{e}"
            else:
                lines = []
                status_counts = {"ok": 0, "warning": 0, "error": 0, "info": 0}

                for res in results:
                    status_counts[res.status] = status_counts.get(res.status, 0) + 1
                    icon = {
                        "ok": "✅",
                        "warning": "⚠️",
                        "error": "❌",
                        "info": "ℹ️",
                    }.get(res.status, "•")
                    line = f"{icon} {res.id}: {res.message}"
                    if res.details:
                        line += f"\n    Details: {res.details}"
                    lines.append(line)

                header = (
                    f"Diagnostics complete.\n"
                    f"- OK: {status_counts.get('ok', 0)}\n"
                    f"- Warnings: {status_counts.get('warning', 0)}\n"
                    f"- Errors: {status_counts.get('error', 0)}\n"
                    f"- Info: {status_counts.get('info', 0)}\n"
                )
                summary_text = header + "\n" + "\n\n".join(lines)

            def on_done():
                try:
                    self.diag_btn.configure(state="normal")
                except Exception:
                    pass

                self.display_message(
                    "Diagnostics finished. Showing details in a separate window.",
                    sender="bot",
                )

                self._show_diagnostics_window(summary_text)

            self.after(0, on_done)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        
    def _show_diagnostics_window(self, summary_text: str):
        """
        Show diagnostics results in a popup window with a scrollable text box
        and a Close button.
        """
        win = ctk.CTkToplevel(self)
        win.title("Diagnostics results")
        win.geometry("700x500")
        win.minsize(520, 360)
        win.transient(self)
        win.grab_set()

        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(0, weight=0)
        win.grid_rowconfigure(1, weight=1)
        win.grid_rowconfigure(2, weight=0)

        title = ctk.CTkLabel(
            win,
            text="System diagnostics",
            font=("Segoe UI", 18, "bold"),
        )
        title.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

        text_box = ctk.CTkTextbox(
            win,
            fg_color=PANEL_ELEVATED,
            border_width=1,
            border_color=BORDER_SUBTLE,
            text_color=TEXT_PRIMARY_ON_DARK,
            font=("Consolas", 11),
        )
        text_box.grid(row=1, column=0, padx=16, pady=(4, 8), sticky="nsew")

        summary_text = summary_text or "No diagnostics output."
        text_box.insert("1.0", summary_text)
        text_box.configure(state="disabled")

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.grid(row=2, column=0, pady=(0, 12))

        close_btn = ctk.CTkButton(
            btn_frame,
            text="Close",
            width=100,
            height=36,
            corner_radius=999,
            fg_color=PANEL_MAIN,
            hover_color="#374151",
            text_color=TEXT_MUTED,
            command=win.destroy,
        )
        close_btn.grid(row=0, column=0, padx=8, pady=4)

    def _dispatch_text_to_agent(self, text: str):
        """
        Send a text command into the running agent as if it was spoken.
        """
        if (
            not self.agent_running
            or self.agent_loop is None
            or self.voice is None
            or self.runner is None
        ):
            self.display_message(
                "Agent is not running yet. Click 'Start Agent' first.",
                sender="bot",
            )
            return

        cleaned = (text or "").strip()
        if not cleaned:
            return

        self.display_message(cleaned, sender="user")

        try:
            asyncio.run_coroutine_threadsafe(
                self._handle_with_request_id(cleaned, self.voice, self.runner),
                self.agent_loop,
            )
        except Exception as e:
            logging.getLogger("ai_agent").exception(
                "Failed to schedule quick action: %s", e
            )

    def _quick_smart_write(self):
        dlg = CTkInputDialog(
            text="What should I write?",
            title="Smart Writer",
        )
        prompt = dlg.get_input()
        if prompt:
            self._dispatch_text_to_agent("write " + prompt)

    def _quick_voice_typing(self):
        self._dispatch_text_to_agent("voice typing")

    def _quick_voice_messaging(self):
        self._dispatch_text_to_agent("send a message")

    def _run_async_agent_loop_thread(self):
        """
        Runs an asyncio event loop in a dedicated thread
        and executes _agent_loop() inside it.
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.agent_loop = loop
            loop.run_until_complete(self._agent_loop())
        except Exception:
            logging.getLogger("ai_agent").exception("Agent loop crashed")
        finally:
            try:
                if self.agent_loop is not None:
                    self.agent_loop.close()
            except Exception:
                pass
            self.agent_loop = None
            self.after(
                0,
                lambda: (
                    self._set_status("Idle • Agent stopped", color="#FACC15"),
                    self.start_btn.configure(state="normal"),
                    self.stop_btn.configure(state="disabled"),
                    self.restart_btn.configure(state="disabled"),
                ),
            )
            self.agent_running = False

    async def _handle_with_request_id(
        self, cleaned_input: str, voice: VoiceHandler, runner: InMemoryRunner
    ) -> bool:
        """
        Wraps _process_user_input with per-request request_id handling.
        Returns True if the loop should stop.
        """
        import uuid

        request_id = uuid.uuid4().hex[:8]
        logger.set_request_id(request_id)
        try:
            return await self._process_user_input(cleaned_input, voice, runner)
        finally:
            logger.set_request_id(None)

    async def _agent_loop(self):
        """
        Core voice agent loop.
        This is adapted from main.py:run_agent_loop, but wired to GUI.
        """
        voice = VoiceHandler(tts_voice=os.getenv("TTS_VOICE", "en-GB-RyanNeural"))
        self.voice = voice

        original_speak = voice.speak

        async def speak_wrapper(text: str, *args, **kwargs):
            if not self.voice_enabled:
                return
            try:
                await original_speak(text, *args, **kwargs)
                self.after(0, lambda: self._update_chips_tts(error=False))
            except Exception as e:
                logger.error(f"TTS speak failed: {e}")
                self.after(0, lambda: self._update_chips_tts(error=True))

        voice.speak = speak_wrapper 

        try:
            loop = asyncio.get_running_loop()
            voice.loop = loop
        except Exception:
            voice.loop = None

        agent = create_axylo_agent()
        runner = InMemoryRunner(agent=agent)
        runner.render_fn = lambda *args, **kwargs: None
        runner.debug = False

        self.runner = runner

        name = (self.user_profile or {}).get("name") if hasattr(self, "user_profile") else None
        if name:
            intro_text = f"Hi {name}! I'm Axylo. The voice of your smart world. How can I help you?"
        else:
            intro_text = "Hi! I'm Axylo. The voice of your smart world. How can I help you?"
            
        try:
            await voice.speak(intro_text)
        except Exception:
            pass
        self.after(0, lambda: self.display_message(intro_text, sender="bot"))
        self.after(
            0, lambda: self._set_status("Online • Listening…", color="#22C55E")
        )

        self.after(0, self._update_chips_mic)
        self.after(0, lambda: self._update_chips_llm(state="idle"))
        self.after(0, lambda: self._update_chips_tts(error=False))

        consecutive_empty = 0
        MAX_EMPTY_BEFORE_SLEEP = 20

        try:
            while not self.stop_event.is_set():
                if self.in_session:
                    await asyncio.sleep(0.2)
                    continue

                if not self.mic_enabled:
                    self.after(
                        0,
                        lambda: self._set_status(
                            "Online • Mic muted", color="#FACC15"
                        ),
                    )
                    await asyncio.sleep(0.2)
                    continue

                try:
                    self.after(
                        0,
                        lambda: self._set_status(
                            "Listening…", color="#60A5FA"
                        ),
                    )
                    user_input = await voice.listen_async(
                        timeout=5, phrase_time_limit=10
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Listen error: {e}")
                    user_input = ""

                if self.stop_event.is_set():
                    break

                if not user_input:
                    consecutive_empty += 1
                    if consecutive_empty >= MAX_EMPTY_BEFORE_SLEEP:
                        await asyncio.sleep(1.0)
                        consecutive_empty = 0
                    continue

                consecutive_empty = 0

                cleaned_input = user_input.strip()
                if cleaned_input:
                    self.after(
                        0,
                        lambda txt=cleaned_input: self.display_message(
                            txt, sender="user"
                        ),
                    )

                stop_flag = await self._handle_with_request_id(
                    cleaned_input, voice, runner
                )
                if stop_flag:
                    break

                self.after(
                    0,
                    lambda: self._set_status(
                        "Online • Listening…", color="#22C55E"
                    ),
                )

        except asyncio.CancelledError:
            try:
                await voice.speak("Shutting down.")
            except Exception:
                pass
        finally:
            try:
                close_fn = getattr(runner, "close", None) or getattr(
                    runner, "shutdown", None
                )
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
                cleanup_fn = getattr(voice, "cleanup_tempdir", None) or getattr(
                    voice, "cleanup", None
                )
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

    async def _process_user_input(
        self,
        cleaned_input: str,
        voice: VoiceHandler,
        runner: InMemoryRunner,
    ) -> bool:
        """
        Main intent handling logic (shutdown, smart writer, voice typing, messaging, LLM).
        Returns True if the agent loop should stop (shutdown phrase).
        """
        logger.user(cleaned_input)
        lower_input = cleaned_input.lower()

        if (
            "bye" in lower_input
            or "bye bye" in lower_input
            or "byebye" in lower_input
            or "bye-bye" in lower_input
            or "shut down" in lower_input
            or "shutdown" in lower_input
            or "shut-down" in lower_input
        ):
            goodbye_text = "Bye! Shutting down."
            try:
                await voice.speak(goodbye_text)
            except Exception:
                pass
            self.after(
                0,
                lambda: self.display_message(
                    goodbye_text, sender="bot"
                ),
            )
            return True

        if lower_input.startswith("write "):
            self.after(
                0,
                lambda: self.display_message(
                    "Starting smart AI writing…", sender="bot"
                ),
            )
            await handle_smart_ai_writing(cleaned_input, voice)
            return False

        if lower_input in ("voice typing", "start voice typing"):
            try:
                await voice.speak("Starting voice typing in Notepad.")
                self.after(
                    0,
                    lambda: self.display_message(
                        "Starting voice typing in Notepad…",
                        sender="bot",
                    ),
                )
            except Exception:
                pass
            
            prev_session = self.in_session
            self.in_session = True
            try:
                self.after(
                    0,
                    lambda: self._set_status(
                        "Voice typing session…", color="#60A5FA"
                    ),
                )
                await start_voice_typing(voice)
            except Exception as e:
                logger.error(f"Voice typing session error: {e}")
                try:
                    await voice.speak(
                        "Voice typing failed because of an internal error."
                    )
                except Exception:
                    pass
            finally:
                self.in_session = prev_session
                self.after(
                    0,
                    lambda: self._set_status(
                        "Online • Listening…", color="#22C55E"
                    ),
                )

            return False

        if lower_input.startswith("send a message") or lower_input.startswith(
            "send message"
        ):
            initial_recipient = None
            if " to " in lower_input:
                try:
                    initial_recipient = lower_input.split(" to ", 1)[1].strip()
                except Exception:
                    initial_recipient = None
            try:
                await voice.speak("Okay, I will help you send a message.")
                self.after(
                    0,
                    lambda: self.display_message(
                        "Okay, I will help you send a message.",
                        sender="bot",
                    ),
                )
            except Exception:
                pass
            prev_session = self.in_session
            self.in_session = True
            try:
                self.after(
                    0,
                    lambda: self._set_status(
                        "Voice messaging session…", color="#60A5FA"
                    ),
                )
                await start_voice_messaging(
                    voice, initial_recipient=initial_recipient
                )
            except Exception as e:
                logger.error(f"Voice messaging session error: {e}")
                try:
                    await voice.speak(
                        "Message sending failed because of an internal error."
                    )
                except Exception:
                    pass
            finally:
                self.in_session = prev_session
                self.after(
                    0,
                    lambda: self._set_status(
                        "Online • Listening…", color="#22C55E"
                    ),
                )

            return False

        self.after(
            0,
            lambda: self._set_status("Thinking…", color="#F97316"),
        )
        self.after(0, lambda: self._update_chips_llm(state="thinking"))

        start_t = time.perf_counter()
        final_text = ""

        try:
            result = await runner.run_debug(cleaned_input)

            if isinstance(result, (list, tuple)):
                for event in result:
                    try:
                        if hasattr(event, "is_final_response") and event.is_final_response():
                            content = getattr(event, "content", None)
                            parts = getattr(content, "parts", None) if content else None
                            if parts:
                                first = parts[0]
                                final_text = getattr(first, "text", str(first))
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

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Agent error: {e}")
            final_text = ""

        end_t = time.perf_counter()
        self.last_response_ms = (end_t - start_t) * 1000.0
        self.after(0, lambda: self._update_chips_llm(state="idle"))

        if final_text:
            logger.agent(final_text)
            self.after(
                0,
                lambda txt=final_text: self.display_message(
                    txt, sender="bot"
                ),
            )
            
            tts_text = make_tts_friendly(final_text)
            
            try:
                await voice.speak(final_text)
                self.after(0, lambda: self._update_chips_tts(error=False))
            except Exception as e:
                logger.error(f"Voice speak failed: {e}")
                self.after(0, lambda: self._update_chips_tts(error=True))
        else:
            fallback_text = (
                "I couldn't parse the agent's response. Please check logs."
            )
            self.after(
                0,
                lambda: self.display_message(
                    fallback_text, sender="bot"
                ),
            )
            try:
                await voice.speak(fallback_text)
            except Exception:
                pass

        return False

    def _on_close(self):
        self.stop_event.set()
        self.destroy()

def main():
    app = AgentGUI()
    app.mainloop()

if __name__ == "__main__":
    main()