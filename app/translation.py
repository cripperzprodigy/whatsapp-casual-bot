from app.ai_client import ask_llm

async def detect_language(text: str) -> str:
    """
    Detects the language of the given text using the LLM.
    Returns the two-letter language code (e.g., 'en', 'id', 'es').
    """
    prompt = f"Detect the primary language of the following text. Respond ONLY with the ISO 639-1 two-letter lowercase language code (e.g., 'en', 'es', 'id'). If you are unsure, respond with 'unknown'.\n\nText: {text}"
    result = await ask_llm(prompt, task_type="language_detection")
    code = result.lower().strip()
    # Simple validation just in case the LLM is chatty
    if len(code) == 2 or code == "unknown":
        return code
    return "unknown"

async def translate_text(text: str, target_language: str) -> str:
    """
    Translates text to the target language using the LLM.
    """
    prompt = f"""Translate the following text to the language represented by the ISO 639-1 code '{target_language}'.
Rules:
1. Preserve the exact original tone and formatting (formal/casual, emojis, line breaks).
2. DO NOT add any conversational filler, introductions, or explanations like 'Here is the translation' or 'Sure, here it is'.
3. Output ONLY the translated text and nothing else.
4. If it is a short message, you may optionally prefix it with the original language name in brackets, like '[Spanish] Translated text here'.

Text to translate:
{text}
"""
    result = await ask_llm(prompt, task_type="translation")
    return result
