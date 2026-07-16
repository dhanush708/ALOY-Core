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

        # Check for search failure and validate confidence
        search_triggered = getattr(context, "search_triggered", False)
        search_succeeded = getattr(context, "search_succeeded", False)

        if search_triggered and not search_succeeded:
            fail_msg = "I couldn't verify this information from reliable sources."
            context.final_response = fail_msg
            if context.event_queue is not None:
                context.event_queue.put_nowait({
                    "type": "meta",
                    "intent": context.intent or "simple_chat",
                    "model": context.model or "local",
                    "search_status": "failed"
                })
                # Stream it token by token for smooth UI experience
                words = fail_msg.split(" ")
                for i, word in enumerate(words):
                    space = " " if i > 0 else ""
                    context.event_queue.put_nowait({
                        "type": "token",
                        "content": space + word
                    })
                    await asyncio.sleep(0.01)
            else:
                async def failed_stream() -> AsyncGenerator[str, None]:
                    yield fail_msg
                context.response_stream = failed_stream()
            return context

        if context.event_queue is not None:
            # Real-time asynchronous stream execution
            full_response = []
            reasoning_active = False
            in_think_block = False
            
            try:
                # We yield the meta event if not already done
                # (although it is done in Intent Detection, we make sure it exists)
                search_status = "success" if (search_triggered and search_succeeded) else "local"
                context.event_queue.put_nowait({
                    "type": "meta",
                    "intent": context.intent or "simple_chat",
                    "model": context.model or "qwen3:14b",
                    "search_status": search_status
                })
                
                async for token in router.stream(
                    task=context.intent or "simple_chat",
                    prompt=context.full_prompt,
                    conversation_id=context.state.id,
                ):
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
                            from identity.integrity import PromptIntegrityFilter
                            # Apply the prompt integrity filter on the clean token
                            filter_obj = PromptIntegrityFilter()
                            clean_token = filter_obj.clean_text(clean_token)
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
