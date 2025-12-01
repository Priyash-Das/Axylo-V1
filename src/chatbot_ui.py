import sys
import os
import threading
import asyncio
import logging
import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import customtkinter as ctk
from src.agent import create_axylo_agent
from google.adk.runners import InMemoryRunner

BG_MAIN = "#0B1120"            
PANEL_MAIN = "#111827"         
PANEL_ELEVATED = "#1F2937"     
ACCENT_PRIMARY = "#F97316"     
ACCENT_SECONDARY = "#22D3EE"   
USER_BUBBLE = "#E5F2FF"        
BOT_BUBBLE = "#111827"         
TEXT_PRIMARY = "#0F172A"      
TEXT_PRIMARY_ON_DARK = "#E5E7EB"  
TEXT_MUTED = "#9CA3AF"         
BORDER_SUBTLE = "#4B5563"

TITLE_FONT = ("Segoe UI", 20, "bold")
SUBTITLE_FONT = ("Segoe UI", 11)
MSG_FONT = ("Consolas", 13)
INPUT_FONT = ("Consolas", 13)
BUTTON_FONT = ("Segoe UI", 12, "bold")
META_FONT = ("Segoe UI", 9)

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

logging.getLogger("asyncio").setLevel(logging.CRITICAL)
logging.getLogger("google_adk").setLevel(logging.ERROR)


class ChatbotWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Axylo Chat")
        self.geometry("560x840")
        self.minsize(520, 720)
        self.configure(fg_color=BG_MAIN)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.agent_factory = create_axylo_agent

        self.top_bar = ctk.CTkFrame(
            self,
            fg_color=PANEL_MAIN,
            corner_radius=0,
        )
        self.top_bar.grid(row=0, column=0, sticky="new")
        self.top_bar.grid_columnconfigure(0, weight=1)
        self.top_bar.grid_columnconfigure(1, weight=0)

        self.title_label = ctk.CTkLabel(
            self.top_bar,
            text="Axylo Chat Interface",
            font=TITLE_FONT,
            text_color=ACCENT_SECONDARY,
        )
        self.title_label.grid(row=0, column=0, padx=18, pady=(12, 0), sticky="w")

        self.status_dot = ctk.CTkLabel(
            self.top_bar,
            text="●",
            font=("Segoe UI", 18, "bold"),
            text_color=ACCENT_PRIMARY,
        )
        self.status_dot.grid(row=0, column=1, padx=(0, 18), pady=(10, 0), sticky="e")

        self.subtitle_label = ctk.CTkLabel(
            self.top_bar,
            text="Online • Local assistant • Realtime responses",
            font=SUBTITLE_FONT,
            text_color=TEXT_MUTED,
        )
        self.subtitle_label.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="w")

        self.divider = ctk.CTkFrame(
            self,
            fg_color=ACCENT_PRIMARY,
            height=2,
            corner_radius=0,
        )
        self.divider.grid(row=0, column=0, sticky="sew", pady=(58, 0), padx=0)

        self.chat_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=BG_MAIN,
            border_width=0,
            corner_radius=0,
        )
        self.chat_frame.grid(row=1, column=0, padx=16, pady=(12, 0), sticky="nsew")
        self.chat_frame.grid_columnconfigure(0, weight=1)

        self.footer_frame = ctk.CTkFrame(
            self,
            fg_color=BG_MAIN,
            corner_radius=0,
        )
        self.footer_frame.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 0))
        self.footer_frame.grid_columnconfigure(0, weight=1)

        self.typing_label = ctk.CTkLabel(
            self.footer_frame,
            text="",
            font=META_FONT,
            text_color=TEXT_MUTED,
        )
        self.typing_label.grid(row=0, column=0, sticky="w")

        self.input_frame = ctk.CTkFrame(
            self,
            fg_color=PANEL_MAIN,
            corner_radius=18,
        )
        self.input_frame.grid(row=3, column=0, padx=18, pady=16, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)
        self.input_frame.grid_columnconfigure(1, weight=0)
        self.input_frame.grid_columnconfigure(2, weight=0)

        self.entry = ctk.CTkEntry(
            self.input_frame,
            placeholder_text="Ask anything or type a command…",
            height=46,
            font=INPUT_FONT,
            fg_color=BG_MAIN,
            border_color=ACCENT_PRIMARY,
            border_width=2,
            text_color=TEXT_PRIMARY_ON_DARK,
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=8)
        self.entry.bind("<Return>", self.start_processing)

        self.send_btn = ctk.CTkButton(
            self.input_frame,
            text="Send",
            width=90,
            height=46,
            command=self.start_processing,
            font=BUTTON_FONT,
            fg_color=ACCENT_PRIMARY,
            hover_color=ACCENT_SECONDARY,
            text_color="white",
            corner_radius=999,
        )
        self.send_btn.grid(row=0, column=1, padx=(0, 8), pady=8)

        self.clear_btn = ctk.CTkButton(
            self.input_frame,
            text="Clear",
            width=70,
            height=46,
            command=self.clear_chat,
            font=("Segoe UI", 11, "bold"),
            fg_color=PANEL_ELEVATED,
            hover_color="#374151",
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER_SUBTLE,
            corner_radius=999,
        )
        self.clear_btn.grid(row=0, column=2, padx=(0, 12), pady=8)

        self.display_message(
            "Hi, I’m Axylo.\nThe interface is ready—what would you like to do?",
            "bot",
        )

        self._status_pulse_state = True
        self.after(600, self._pulse_status_dot)

    def _pulse_status_dot(self):
        try:
            self._status_pulse_state = not self._status_pulse_state
            self.status_dot.configure(
                text_color=ACCENT_SECONDARY if self._status_pulse_state else ACCENT_PRIMARY
            )
        except Exception:
            pass
        self.after(600, self._pulse_status_dot)

    def display_message(self, text, sender="bot"):
        """Displays a styled message bubble."""
        if not text:
            return

        timestamp = datetime.datetime.now().strftime("%H:%M")

        if sender == "user":
            bg_color = USER_BUBBLE
            text_color = TEXT_PRIMARY
            anchor_val = "e"
            meta_align = "e"
            bubble_justify = "right"
        else:
            bg_color = BOT_BUBBLE
            text_color = TEXT_PRIMARY_ON_DARK
            anchor_val = "w"
            meta_align = "w"
            bubble_justify = "left"

        msg_frame = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
        msg_frame.pack(anchor=anchor_val, pady=6, padx=4, fill="x")

        meta_frame = ctk.CTkFrame(msg_frame, fg_color="transparent")
        meta_frame.pack(anchor=meta_align, fill="x")

        name_text = "You" if sender == "user" else "Axylo"
        name_label = ctk.CTkLabel(
            meta_frame,
            text=name_text,
            font=META_FONT,
            text_color=ACCENT_SECONDARY if sender == "bot" else ACCENT_PRIMARY,
        )
        time_label = ctk.CTkLabel(
            meta_frame,
            text=timestamp,
            font=META_FONT,
            text_color=TEXT_MUTED,
        )

        if sender == "user":
            time_label.pack(side="right", padx=(4, 0))
            name_label.pack(side="right")
        else:
            name_label.pack(side="left")
            time_label.pack(side="left", padx=(4, 0))

        bubble = ctk.CTkLabel(
            msg_frame,
            text=text,
            fg_color=bg_color,
            text_color=text_color,
            wraplength=420,
            corner_radius=18,
            padx=14,
            pady=10,
            justify=bubble_justify,
            font=MSG_FONT,
        )
        bubble.pack(anchor=anchor_val, pady=(2, 0))

        if sender == "bot":
            actions_frame = ctk.CTkFrame(msg_frame, fg_color="transparent")
            actions_frame.pack(anchor=anchor_val, pady=(2, 0))

            copy_btn = ctk.CTkButton(
                actions_frame,
                text="Copy",
                width=54,
                height=22,
                font=("Segoe UI", 9),
                fg_color="transparent",
                hover_color=PANEL_ELEVATED,
                text_color=TEXT_MUTED,
                command=lambda t=text: self.copy_to_clipboard(t),
                corner_radius=999,
                border_width=0,
            )
            copy_btn.pack(side="left" if sender == "bot" else "right")

        self.update_idletasks()
        try:
            self.chat_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def copy_to_clipboard(self, text: str):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def clear_chat(self):
        for child in self.chat_frame.winfo_children():
            child.destroy()
        self.display_message("Chat cleared. Axylo is still active.", "bot")

    def set_typing(self, is_typing: bool):
        if is_typing:
            self.typing_label.configure(text="Axylo is thinking…")
        else:
            self.typing_label.configure(text="")

    def toggle_input(self, state):
        if state == "disabled":
            self.entry.configure(state="disabled")
            self.send_btn.configure(state="disabled", text="Thinking…")
            self.set_typing(True)
        else:
            self.entry.configure(state="normal")
            self.send_btn.configure(state="normal", text="Send")
            self.entry.focus()
            self.set_typing(False)

    def start_processing(self, event=None):
        user_text = self.entry.get()
        if not user_text.strip():
            return
            
        lower_text = user_text.strip().lower()

        if lower_text.startswith("send a message") or lower_text.startswith("send message"):
            self.display_message(
                "Messaging requires voice interaction.\n"
                "Please say this using the voice agent: “send a message to <name>”.",
                "bot"
            )
            self.entry.delete(0, "end")
            return   

        if lower_text in ("voice typing", "start voice typing"):
            self.display_message(
                "Voice typing is available only in voice mode.\n"
                "Try speaking the command instead.",
                "bot"
            )
            self.entry.delete(0, "end")
            return

        if lower_text.startswith("write "):
            self.display_message(
                "AI writing is handled in voice mode. Please speak the command instead.",
                "bot"
            )
            self.entry.delete(0, "end")
            return

        self.display_message(user_text, "user")
        self.entry.delete(0, "end")
        self.toggle_input("disabled")

        threading.Thread(
            target=self.run_agent_stateless,
            args=(user_text,),
            daemon=True,
        ).start()

    def run_agent_stateless(self, user_text):
        response_text = ""
        agent = None

        try:
            agent = self.agent_factory()
            runner = InMemoryRunner(agent=agent)
            runner.render_fn = lambda *args, **kwargs: None
            response_text = asyncio.run(self._get_adk_response(runner, user_text))

        except Exception as e:
            response_text = f"Error: {str(e)}"

        finally:
            if agent:
                try:
                    if hasattr(agent, "model") and hasattr(agent.model, "_client"):
                        asyncio.run(agent.model._client.close())
                    elif hasattr(agent, "model") and hasattr(agent.model, "client"):
                        if hasattr(agent.model.client, "close"):
                            asyncio.run(agent.model.client.close())
                except Exception:
                    pass

            self.after(0, lambda: self._finish_processing(response_text))

    def _finish_processing(self, text):
        self.display_message(text, "bot")
        self.toggle_input("normal")

    async def _get_adk_response(self, runner, text):
        """
        Robustly extracts the final text response from the ADK event stream.
        This handles list outputs, single objects, and nested content parts.
        """
        try:
            events = await runner.run_debug(text)

            final_text = ""

            if isinstance(events, list):
                for event in reversed(events):
                    extracted = self._extract_text_from_event(event)
                    if extracted:
                        final_text = extracted
                        break
            else:
                final_text = self._extract_text_from_event(events)

            return final_text if final_text else "I couldn't generate a response."

        except Exception as e:
            return f"Processing Error: {str(e)}"

    def _extract_text_from_event(self, event):
        """Helper to dig into an event object and find text."""
        if hasattr(event, "content") and event.content:
            parts = getattr(event.content, "parts", [])

            if parts and hasattr(parts[0], "text"):
                return parts[0].text.strip()

        if hasattr(event, "parts"):
            parts = getattr(event, "parts", [])
            if parts and hasattr(parts[0], "text"):
                return parts[0].text.strip()

        if isinstance(event, str):
            return event.strip()

        return None


if __name__ == "__main__":
    app = ChatbotWindow()
    app.mainloop()
