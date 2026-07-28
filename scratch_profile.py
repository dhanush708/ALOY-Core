import asyncio
import time
import uuid
import sys
from kernel.boot import boot_kernel
from conversation.engine import ConversationContext

async def profile_request():
    kernel = await boot_kernel()
    engine = kernel.conversation_engine
    
    # 1. HTTP Request received
    t_start = time.perf_counter()
    
    conv_id = str(uuid.uuid4())
    message = "My name is Max"
    
    t0 = time.perf_counter()
    state = await engine.get_or_create_state(conv_id)
    state.add_turn()
    await engine.history_store.add_message(conv_id, "user", message)
    t_conv_load = time.perf_counter() - t0
    
    context = ConversationContext(state=state, user_message=message)
    
    timings = {}
    
    for stage in engine.pipeline:
        stage_name = stage.__class__.__name__
        t_stage_start = time.perf_counter()
        context = await stage.process(context)
        timings[stage_name] = time.perf_counter() - t_stage_start
        
    t_total = time.perf_counter() - t_start
    
    print(f"Total time: {t_total:.4f}s")
    print(f"Conv load/save: {t_conv_load:.4f}s")
    for k, v in timings.items():
        print(f"Stage {k}: {v:.4f}s")
        
    print(f"Intent detected: {context.intent}")
    print(f"Model selected: {context.model}")
    print(f"Facts in context: {len(context.active_memories) if hasattr(context, 'active_memories') else 'unknown'}")

    
if __name__ == '__main__':
    asyncio.run(profile_request())
