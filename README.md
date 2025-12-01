# 🤖 Axylo – Intelligent Voice-Controlled Desktop Agent 🧠🎙️

> Axylo is a local **AI-powered voice assistant** that automates desktop tasks, performs live web research, generates intelligent content, assists with coding, and interacts via a GUI or voice. It integrates **Google Gemini**, desktop automation, speech processing, and async agent workflows for a seamless AI experience. 🧠🎙️

---
---

## 📷 Preview

![Agent]()

---

## 📹 Video (DEMO)

👉 [Watch the demo](https://drive.google.com/drive/folders/13gpdsU9U0ay3uw6riCDlWhv9uYRhSlI0?usp=sharing)


---

## 🚀 Key Features

### 🎙 Voice Interaction
- Real-time voice control using `speech_recognition`, `edge-tts`, and `gTTS`.
- Handles **voice typing**, **messaging**, and **AI-powered smart writing**.
- Prevents microphone interference when TTS is speaking.

### 🧠 LLM-Powered Automation
- Leverages **Google Gemini 2.0 Flash** via `google-adk`.
- Integrated **tool wrappers**:
  - Open / Close apps
  - Media & volume control
  - Intelligent web search
  - Scroll & auto-scroll
  - YouTube control
  - Launch chatbot interface
- Supports powerful sub-agents:
  - `ResearchAgent` → in-depth content analysis
  - `CodeAgent` → coding, refactoring, debugging

### 🖥 Desktop Control
- Dynamic app launch and closure with fuzzy matching.
- Automated keyboard & media events using `pyautogui`.
- Supports tab control and continuous scrolling.

### 🔍 Smart Web Search
- Live web queries via `EnhancedSearchEngine` (DuckDuckGo-based).
- Summarized responses and deeper reasoning via sub-agents.

### 📝 Document Handling
- Voice typing in Notepad with spoken edit commands.
- Smart AI writing with Gemini → auto-saves to DOCX or TXT.

### 💬 GUI Chat Interface
- Built with `customtkinter`.
- Includes real-time logs, copyable AI responses, typing indicator, and quick actions.

---
---

## 📁 Project Structure

```
Agent
├─ .env
├─ main.py                    # Terminal-based voice interaction
├─ requirements.txt
├─ src
│ ├─ agent.py                 # Main Axylo agent setup & tool integration
│ ├─ app_launcher.py          # Fuzzy app launcher & closer
│ ├─ chatbot_ui.py            # GUI chat interface
│ ├─ diagnostics.py           # Internal diagnostics
│ ├─ logger.py                # Central logging & secret masking
│ ├─ search_engine.py         # Web search engine with caching
│ ├─ smart_writer.py          # AI writing handler
│ ├─ sub_agents.py            # Research and Code agents
│ ├─ tools.py                 # App control, browsing, scrolling, media, YouTube
│ ├─ user_profile.py          # Persistent user profile handling
│ ├─ voice_io.py              # Voice input/output system
│ ├─ voice_messaging.py       # Voice-based email/WhatsApp messaging
│ ├─ voice_typing.py          # Full voice typing session handler
│ └─ __init__.py
└─ Start_Agent.py             # GUI launcher
```

---
---

## 🔄 Workflow Overview

### 1️⃣ User Interaction
- Via **voice (main)** or **GUI chat window**.
- Commands like *“open chrome”, “scroll down”, “write an email”* trigger task-specific logic.

### 2️⃣ Agent Processing
- Request is passed to `agent.py → create_axylo_agent()`.
- Agent interprets intent based on structured **system prompt rules**.

### 3️⃣ Tool Execution
- Depending on request:
  - App control → `control_app_wrapper`
  - Web search → `intelligent_web_search_wrapper`
  - Deep analysis → `call_research_agent_tool`
  - Code tasks → `call_code_agent_tool`
  - Voice writing → `smart_writer`
  - Typing → `start_voice_typing`
  - Messaging → `start_voice_messaging`

### 4️⃣ Response Generation
- Results returned from tools are sanitized and optimized for voice.
- Agent creates final response (spoken or shown in GUI).

---
---

## 🧩 Built-In Agents

| Agent Name        | Purpose                                                                                                        |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| **Main Agent**    | Core orchestrator that interprets user commands, decides whether to respond directly or call tools/sub-agents. |
| **ResearchAgent** | Performs in-depth analysis of web search results or provided context. Helps with reasoning-heavy queries.      |
| **CodeAgent**     | Handles coding tasks such as writing, debugging, refactoring, and explaining code.                             |


---
---

## 🛠 Tools Available

| Component        | Tools                              |
| ---------------- | ---------------------------------- |
| LLM              | Gemini (google-adk)                |
| Voice            | speech_recognition, edge-tts, gTTS |
| GUI              | customtkinter                      |
| Automation       | pyautogui                          |
| Web Search       | EnhancedSearchEngine               |
| File Output      | python-docx, txt                   |
| Platform Control | subprocess, browser                |

---
---

## 📌 Configuration

Create a `.env` file:

```env
GEMINI_API_KEY=YOUR_API_KEY
GOOGLE_API_KEY=YOUR_API_KEY
OPENAI_API_KEY=YOUR_API_KEY
```

---
---
