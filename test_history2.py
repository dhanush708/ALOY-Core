import asyncio
from conversation.context_builder import ContextBuildStage
from conversation.context_intelligence import ContextIntelligenceEngine
from conversation.state import ConversationState
from conversation.history import ConversationMessage
from conversation.pipeline import ConversationContext
from memory.types import ScoredMemory, Memory
from datetime import datetime

async def main():
    state = ConversationState(id="test_conv")
    history = [
        ConversationMessage(id="1", conversation_id="test_conv", role="user", content="My favorite color is blue.", token_count=3, created_at=datetime.utcnow()),
        ConversationMessage(id="2", conversation_id="test_conv", role="assistant", content="I will remember that.", token_count=4, created_at=datetime.utcnow()),
        ConversationMessage(id="3", conversation_id="test_conv", role="user", content="What is my favorite color?", token_count=6, created_at=datetime.utcnow())
    ]
    
    memories = [
        ScoredMemory(
            memory=Memory(id="m1", type="preference", content="User's favorite color is blue", created_at=datetime.utcnow(), updated_at=datetime.utcnow()),
            score=0.9
        )
    ]
    
    intel_engine = ContextIntelligenceEngine()
    context = ConversationContext(state=state, user_message="What is my favorite color?", history=history, memories=memories)
    
    stage = ContextBuildStage(intel_engine, None, None)
    context = await stage.process(context)
    
    import json
    print("MESSAGES:")
    print(json.dumps(context.messages, indent=2))

asyncio.run(main())
