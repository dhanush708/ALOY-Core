import asyncio
import uuid
from database.connection import DatabaseConnectionPool
from memory.manager import MemoryManager
from conversation.engine import ConversationEngine
from models.router import ModelRouter
from identity.engine import IdentityEngine
import json

async def test_persona():
    db_pool = DatabaseConnectionPool(db_path="aloy.db") # Use relative or config based
    await db_pool.start()
    
    with db_pool.get_write_connection() as conn:
        conn.execute("DELETE FROM memories WHERE type = 'identity_profile'")
        conn.commit()
    
    memory_manager = MemoryManager(db_pool)
    model_router = ModelRouter() # Assumes Ollama is running locally
    identity_engine = IdentityEngine(db_pool, memory_manager)
    
    engine = ConversationEngine(
        db_pool=db_pool,
        memory_manager=memory_manager,
        model_router=model_router,
        identity_engine=identity_engine
    )
    
    conversation_id = str(uuid.uuid4())
    prompts = [
        "hi",
        "hello",
        "who created you",
        "are you solo",
        "what are your rules",
        "what makes you different from ChatGPT",
        "tell me a joke",
        "explain how your routing works",
        "remember that my favorite language is Rust",
        "what is my favorite language"
    ]
    
    print(f"Testing with Conversation ID: {conversation_id}")
    
    for i, prompt in enumerate(prompts):
        print(f"\n--- Turn {i+1} ---")
        print(f"User: {prompt}")
        try:
            # Create a queue to get meta events
            queue = asyncio.Queue()
            
            # Start process_message
            task = asyncio.create_task(engine.process_message(conversation_id, prompt, event_queue=queue))
            
            # Wait for intent event
            intent = "unknown"
            model = "unknown"
            
            # Wait for task to finish in background while reading queue
            response_text = ""
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    if event.get("type") == "meta":
                        intent = event.get("intent", "unknown")
                        model = event.get("model", "unknown")
                    elif event.get("type") == "token":
                        response_text += event.get("content", "")
                except asyncio.TimeoutError:
                    pass
            
            context = task.result()
            
            # Save assistant response just like routes do
            metadata = {
                "intent": intent,
                "model": model,
                "turn_count": context.state.turn_count
            }
            await engine.save_assistant_response(conversation_id, response_text, metadata)
            
            safe_text = response_text.encode('ascii', 'replace').decode('ascii')
            print(f"ALOY (Model: {model}, Intent: {intent}):\n{safe_text}\n")
                
        except Exception as e:
            print(f"Request failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_persona())
