import sys
import os
import time
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.chdir(project_root)

from database.connection import DatabaseConnectionPool
from memory.manager import MemoryManager
from conversation.engine import ConversationEngine
from models.router import ModelRouter

from validation.prompts import generate_validation_suite
from validation.evaluator import evaluate_response
from validation.db import load_baseline, save_baseline, compare_to_baseline

async def main():
    print("=" * 70)
    print("ALOY AUTOMATED VALIDATION & REGRESSION FRAMEWORK")
    print("=" * 70)
    
    # Parse CLI args
    live_mode = "--live" in sys.argv
    save_base = "--save-baseline" in sys.argv
    
    prompts_per_cat = 5
    for arg in sys.argv:
        if arg.startswith("--prompts-per-category="):
            try:
                prompts_per_cat = int(arg.split("=")[1])
            except ValueError:
                pass
                
    mode_str = "LIVE (Ollama inference)" if live_mode else "FAST (Mocked inference, full pipeline check)"
    print(f"Execution Mode: {mode_str}")
    print(f"Prompts density: {prompts_per_cat} prompts per domain category.")
    
    # Initialize ALOY Server subsystems
    db_path = "data/aloy.db"
    pool = DatabaseConnectionPool(db_path)
    await pool.start()
    
    mem_mgr = MemoryManager(pool)
    await mem_mgr.start()
    
    # Mock embeddings to prevent Ollama load timeouts or external requests
    mem_mgr.embeddings.generate = AsyncMock(return_value=[0.1]*768)
    
    model_router = ModelRouter()
    engine = ConversationEngine(pool, mem_mgr, model_router=model_router)
    
    # Generate the suite of prompts
    suite = generate_validation_suite(prompts_per_cat)
    total_prompts = sum(len(p) for p in suite.values())
    print(f"Generated {total_prompts} dynamic test prompts across {len(suite)} domains.")
    
    # Mock web search so tests don't hit external servers or rate limits
    mock_search_results = (
        "Title: Mocked Search Result 1\n"
        "URL: https://www.ign.com/articles/mocked-game-news-2026\n"
        "Snippet: Verified live updates regarding 2026 releases and scores.\n"
        "---\n"
        "Title: Mocked Search Result 2\n"
        "URL: https://github.com/mocked/repo-updates\n"
        "Snippet: Technical release notes and changes for Microchips and Python.\n"
        "---"
    )
    
    results = []
    
    # Mock class for app context
    class MockApp:
        class MockState:
            knowledge_router = None
        state = MockState()
    engine.app = MockApp()
    
    with patch("tools.impl.web_search.WebSearchTool.execute", new=AsyncMock(return_value=mock_search_results)):
        for category, prompts in suite.items():
            print(f"\nEvaluating Domain: {category.replace('_', ' ').upper()} ({len(prompts)} cases)")
            
            for idx, prompt in enumerate(prompts):
                t0 = time.perf_counter()
                
                # Mock or Execute response
                try:
                    if live_mode:
                        # Full live pipeline run
                        context = await engine.process_message(f"val_{category}_{idx}", prompt)
                        response_text = context.final_response
                    else:
                        # Full pipeline execution with mocked LLM generation
                        from conversation.intent import IntentDetectionStage
                        from conversation.context_builder import ContextBuildStage
                        from conversation.state import ConversationState
                        from conversation.pipeline import ConversationContext
                        
                        state = ConversationState(id=f"val_{category}_{idx}")
                        context = ConversationContext(state=state, user_message=prompt)
                        
                        # Run Intent Classification
                        intent_stage = IntentDetectionStage(model_router=model_router)
                        context = await intent_stage.process(context)
                        
                        # Run Memory Retrieval
                        context.memories = await mem_mgr.retrieve(prompt, limit=10)
                        
                        # Run Context Builder (Search execution, system prompt formatting)
                        ctx_build = ContextBuildStage(engine.intelligence_engine, conversation_engine=engine)
                        context = await ctx_build.process(context)
                        
                        # Determine Mock Output based on prompt features & intent
                        if category == "identity":
                            response_text = "I am ALOY Version 1.0, developed by Dhanush A. I run completely locally."
                        elif category == "ambiguous_query":
                            response_text = "Are you asking about Tesla, the company, or Nikola Tesla, the inventor?"
                        elif category == "hallucination":
                            response_text = "Nobody knows yet. I don't guess future events."
                        elif "[LIVE INTERNET SEARCH RESULTS" in context.full_prompt:
                            response_text = (
                                "Based on live search results, NVIDIA released updates for graphics cards.\n"
                                "### Sources\n1. [IGN](https://www.ign.com/articles/mocked-game-news-2026)\n\n"
                                "#### Search Metadata\n- Timestamp: 2026-07"
                            )
                        elif "[LIVE SEARCH FAILED]" in context.full_prompt:
                            response_text = "I am sorry, but I was unable to retrieve live information from the web."
                        else:
                            response_text = "Yeah, I can help with that. Here is the standard local context answer."
                            
                        # Set context response params
                        context.final_response = response_text
                        
                    t_total = (time.perf_counter() - t0) * 1000
                    
                    # Score the response
                    eval_res = evaluate_response(category, prompt, response_text, context, t_total)
                    eval_res["prompt"] = prompt
                    eval_res["category"] = category
                    eval_res["response_text"] = response_text
                    
                    results.append(eval_res)
                    
                    status_str = "PASS" if eval_res["passed"] else f"FAIL ({eval_res['severity']})"
                    print(f"  [{idx+1}/{len(prompts)}] Score: {eval_res['overall_score']}/100 | {status_str} ({t_total:.1f}ms)")
                    if not eval_res["passed"]:
                        print(f"    |- Issues: {', '.join(eval_res['failures'])}")
                        
                except Exception as e:
                    print(f"  [{idx+1}/{len(prompts)}] ERROR processing: {e}")
                    results.append({
                        "prompt": prompt,
                        "category": category,
                        "passed": False,
                        "overall_score": 0,
                        "scores": {},
                        "failures": [f"Execution crashed: {str(e)}"],
                        "severity": "High",
                        "intent": "unknown",
                        "model": "unknown",
                        "latency_ms": 0.0
                    })
                    
    # Shutdown subsystems
    await pool.stop()
    
    # Calculate global metrics
    passed_tests = [r for r in results if r["passed"]]
    failed_tests = [r for r in results if not r["passed"]]
    pass_rate = (len(passed_tests) / len(results)) * 100 if results else 0.0
    avg_score = sum(r["overall_score"] for r in results) / len(results) if results else 0.0
    
    # Regression comparison
    comparison = compare_to_baseline(results)
    
    # Save current run as new baseline if requested
    if save_base:
        save_baseline(results, pass_rate, avg_score)
        print("\nSuccessfully updated stored baseline results.")
        
    # Generate detailed reports
    reports_dir = "reports"
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, "validation_report.md")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# ALOY Automated Validation & Regression Report\n")
        f.write(f"Generated on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.write(f"Mode: {mode_str}\n\n")
        
        f.write("## 1. Summary Metrics\n\n")
        f.write(f"- **Pass Rate**: {pass_rate:.1f}% ({len(passed_tests)} passed, {len(failed_tests)} failed)\n")
        f.write(f"- **Average Quality Score**: {avg_score:.1f}/100\n")
        f.write(f"- **Baseline Pass Rate**: {comparison['baseline_pass_rate']:.1f}%\n")
        f.write(f"- **Baseline Avg Score**: {comparison['baseline_avg_score']:.1f}%\n\n")
        
        f.write("## 2. Regression & Improvements Analysis\n\n")
        
        # Highlight Regressions
        f.write("### ⚠️ Regressions (Score drops or new failures)\n\n")
        if comparison["regressions"]:
            f.write("| Category | Prompt | Reason | Old Score | New Score |\n")
            f.write("|---|---|---|---|---|\n")
            for reg in comparison["regressions"]:
                f.write(f"| {reg['category']} | \"{reg['prompt']}\" | {reg['reason']} | {reg['old_score']} | {reg['new_score']} |\n")
        else:
            f.write("*No regressions detected.* 👍\n")
            
        # Highlight Improvements
        f.write("\n### 🚀 Improvements (Score gains or fixed failures)\n\n")
        if comparison["improvements"]:
            f.write("| Category | Prompt | Reason | Old Score | New Score |\n")
            f.write("|---|---|---|---|---|\n")
            for imp in comparison["improvements"]:
                f.write(f"| {imp['category']} | \"{imp['prompt']}\" | {imp['reason']} | {imp['old_score']} | {imp['new_score']} |\n")
        else:
            f.write("*No new improvements recorded.* \n")
            
        f.write("\n## 3. Failure Log & Troubleshooting Details\n\n")
        if failed_tests:
            f.write("| Severity | Category | Prompt | Issues Identified | Suggested Fix |\n")
            f.write("|---|---|---|---|---|\n")
            for test in failed_tests:
                fails_str = ", ".join(test["failures"])
                # Compile suggestion based on issues
                fix = "Check models config or intent routes."
                if "robotic" in fails_str.lower():
                    fix = "Refine prompt system guidelines in context_builder.py to restrict robotic fillers."
                elif "competitor" in fails_str.lower():
                    fix = "Update seed memory identity block or identity engine profile constraints."
                elif "search" in fails_str.lower():
                    fix = "Verify DDG connector or intent patterns for web search triggers."
                elif "Fabricated" in fails_str.lower():
                    fix = "Verify search status checks in ResponseGenerationStage."
                f.write(f"| {test['severity']} | {test['category']} | \"{test['prompt']}\" | {fails_str} | {fix} |\n")
        else:
            f.write("*All test prompt checks passed successfully!* 🎉\n")
            
        f.write("\n## 4. Complete Test Results Table\n\n")
        f.write("| Index | Category | Prompt | Intent | Model | Score | Status |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for idx, r in enumerate(results, 1):
            status = "✅ PASS" if r["passed"] else "❌ FAIL"
            f.write(f"| {idx} | {r['category']} | \"{r['prompt']}\" | {r['intent']} | {r['model']} | {r['overall_score']} | {status} |\n")

    print("\n" + "=" * 70)
    print("VALIDATION EXECUTION COMPLETED")
    print(f"Report saved to: {report_path}")
    print(f"Pass Rate: {pass_rate:.1f}% ({len(passed_tests)}/{len(results)} passed)")
    print(f"Average Quality Score: {avg_score:.1f}/100")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
