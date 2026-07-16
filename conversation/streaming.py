import json
import logging
import asyncio
from typing import AsyncGenerator, Optional
from .pipeline import ConversationContext

logger = logging.getLogger(__name__)

async def sse_stream_handler(
    context_or_task,
    engine,
    conversation_id: str,
    queue: Optional[asyncio.Queue] = None
) -> AsyncGenerator[str, None]:
    """Wraps the generator to yield SSE formatted strings and save history when done.
    Supports both traditional synchronous context flow and real-time asynchronous event queueing.
    """
    if isinstance(context_or_task, ConversationContext):
        # Traditional synchronous pipeline flow (fallback for tests)
        context = context_or_task
        search_triggered = getattr(context, "search_triggered", False)
        search_succeeded = getattr(context, "search_succeeded", False)
        search_status = "success" if (search_triggered and search_succeeded) else "local"
        if search_triggered and not search_succeeded:
            search_status = "failed"

        yield f"data: {json.dumps({'type': 'meta', 'intent': context.intent, 'model': context.model, 'search_status': search_status})}\n\n"
        
        final_text = []
        if context.response_stream:
            from identity.integrity import PromptIntegrityFilter
            integrity_filter = PromptIntegrityFilter()
            async for clean_token in integrity_filter.stream_filter(context.response_stream):
                final_text.append(clean_token)
                yield f"data: {json.dumps({'type': 'token', 'content': clean_token})}\n\n"
                
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        
        # Save assistant's response to history with full search metadata
        full_response = "".join(final_text)
        if full_response:
            try:
                metadata = {"search_status": search_status}
                # Persist source metadata for follow-up continuity and UI badge display
                if search_triggered and search_succeeded:
                    metadata["search_sources"] = getattr(context, "search_sources", [])
                    metadata["search_confidence"] = getattr(context, "search_confidence", 0.0)
                    metadata["search_timestamp"] = getattr(context, "search_timestamp", "")
                    metadata["search_result_count"] = getattr(context, "search_result_count", 0)
                await engine.save_assistant_response(conversation_id, full_response, metadata)
            except Exception as e:
                logger.error(f"Failed to save assistant response: {e}")
    else:
        # Real-time asynchronous pipeline execution flow
        task = context_or_task
        final_text = []
        
        while not task.done() or (queue is not None and not queue.empty()):
            try:
                if queue is None:
                    break
                # Fetch next event from the queue
                event = await asyncio.wait_for(queue.get(), timeout=0.05)
                yield f"data: {json.dumps(event)}\n\n"
                queue.task_done()
                
                if event.get("type") == "token":
                    final_text.append(event.get("content", ""))
            except asyncio.TimeoutError:
                continue
                
        # Check if the task failed
        if task.done() and task.exception():
            err = task.exception()
            logger.error(f"Async pipeline execution failed: {err}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(err)})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
            # Save the assistant response with full search metadata
            full_response = "".join(final_text)
            if full_response:
                try:
                    metadata = {}
                    context = task.result() if task.done() else None
                    if context:
                        search_triggered = getattr(context, "search_triggered", False)
                        search_succeeded = getattr(context, "search_succeeded", False)
                        if search_triggered:
                            status = "success" if search_succeeded else "failed"
                        else:
                            status = "local"
                        metadata["search_status"] = status
                        # Persist full source metadata for follow-up continuity
                        if search_triggered and search_succeeded:
                            metadata["search_sources"] = getattr(context, "search_sources", [])
                            metadata["search_confidence"] = getattr(context, "search_confidence", 0.0)
                            metadata["search_timestamp"] = getattr(context, "search_timestamp", "")
                            metadata["search_result_count"] = getattr(context, "search_result_count", 0)
                    await engine.save_assistant_response(conversation_id, full_response, metadata)
                except Exception as e:
                    logger.error(f"Failed to save assistant response: {e}")
