import logging
import asyncio
from typing import AsyncGenerator
from .pipeline import PipelineStage, ConversationContext

logger = logging.getLogger(__name__)

class ResponseGenerationStage(PipelineStage):
    """Calls the Model Router to produce a streaming response."""

    def __init__(self, model_router=None):
        self.model_router = model_router

    async def process(self, context: ConversationContext) -> ConversationContext:
        """Sets up the streaming generator in the context or consumes it asynchronously into the queue."""
        router = self.model_router

        # Search state is now advisory only (v1.0.2) — the model always runs.
        # When search failed, the search_context in the user message already
        # tells the model what happened via the system prompt rules.
        search_triggered = getattr(context, "search_triggered", False)
        search_succeeded = getattr(context, "search_succeeded", False)

        if context.event_queue is not None:
            # Real-time asynchronous stream execution
            full_response = []
            reasoning_active = False
            in_think_block = False
            
            # Create ONE filter instance per response (not per token!)
            # The sliding-window state must persist across all tokens.
            from identity.integrity import PromptIntegrityFilter
            integrity_filter = PromptIntegrityFilter()

            try:
                # We yield the meta event if not already done
                if search_triggered and search_succeeded:
                    search_status = "success"
                elif search_triggered:
                    search_status = "failed"
                else:
                    search_status = "local"
                context.event_queue.put_nowait({
                    "type": "meta",
                    "intent": context.intent or "simple_chat",
                    "model": context.model or "qwen3:14b",
                    "search_status": search_status
                })

                # Use the chat API (messages format) when structured messages are available.
                # Fall back to raw prompt if messages list is empty (e.g., in tests).
                use_chat_api = bool(context.messages)
                if use_chat_api:
                    token_stream = router.stream_chat(
                        task=context.intent or "simple_chat",
                        messages=context.messages,
                        conversation_id=context.state.id,
                    )
                else:
                    token_stream = router.stream(
                        task=context.intent or "simple_chat",
                        prompt=context.full_prompt,
                        conversation_id=context.state.id,
                    )
                
                async for token in token_stream:
                    full_response.append(token)
                    
                    # Accumulate a check window
                    check_str = "".join(full_response[-3:])
                    
                    # 1. Check for thinking block start
                    if "<think>" in token or (not reasoning_active and "<think" in check_str):
                        if not reasoning_active:
                            reasoning_active = True
                            in_think_block = True
                            context.event_queue.put_nowait({
                                "type": "reasoning_started",
                                "stage": "Thinking"
                            })
                        continue
                        
                    # 2. Check for thinking block end
                    if "</think>" in token or (reasoning_active and "</think" in check_str):
                        if reasoning_active:
                            reasoning_active = False
                            in_think_block = False
                            context.event_queue.put_nowait({
                                "type": "reasoning_finished"
                            })
                        continue
                        
                    # 3. Stream content accordingly
                    if in_think_block:
                        context.event_queue.put_nowait({
                            "type": "reasoning_progress",
                            "stage": "Thinking",
                            "content": token
                        })
                    else:
                        # Strip any trailing or raw tags that might leak
                        clean_token = token.replace("</think>", "").replace("<think>", "")
                        if clean_token:
                            # Apply the shared integrity filter instance (stateful across tokens)
                            clean_token = integrity_filter.process_chunk(clean_token)
                            if clean_token:
                                context.event_queue.put_nowait({
                                    "type": "token",
                                    "content": clean_token
                                })
                            
            except Exception as e:
                logger.error("Response generation failed in async stream: %s", e, exc_info=True)
                context.event_queue.put_nowait({
                    "type": "token",
                    "content": " [Connection Error]"
                })
                
            # If the model finished thinking but we never sent reasoning_finished
            if reasoning_active:
                context.event_queue.put_nowait({
                    "type": "reasoning_finished"
                })
                
            # Flush any remaining safe text held back by the filter
            final_token = integrity_filter.flush()
            if final_token:
                context.event_queue.put_nowait({
                    "type": "token",
                    "content": final_token
                })
                full_response.append(final_token)
                
            context.final_response = "".join(full_response)
        else:
            # Traditional synchronous fallback (tests)
            async def stream_generator() -> AsyncGenerator[str, None]:
                full_response: list[str] = []
                try:
                    async for token in router.stream(
                        task=context.intent or "simple_chat",
                        prompt=context.full_prompt,
                        conversation_id=context.state.id,
                    ):
                        full_response.append(token)
                        yield token
                except Exception as e:
                    logger.error("Response generation failed: %s", e)
                    yield " [Connection Error]"

                context.final_response = "".join(full_response)

            context.response_stream = stream_generator()
            
        return context
