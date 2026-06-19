from typing import Literal
from openai import AsyncOpenAI
from app.config import settings

# Use the local API key if provided in settings, otherwise fallback to placeholder
local_client = AsyncOpenAI(
    base_url=settings.LOCAL_LLM_ENDPOINT,
    api_key=getattr(settings, 'LOCAL_LLM_API_KEY', 'local-placeholder')
)

cloud_client = AsyncOpenAI(
    base_url=settings.CLOUD_LLM_ENDPOINT,
    api_key=settings.CLOUD_LLM_API_KEY if settings.CLOUD_LLM_API_KEY else "cloud-placeholder"
)

async def ask_llm(prompt: str, task_type: Literal["translation", "summary", "search_answer", "generic", "language_detection"] = "generic") -> str:
    """
    Unified interface to call the LLM based on task type and configuration.
    """
    use_local = False
    
    if task_type in ["translation", "language_detection", "generic"]:
        if settings.USE_LOCAL_LLM:
            use_local = True
            
    if use_local:
        client = local_client
        model = settings.DEFAULT_MODEL_NAME_LOCAL
    else:
        client = cloud_client
        model = settings.DEFAULT_MODEL_NAME_CLOUD
        
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3 if task_type in ["translation", "language_detection"] else 0.7,
            max_tokens=1024
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling LLM (local={use_local}): {e}")
        # Fallback to cloud if local fails and we were trying local
        if use_local and settings.CLOUD_LLM_API_KEY:
            print("Falling back to cloud LLM...")
            try:
                response = await cloud_client.chat.completions.create(
                    model=settings.DEFAULT_MODEL_NAME_CLOUD,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=1024
                )
                return response.choices[0].message.content.strip()
            except Exception as e_cloud:
                print(f"Error falling back to cloud LLM: {e_cloud}")
        return "Error: Could not process request with AI."
