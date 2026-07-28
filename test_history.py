import asyncio
from conversation.context_builder import ContextBuildStage
from conversation.context_intelligence import ContextIntelligenceEngine
from conversation.state import ConversationState
from conversation.history import ConversationMessage
from memory.manager import MemoryManager
from conversation.pipeline import ConversationContext
from datetime import datetime

async def main():
    state = ConversationState(id="test_conv")
    history = [
        ConversationMessage(id="1", conversation_id="test_conv", role="user", content="Who are you?", token_count=3, created_at=datetime.utcnow()),
        ConversationMessage(id="2", conversation_id="test_conv", role="assistant", content="I am ALOY", token_count=4, created_at=datetime.utcnow()),
        ConversationMessage(id="3", conversation_id="test_conv", role="user", content="What did I just ask you?", token_count=6, created_at=datetime.utcnow())
    ]
    
    intel_engine = ContextIntelligenceEngine()
    context = ConversationContext(state=state, user_message="What did I just ask you?", history=history)
    
    stage = ContextBuildStage(intel_engine, None, None)
    context = await stage.process(context)
    
    import json
    print("MESSAGES:")
    print(json.dumps(context.messages, indent=2))

asyncio.run(main())
