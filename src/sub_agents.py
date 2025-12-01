import asyncio
import concurrent.futures

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner

from google.genai import types  
import src.logger as logger

retry_config = types.HttpRetryOptions(
    attempts=3,
    exp_base=2,
    initial_delay=1,
    http_status_codes=[429, 500, 503],
)

def create_research_agent() -> LlmAgent:
    """
    Sub-agent focused only on analyzing text (esp. web content).
    It does NOT control the computer; it just reasons and summarizes.
    """
    model = Gemini(model="gemini-2.0-flash", retry_options=retry_config)

    system_instruction = """
You are ResearchAgent.

Your only job:
- Given a user question and a chunk of text (usually from web search),
  analyze it and return a short, factual, well-structured answer.

Rules:
- Do not control the computer.
- Do not mention tools.
- Do not speak as the main assistant, just answer the question.
- Prefer bullet points and clear structure when helpful.
"""

    agent = LlmAgent(
        model=model,
        name="ResearchAgent",
        description="Specialist sub-agent for deep analysis of web content.",
        instruction=system_instruction,
        tools=[],  
    )

    try:
        if hasattr(agent, "set_default_parameters"):
            agent.set_default_parameters(
                {
                    "temperature": 0.2,
                    "max_tokens": 400,
                    "top_p": 0.8,
                }
            )
    except Exception:
        pass

    return agent

async def _run_research_agent_async(question: str, context_text: str = "") -> str:
    """
    Internal async helper that actually runs the ResearchAgent via InMemoryRunner.
    This function is executed inside its own event loop in a worker thread.
    """
    question = (question or "").strip()
    context_text = (context_text or "").strip()

    if not question:
        return "No question was provided to the research agent."

    prompt = (
        "User question:\n"
        + question
        + "\n\nContext text to analyze:\n"
        + (context_text or "(no extra context provided)")
        + "\n\nInstructions:\n"
        "- Answer the user's question using only the given context and your background knowledge.\n"
        "- Be concise but clear. If the context is empty, answer from your own knowledge.\n"
    )

    agent = create_research_agent()
    runner = InMemoryRunner(agent=agent)
    runner.render_fn = lambda *args, **kwargs: None
    runner.debug = False

    logger.tools("[A2A] Calling ResearchAgent for deep analysis (async).")

    result = await runner.run_debug(prompt)

    text = ""
    try:
        if hasattr(result, "content") and getattr(result.content, "parts", None):
            text = result.content.parts[0].text
        elif isinstance(result, str):
            text = result
        elif isinstance(result, (list, tuple)):
            for ev in result:
                try:
                    if hasattr(ev, "is_final_response") and ev.is_final_response():
                        if getattr(ev, "content", None) and getattr(ev.content, "parts", None):
                            text = ev.content.parts[0].text
                            break
                except Exception:
                    if isinstance(ev, str):
                        text = ev
    except Exception:
        text = str(result)

    text = (text or "").strip()
    if not text:
        text = "ResearchAgent did not return any text."

    return text

def run_research_agent_sync(question: str, context_text: str = "") -> str:
    """
    Synchronous facade used by the main A2A tool.

    It spins up a separate worker thread, runs an asyncio event loop there,
    and returns the final text answer. This avoids conflicts with the main
    event loop used by the primary agent.
    """

    def _worker() -> str:
        return asyncio.run(_run_research_agent_async(question, context_text))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_worker)
        return future.result()

def create_code_agent() -> LlmAgent:
    """
    Sub-agent specialized in coding tasks:
    - write code
    - refactor code
    - explain code
    - suggest improvements & tests

    It does NOT control the computer or call tools.
    """
    model = Gemini(model="gemini-2.0-flash", retry_options=retry_config)

    system_instruction = """
You are CodeAgent.

Your job:
- Help with programming tasks: writing code, refactoring, explaining,
  optimizing functions, and suggesting tests and edge cases.

Rules:
- Prefer clear, production-quality code.
- Use comments only when they add real value.
- Be explicit about assumptions.
- If the user provides existing code, preserve their style where reasonable.
- Do NOT control the computer or talk about tools; just focus on code and explanation.
"""

    agent = LlmAgent(
        model=model,
        name="CodeAgent",
        description="Specialist sub-agent for programming help and code reasoning.",
        instruction=system_instruction,
        tools=[],  
    )

    try:
        if hasattr(agent, "set_default_parameters"):
            agent.set_default_parameters(
                {
                    "temperature": 0.25,
                    "max_tokens": 600,
                    "top_p": 0.8,
                }
            )
    except Exception:
        pass

    return agent

async def _run_code_agent_async(
    task: str,
    language: str = "",
    code_context: str = "",
) -> str:
    """
    Internal async helper that runs CodeAgent via InMemoryRunner.
    Executed inside its own event loop in a worker thread.
    """
    task = (task or "").strip()
    language = (language or "").strip()
    code_context = (code_context or "").strip()

    if not task and not code_context:
        return "No coding task or code context was provided to CodeAgent."

    prompt_parts = []

    if task:
        prompt_parts.append("Task:\n" + task)

    if language:
        prompt_parts.append(f"\nPreferred language: {language}")

    if code_context:
        prompt_parts.append("\nExisting code:\n" + code_context)

    prompt_parts.append(
        "\nInstructions:\n"
        "- Provide clear, production-ready code where appropriate.\n"
        "- If modifying code, show only the updated version unless explicitly asked otherwise.\n"
        "- Explain briefly what you did and why.\n"
    )

    prompt = "\n".join(prompt_parts)

    agent = create_code_agent()
    runner = InMemoryRunner(agent=agent)
    runner.render_fn = lambda *args, **kwargs: None
    runner.debug = False

    logger.tools("[A2A] Calling CodeAgent for coding task (async).")

    result = await runner.run_debug(prompt)

    text = ""
    try:
        if hasattr(result, "content") and getattr(result.content, "parts", None):
            text = result.content.parts[0].text
        elif isinstance(result, str):
            text = result
        elif isinstance(result, (list, tuple)):
            for ev in result:
                try:
                    if hasattr(ev, "is_final_response") and ev.is_final_response():
                        if getattr(ev, "content", None) and getattr(ev.content, "parts", None):
                            text = ev.content.parts[0].text
                            break
                except Exception:
                    if isinstance(ev, str):
                        text = ev
    except Exception:
        text = str(result)

    text = (text or "").strip()
    if not text:
        text = "CodeAgent did not return any text."

    return text

def run_code_agent_sync(
    task: str,
    language: str = "",
    code_context: str = "",
) -> str:
    """
    Synchronous facade used by the main A2A tool for code help.

    Spins up a worker thread, runs an asyncio event loop there,
    and returns the final text answer.
    """

    def _worker() -> str:
        return asyncio.run(_run_code_agent_async(task, language, code_context))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_worker)
        return future.result()
