import json
import os
from typing import Dict, Any, List

BASELINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")

def load_baseline() -> Dict[str, Any]:
    """Loads baseline test results from the JSON file."""
    if not os.path.exists(BASELINE_PATH):
        return {"pass_rate": 0.0, "avg_score": 0.0, "tests": {}}
    try:
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"pass_rate": 0.0, "avg_score": 0.0, "tests": {}}

def save_baseline(results: List[Dict[str, Any]], pass_rate: float, avg_score: float) -> None:
    """Saves the current validation run results as the new baseline."""
    tests_dict = {}
    for r in results:
        tests_dict[r["prompt"]] = {
            "passed": r["passed"],
            "score": r["overall_score"],
            "category": r["category"]
        }
    
    data = {
        "pass_rate": pass_rate,
        "avg_score": avg_score,
        "tests": tests_dict
    }
    
    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def compare_to_baseline(current_results: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Compares the current results to the stored baseline and identifies improvements/regressions."""
    baseline = load_baseline()
    baseline_tests = baseline.get("tests", {})
    
    regressions = []
    improvements = []
    
    for r in current_results:
        prompt = r["prompt"]
        if prompt in baseline_tests:
            base = baseline_tests[prompt]
            # Regression: was passing, now failing OR score dropped by > 10 points
            if base["passed"] and not r["passed"]:
                regressions.append({
                    "prompt": prompt,
                    "reason": "Was previously passing, but now fails.",
                    "old_score": base["score"],
                    "new_score": r["overall_score"],
                    "category": r["category"]
                })
            elif base["score"] - r["overall_score"] >= 15:
                regressions.append({
                    "prompt": prompt,
                    "reason": f"Overall quality score dropped significantly (from {base['score']} to {r['overall_score']}).",
                    "old_score": base["score"],
                    "new_score": r["overall_score"],
                    "category": r["category"]
                })
            # Improvement: was failing, now passing OR score increased by > 10 points
            elif not base["passed"] and r["passed"]:
                improvements.append({
                    "prompt": prompt,
                    "reason": "Was previously failing, but now passes.",
                    "old_score": base["score"],
                    "new_score": r["overall_score"],
                    "category": r["category"]
                })
            elif r["overall_score"] - base["score"] >= 15:
                improvements.append({
                    "prompt": prompt,
                    "reason": f"Overall quality score improved significantly (from {base['score']} to {r['overall_score']}).",
                    "old_score": base["score"],
                    "new_score": r["overall_score"],
                    "category": r["category"]
                })
                
    return {
        "regressions": regressions,
        "improvements": improvements,
        "baseline_pass_rate": baseline.get("pass_rate", 0.0),
        "baseline_avg_score": baseline.get("avg_score", 0.0)
    }
