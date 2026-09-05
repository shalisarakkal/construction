"""Optional LLM answer synthesis (dream.md section 5), behind a provider
switch (RAG_LLM_PROVIDER=anthropic|ollama). /query and /documents/{id}/summary
only call is_configured()/synthesize_answer()/synthesize_summary() below --
they don't know which provider is active, same isolation as embeddings.py.
Without a reachable provider, /query still returns raw retrieved chunks with
no synthesized answer, so the retrieval path is testable without any LLM
dependency at all.

Citations are NOT trusted from the model's own output -- they're derived
programmatically from which chunks were actually retrieved (see
docs/AllDevFlow.md "Confidence & citations" section for why: LLM
self-reported citations/confidence are unreliable, flagged during initial
planning).
"""

import json
import urllib.request
from urllib.error import URLError

from .config import settings

SYSTEM_PROMPT = (
    "You are an engineering assistant. Use ONLY the provided context to answer. "
    "Before concluding there isn't enough information, check each numbered context "
    "excerpt individually against the question -- don't stop after skimming the "
    "first one or two. "
    "The context sometimes describes amendments to an adopted model code (e.g. "
    "\"Section R309.2 ... shall be deleted\" or \"shall not apply\"). Treat a section "
    "described as deleted, removed, or not adopted as meaning the requirement it "
    "described does NOT apply -- draw that conclusion directly rather than treating "
    "amendment language as insufficient information just because it doesn't state the "
    "answer in plain prose. "
    "Only after checking every excerpt this way, if none are relevant, say "
    "\"Not enough information.\" Do not use outside knowledge."
)

SUMMARY_SYSTEM_PROMPT = (
    "You are an engineering assistant. Summarize the provided document excerpt for "
    "someone who needs to quickly understand what it covers. Use ONLY the provided "
    "context. Note the main topics, key requirements, and any fee/table data present. "
    "Do not use outside knowledge."
)


def is_configured() -> bool:
    if settings.llm_provider == "ollama":
        return _ollama_reachable()
    return bool(settings.anthropic_api_key)


def synthesize_answer(question: str, context_block: str) -> str:
    user_content = f"Context:\n{context_block}\n\nQuestion: {question}"
    if settings.llm_provider == "ollama":
        return _ollama_chat(SYSTEM_PROMPT, user_content)
    return _anthropic_chat(SYSTEM_PROMPT, user_content)


def synthesize_summary(title: str, context_block: str) -> str:
    user_content = f"Document: {title}\n\nContext:\n{context_block}"
    if settings.llm_provider == "ollama":
        return _ollama_chat(SUMMARY_SYSTEM_PROMPT, user_content)
    return _anthropic_chat(SUMMARY_SYSTEM_PROMPT, user_content)


def _anthropic_chat(system: str, user_content: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _ollama_reachable() -> bool:
    """Runtime check, not a static config check -- same reasoning as
    ocr.is_available(): a configured provider isn't the same as an actually
    running one, and Ollama is a local server process that may not be up."""
    try:
        urllib.request.urlopen(f"{settings.ollama_base_url}/api/tags", timeout=1.5)
        return True
    except URLError:
        return False


def _ollama_chat(system: str, user_content: str) -> str:
    options = {"num_predict": 1024}  # matches the Anthropic path's max_tokens=1024
    if settings.ollama_num_gpu is not None:
        options["num_gpu"] = settings.ollama_num_gpu
    body = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "options": options,
    }
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{settings.ollama_base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read())
    return body["message"]["content"]
