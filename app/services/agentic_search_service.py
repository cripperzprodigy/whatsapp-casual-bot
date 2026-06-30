import asyncio
import logging
import json
from typing import List, Dict, Any, Optional

from app.services.search_service import HybridSearchService
from app.ai_client import ask_llm
from app.prompts.search_prompts import GAP_ANALYZER_SYSTEM, SYNTHESIZER_SYSTEM
from app.config import settings

logger = logging.getLogger(__name__)

class AgenticSearchOrchestrator:
    def __init__(self, search_service: HybridSearchService):
        self.search_service = search_service
        self.max_iterations = settings.AGENTIC_MAX_ITERATIONS
        self.results_per_query = settings.SEARCH_RESULTS_PER_QUERY
        self.rate_limit_delay = settings.OPENROUTER_RATE_LIMIT_DELAY
        self.llm_timeout = settings.LLM_TIMEOUT_SECONDS

    async def execute_iterative_search(self, query: str, user_id: str) -> str:
        """Top-level entry point.  ALWAYS returns a str — never raises.

        This guarantee is critical: the caller (commands.py) sends whatever
        string we return via send_text_message.  If we raise instead, the
        caller's except block sends an *additional* error message, producing
        the duplicate-message bug described in the issue tracker.
        """
        try:
            return await asyncio.wait_for(
                self._execute_search_loop(query),
                timeout=self.llm_timeout + 60.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"AgenticSearchOrchestrator global timeout for query '{query}'")
            return "⚠️ I took too long to think about this query. Please try something simpler."
        except Exception as exc:
            # Catch-all: guarantee we return a string, never propagate.
            logger.error(f"AgenticSearchOrchestrator unexpected error for query '{query}': {exc}")
            return "⚠️ Something went wrong while processing your search. Please try again."

    async def _execute_search_loop(self, query: str) -> str:
        context_history = []
        seen_urls = set()
        current_query = query
        iteration = 0
        reasoning_failed = False

        while iteration < self.max_iterations:
            # 1. Perform Search
            logger.info(f"Agentic Search Iteration {iteration}: Query '{current_query}'")
            try:
                # Search Step Timeout: 3.0 seconds
                results = await asyncio.wait_for(
                    self.search_service.search(current_query, max_results=self.results_per_query),
                    timeout=15.0
                )

                # Format results and append
                formatted_results = self._format_search_results(results, seen_urls)
                if formatted_results:
                     context_history.append(f"--- Search Results for '{current_query}' ---\n{formatted_results}")
            except asyncio.TimeoutError:
                 logger.warning(f"Search step timed out for query '{current_query}'")
            except Exception as e:
                 logger.error(f"Search step failed: {e}")

            if not context_history:
                 return f"🔍 No initial results found for '{query}'."

            # If it's the final iteration, skip gap analysis
            if iteration == self.max_iterations - 1:
                break

            # 2. Gap Analysis
            try:
                # LLM Gap Analysis Timeout: 5.0 seconds
                analysis = await asyncio.wait_for(
                    self._analyze_gaps(query, context_history),
                    timeout=self.llm_timeout
                )

                if analysis.get('sufficient', True):
                    logger.info("Gap analysis determined context is sufficient.")
                    break

                refined_query = analysis.get('refined_query')
                if not refined_query:
                    logger.warning("Gap analysis returned insufficient, but no refined_query.")
                    break

                if refined_query.lower().strip() == current_query.lower().strip():
                    logger.info("Gap analysis returned identical query. Breaking loop to prevent duplicates.")
                    break

                current_query = refined_query

            except asyncio.TimeoutError:
                logger.warning("Gap analysis timed out. Falling back to synthesis.")
                reasoning_failed = True
                break
            except Exception as e:
                logger.error(f"Gap analysis failed: {e}. Falling back to synthesis.")
                reasoning_failed = True
                break

            if iteration < self.max_iterations - 1:
                await asyncio.sleep(self.rate_limit_delay)

            iteration += 1

        # 3. Final Synthesis
        try:
            # LLM Synthesis Timeout: 6.0 seconds
            return await asyncio.wait_for(
                self._synthesize_final_answer(query, context_history, reasoning_failed),
                timeout=self.llm_timeout
            )
        except asyncio.TimeoutError:
             logger.warning("Synthesis timed out.")
             fallback = "⚠️ I gathered information but took too long to write the final answer.\n\n" + self._get_raw_results(context_history)
             logger.info("Fallback constructed (synthesis timeout). Returning single response.")
             return fallback
        except Exception as e:
             logger.error(f"Synthesis failed: {e}")
             fallback = "⚠️ I encountered some retrieved information but couldn't synthesize a full report. Here are the raw findings:\n\n" + self._get_raw_results(context_history)
             logger.info("Fallback constructed (synthesis error). Returning single response.")
             return fallback

    async def _analyze_gaps(self, original_query: str, context: List[str]) -> Dict[str, Any]:
        context_str = "\n\n".join(context)
        prompt = (
            f"Original Query: '{original_query}'\n\n"
            f"Accumulated Context:\n{context_str}\n\n"
            "Analyze these results. Are they sufficient to answer the original query comprehensively? "
            "If not, what specific information is missing? "
            "Output JSON: {'sufficient': bool, 'missing_info': str, 'refined_query': str}"
        )

        response_text = await ask_llm(
            prompt=prompt,
            task_type="json",
            system_override=GAP_ANALYZER_SYSTEM
        )

        # Simple extraction to handle JSON inside markdown code blocks
        if "```json" in response_text:
             response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
             response_text = response_text.split("```")[1].split("```")[0].strip()

        # Find first '{' and last '}'
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
             response_text = response_text[start_idx:end_idx+1]

        try:
             return json.loads(response_text)
        except json.JSONDecodeError as e:
             logger.error(f"Failed to parse gap analysis JSON: {response_text}, error: {e}")
             return {'sufficient': True} # Default to true to stop loop on parse error

    async def _synthesize_final_answer(self, query: str, context: List[str], reasoning_failed: bool) -> str:
        context_str = "\n\n".join(context)

        system_instruction = SYNTHESIZER_SYSTEM
        if reasoning_failed:
             system_instruction += "\n\nNote: Advanced reasoning step failed due to technical constraints. Synthesize the best possible answer using only the provided context chunks."

        prompt = (
            f"Original Query: '{query}'\n\n"
            f"Using the following accumulated context from multiple search rounds, write a comprehensive, detailed answer. "
            f"Cite sources implicitly. Tone: Helpful and authoritative. Ensure the output is formatted beautifully in Markdown.\n\n"
            f"Context chunks:\n{context_str}"
        )

        return await ask_llm(
            prompt=prompt,
            task_type="search_answer",
            system_override=system_instruction
        )

    def _format_search_results(self, results: List[Any], seen_urls: set) -> str:
        if not results:
            return ""

        formatted = []
        for i, res in enumerate(results, 1):
             title = getattr(res, 'title', 'No Title')
             snippet = getattr(res, 'snippet', 'No Snippet')
             url = getattr(res, 'url', '')
             if url and url in seen_urls:
                 continue
             if url:
                 seen_urls.add(url)
             formatted.append(f"{i}. {title}\nSnippet: {snippet}\nURL: {url}")

        return "\n\n".join(formatted)

    def _get_raw_results(self, context_history: List[str]) -> str:
         # Limit raw output size to prevent message failure
         raw_text = "\n\n".join(context_history)
         if len(raw_text) > 3000:
              return raw_text[:3000] + "...\n[Results Truncated]"
         return raw_text
