import pytest
import asyncio
from identity.integrity import PromptIntegrityFilter

def test_static_clean_text():
    integrity = PromptIntegrityFilter()
    
    # 1. Clean XML blocks
    text = "Hello, here is the context: <identity>Some private instructions</identity> and <history>User: hi\nALOY: hello</history>."
    assert integrity.clean_text(text) == "Hello, here is the context:  and ."
    
    # 2. Clean unclosed XML tags (truncates from the first unclosed tag onwards)
    text = "Hello <identity> world <think> thinking..."
    assert integrity.clean_text(text) == "Hello "
    
    # 3. Clean headers
    text = "System: You are ALOY.\nAssistant: Hi Dhanush."
    assert integrity.clean_text(text) == "Hi Dhanush."
    
    text = "  User:  Hello!"
    assert integrity.clean_text(text) == ""

@pytest.mark.asyncio
async def test_stream_filter():
    integrity = PromptIntegrityFilter()
    
    # Simulate a stream yielding tokens
    async def token_generator():
        yield "Hello "
        yield "world, "
        yield "<id"
        yield "entity>"
        yield "hidden "
        yield "instructions"
        yield "</ide"
        yield "nt"
        yield "ity>"
        yield "this is clean."
        
    cleaned_tokens = []
    async for clean_token in integrity.stream_filter(token_generator()):
        cleaned_tokens.append(clean_token)
        
    full_cleaned_response = "".join(cleaned_tokens)
    assert "hidden" not in full_cleaned_response
    assert "instructions" not in full_cleaned_response
    assert "<identity>" not in full_cleaned_response
    assert "</identity>" not in full_cleaned_response
    assert "Hello world, this is clean." in full_cleaned_response

@pytest.mark.asyncio
async def test_stream_filter_headers():
    integrity = PromptIntegrityFilter()
    
    async def token_generator():
        yield "Assis"
        yield "tant: "
        yield "Hi "
        yield "Dhanush."
        
    cleaned_tokens = []
    async for clean_token in integrity.stream_filter(token_generator()):
        cleaned_tokens.append(clean_token)
        
    full_cleaned_response = "".join(cleaned_tokens)
    assert "Assistant:" not in full_cleaned_response
    assert "Hi Dhanush." in full_cleaned_response

def test_process_chunk_fragmented():
    integrity = PromptIntegrityFilter()
    
    tokens = [
        "Hello ", "world, ", 
        "<id", "entity>", "hidden ", "instructions", "</ide", "nt", "ity>", 
        "this is clean."
    ]
    
    cleaned_tokens = []
    for token in tokens:
        clean_token = integrity.process_chunk(token)
        if clean_token:
            cleaned_tokens.append(clean_token)
            
    final_token = integrity.flush()
    if final_token:
        cleaned_tokens.append(final_token)
        
    full_cleaned_response = "".join(cleaned_tokens)
    assert "hidden" not in full_cleaned_response
    assert "instructions" not in full_cleaned_response
    assert "<identity>" not in full_cleaned_response
    assert "</identity>" not in full_cleaned_response
    assert "Hello world, this is clean." in full_cleaned_response

