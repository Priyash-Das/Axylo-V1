# 🤖 Axylo – Intelligent Voice-Controlled Desktop Agent 
---

> Axylo is a local, fully offline-capable **AI concierge agent** that automates desktop tasks, performs live web research, generates intelligent content, assists with coding, and interacts naturally using **voice or GUI**.  
It integrates **Google Gemini**, desktop automation, custom tools, and asynchronous agents for a seamless real-time AI experience. 🧠🎙️

---

## 📷 Preview
---

![Agent](https://github.com/Priyash-Das/Photos/blob/main/Axylo-V1/Axylo-V1.png)

---

## 📹 Video (Demo)

👉 [ WATCH THE DEMO > CLICK HERE ](https://drive.google.com/drive/folders/13gpdsU9U0ay3uw6riCDlWhv9uYRhSlI0?usp=sharing)

---

## 🖼 Screenshots
---

<table>
  <tr>
    <td width="50%">
      <img src="https://github.com/Priyash-Das/Photos/blob/main/Axylo-V1/1.png" alt="User Profile" width="100%">
      <p align="center"><b>Personalized User Profile</b><br>Manage user details for tailored AI responses.</p>
    </td>
    <td width="50%">
      <img src="https://github.com/Priyash-Das/Photos/blob/main/Axylo-V1/4.png" alt="Chat Interface" width="100%">
      <p align="center"><b>Standalone Chat UI</b><br>A dedicated window for text-based interaction.</p>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="https://github.com/Priyash-Das/Photos/blob/main/Axylo-V1/3.png" alt="Diagnostics" width="100%">
      <p align="center"><b>System Diagnostics</b><br>Self-check tool to verify API keys, mic, and dependencies.</p>
    </td>
    <td width="50%">
      <img src="https://github.com/Priyash-Das/Photos/blob/main/Axylo-V1/2.png" alt="Smart Writer" width="100%">
      <p align="center"><b>Smart Writer</b><br>Quick-action modal for AI-assisted content generation.</p>
    </td>
  </tr>
</table>

---

## ⭐ Key Features
---

## 1. Voice Interaction
- Real-time speech input via `speech_recognition`
- High-quality TTS via **Edge-TTS** and **gTTS**
- **Voice typing** into Notepad or editors  
- **Voice messaging** with guided metadata collection  
- Auto-prevents microphone feedback when Axylo is speaking

---

## 2. LLM-Powered Automation (Gemini 2.0 Flash)
- Integrated via `google-adk`
- Structured tool-calling for:
  - App launch/close
  - Tab & scroll control
  - Intelligent web search
  - YouTube actions
  - Media & volume control
  - Code execution helpers
- Supports internal sub-agents:
  - **ResearchAgent** – deep content reasoning  
  - **CodeAgent** – refactoring, debugging, code generation  

---

## 3. Desktop Automation Tools
- Fuzzy-matched app launcher & closer (`AppLauncher`)
- Cursor, scroll, keyboard, and UI automation (`pyautogui`)
- Works on Windows/macOS/Linux depending on system capabilities

---

## 4. Smart Web Search
- DuckDuckGo-powered enhanced search engine
- Auto-extracts text (via `trafilatura`)
- Summaries + deeper reasoning from ResearchAgent

---

## 5. Document Handling & Smart Writing
- Voice-typing into Notepad  
- AI-generated articles, emails, ideas, and drafts  
- Doc creation via `python-docx`  
- Content auto-saved to `.docx` or `.txt`

---

## 6. Structured GUI Chat Interface
Built using **CustomTkinter** with:
- Modern dark UI  
- Realtime message bubbles  
- Copy button for AI replies  
- Typing indicator  
- Scrollable chat history  
- Quick actions  
- Agent status indicator  

GUI script: `src/chatbot_ui.py`

---

## 📁 Project Structure
---

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

## 🔄 Workflow Overview
---

### 1️. User Interaction
Input sources:
- Voice commands  
- GUI chat messages  

Examples:
- “Open Chrome”
- “Scroll down”
- “Write an email”
- “Search for AI news”

### 2️. Agent Processing
Handled inside `create_axylo_agent()`:

- Interprets user intent  
- Decides whether to respond directly or call tools  
- Routes complex tasks to ResearchAgent / CodeAgent  

### 3️. Tool Execution
- Depending on request:
  - App control → `control_app_wrapper`
  - Web search → `intelligent_web_search_wrapper`
  - Deep analysis → `call_research_agent_tool`
  - Code tasks → `call_code_agent_tool`
  - Voice writing → `smart_writer`
  - Typing → `start_voice_typing`
  - Messaging → `start_voice_messaging`

### 4️. Response Generation
- Results returned from tools are sanitized and optimized for voice.
- Agent creates final response (spoken or shown in GUI).

---

## 🧩 Built-In Agents
---

| Agent Name        | Purpose                                                                                                        |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| **Main Agent**    | Core orchestrator that interprets user commands, decides whether to respond directly or call tools/sub-agents. |
| **ResearchAgent** | Performs in-depth analysis of web search results or provided context. Helps with reasoning-heavy queries.      |
| **CodeAgent**     | Handles coding tasks such as writing, debugging, refactoring, and explaining code.                             |


---

## 🛠 Tools Available
---

| Component        | Tools                              |
| ---------------- | ---------------------------------- |
| LLM              | Gemini (google-adk)                |
| Voice            | speech_recognition, edge-tts, gTTS |
| GUI              | customtkinter                      |
| Automation       | pyautogui                          |
| Web Search       | EnhancedSearchEngine               |
| File Output      | python-docx, txt                   |
| Platform Control | subprocess, browser                |
| System           | subprocess, platform               |

---

## ⚙ Configuration
---

Create a `.env` file:

```env
GEMINI_API_KEY=YOUR_API_KEY
GOOGLE_API_KEY=YOUR_API_KEY
OPENAI_API_KEY=YOUR_API_KEY
```

---

## 📄 License
Released under **CC BY 4.0 International**.

---

## 🏷 Citation
Priyash Das. *Axylo – Desktop Agent for Intelligent Automation*. Kaggle, 2025.

---
---
