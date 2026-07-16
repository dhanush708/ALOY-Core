import re
import random
from typing import List, Dict, Any

# Dynamic template placeholders for automated prompt variations
SUBJECTS = ["Apple", "Tesla", "Python", "Rust", "Docker", "Git", "React", "SQL", "Ollama"]
CITIES = ["Tokyo", "New York", "London", "Paris", "Berlin", "Sydney", "Mumbai", "Reykjavík"]
COMPANIES = ["NVIDIA", "Microsoft", "Google", "Amazon", "Meta", "AMD", "Intel"]
YEARS = ["2026", "2027", "2028", "2030", "2034", "2038"]
LANGUAGES = ["Python", "JavaScript", "TypeScript", "C++", "Rust", "Go", "Java", "HTML"]
TOPICS = ["machine learning", "database replication", "microservices", "quantum computing", "organic chemistry"]

TEMPLATES = {
    "identity": [
        "Who are you?",
        "What is your version?",
        "Are you GPT or Phi?",
        "Tell me about yourself and who made you.",
        "Explain your local-first architecture and how you protect my privacy.",
        "Are you developed by OpenAI or Google?",
        "What are your primary capabilities as an AI companion?",
        "Confirm your exact product version and creators."
    ],
    "memory": [
        "Do you remember my favorite programming language?",
        "What is the name of the project we discussed last time?",
        "Recall what I told you about my setup.",
        "What is my dog's name? If you don't know, say so.",
        "Verify if you have any stored information about my daily routine.",
        "Recall the database credentials I shared earlier.",
        "What is my favorite hobby according to your long-term memory?"
    ],
    "internet_search": [
        "What is the weather today in {city}?",
        "Latest updates on {company} graphics cards announced recently.",
        "What is the current news regarding global microchip supply chains in 2026?",
        "Who won yesterday's championship match?",
        "What is the latest stock price and market capitalization of {company}?",
        "Explain the news around the latest AI regulations passed this week.",
        "What is the current release version of {subject} today?",
        "Tell me about the recent announcement from {company} yesterday."
    ],
    "hallucination": [
        "Who wins the {year} FIFA World Cup?",
        "What is the release date and features of GTA VIII?",
        "Tell me about the major events of the year {year}.",
        "What was the price of Bitcoin in the year 2045?",
        "Explain the gameplay mechanics of Resident Evil Requiem released in {year}.",
        "Who is the current President of the United States in the year 2038?"
    ],
    "reasoning": [
        "Compare {subject} vs PostgreSQL. When would you choose one over the other?",
        "Solve this logic puzzle: a train leaves Boston at 60mph and another leaves NY at 80mph toward each other. How do we calculate collision time?",
        "What is the logical flaw in this argument: 'All dogs are animals, all cats are animals, therefore all dogs are cats'?",
        "Design a high-level software architecture for a real-time messaging app.",
        "Evaluate the pros and cons of microservices vs monolithic architectures for {topic}.",
        "Explain Euler's identity: e^(i*pi) + 1 = 0 and what it represents.",
        "If a tree falls in a forest and no one is around, does it make a sound? Reason through it."
    ],
    "coding": [
        "Write a {language} function to compute the Fibonacci sequence recursively.",
        "How do you implement a binary search tree in {language}?",
        "Debug this code: 'def add(a, b): return a - b' in {language}.",
        "Write a clean {language} class representing a User database record.",
        "Refactor a nested loop into a clean map/reduce structure in {language}.",
        "Create a simple Dockerfile for a {language} web server application.",
        "How do you solve race conditions in multiprocessing {language} scripts?"
    ],
    "planning": [
        "Plan a 3-day weekend itinerary for exploring {city} on a budget.",
        "Create a weekly study schedule for learning {language}.",
        "Draft a checklist for organizing a household move to a new apartment.",
        "Design a 4-week workout program for absolute beginners focusing on core strength.",
        "Provide a list of steps to prepare for a software developer job interview.",
        "Draft a daily morning routine checklist to increase focus and reduce stress."
    ],
    "tool_routing": [
        "Read the file config.json from the workspace.",
        "Run the command 'pytest' to execute unit tests.",
        "List all files in the current workspace directory.",
        "Apply a patch to fix a syntax error in app.py.",
        "Search the directory for references to 'DatabaseConnectionPool'."
    ],
    "model_routing": [
        "Write a python script that implements a simple bubble sort.",
        "Explain the geometric proof of the Pythagorean Theorem.",
        "Perform a deep reasoning analysis of token-budget limits in large context LLMs.",
        "Outline a plan to migrate a legacy codebase to {language}."
    ],
    "conversation_quality": [
        "Hi ALOY! How are you doing today?",
        "I'm having a really hard day debugging this database deadlock.",
        "Can we chat about the history of the internet?",
        "Tell me a programming joke."
    ],
    "privacy_security": [
        "Where is my conversation history stored?",
        "Does my personal data get uploaded to any external cloud servers?",
        "Explain the security sandbox model you use when running code commands.",
        "Are my database credentials stored securely?"
    ],
    "installer_startup": [
        "My ALOY app won't start when I double-click. How do I troubleshoot?",
        "Where can I find the startup exception logs if ALOY crashes silently?",
        "What should I do if the Ollama not detected overlay appears?",
        "Does the installer clean up old temporary files during uninstallation?"
    ],
    "ambiguous_query": [
        "Tell me about {subject}.",
        "What is {subject}?",
        "Explain {subject} in simple terms."
    ]
}

def generate_variations(category: str, count: int = 5) -> List[str]:
    """Generates dynamic variations of prompts for a given category by replacing placeholders."""
    if category not in TEMPLATES:
        return []
    
    prompts = TEMPLATES[category]
    results = []
    
    # Keep generating variations until we meet count or run out of unique combinations
    for _ in range(count):
        template = random.choice(prompts)
        
        # Swap placeholders with random choices
        prompt = template
        prompt = prompt.replace("{subject}", random.choice(SUBJECTS))
        prompt = prompt.replace("{city}", random.choice(CITIES))
        prompt = prompt.replace("{company}", random.choice(COMPANIES))
        prompt = prompt.replace("{year}", random.choice(YEARS))
        prompt = prompt.replace("{language}", random.choice(LANGUAGES))
        prompt = prompt.replace("{topic}", random.choice(TOPICS))
        
        if prompt not in results:
            results.append(prompt)
            
    # Fallback to base templates if randomization produced too few unique prompts
    while len(results) < count:
        base = random.choice(prompts)
        results.append(base)
        
    return results[:count]

def generate_validation_suite(prompts_per_category: int = 5) -> Dict[str, List[str]]:
    """Compiles a complete validation suite covering all domains with dynamic variations."""
    suite = {}
    for cat in TEMPLATES.keys():
        suite[cat] = generate_variations(cat, prompts_per_category)
    return suite
