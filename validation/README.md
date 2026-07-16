# ALOY Automated Validation & Regression Framework
This framework provides an end-to-end automated testing, quality scoring, and regression tracking utility for the ALOY platform. It executes test suites across 13 core domain categories, evaluates model routing correctness, flags quality issues, and highlights quality deviations from baseline results.

---

## 1. Quick Start

### Running the Suite (Fast Mode)
By default, the validation suite runs in **Fast Regression Mode**. This mode executes the full ALOY conversational processing pipeline (including intent classification, memory retrieval, and search routing context extraction) while using lightweight simulated generation inputs. This allows developers to check pipeline integrity and routing tables in seconds without invoking full LLM inference overhead:

```bash
python validation/run.py
```

### Running the Suite (Live Mode)
To validate the actual LLM generation responses, active reasoning steps, and conversational formatting quality, run the suite against your locally running Ollama instance:

```bash
python validation/run.py --live
```

### Saving Baseline & Customizing Density
- **To update the baseline results** (to lock in recent bug fixes or improvements as the new target standard), run:
  ```bash
  python validation/run.py --save-baseline
  ```
- **To configure density** (e.g. to run 10 dynamic prompt variations per category instead of the default 5), run:
  ```bash
  python validation/run.py --prompts-per-category=10
  ```

---

## 2. Interpreting the Reports

Each validation run generates a comprehensive markdown report under `reports/validation_report.md`.

### Summary Metrics
The top of the report provides global health indicators of the codebase:
- **Pass Rate**: The percentage of test cases that fully met quality, search, identity, and routing assertions.
- **Average Quality Score**: Weighted scoring (0-100) combining identity preservation, hallucination resistance, memory safety, naturalness, reasoning structures, and routing accuracy.
- **Baseline Comparison**: Pass rate and average score delta comparisons against the baseline standard.

### Regression & Improvements Analysis
The report automatically performs differential analysis against `validation/baseline.json`:
- **Regressions (⚠️)**: Highlights any prompts that previously passed or had higher scores but now fail or have suffered a drop in quality. Developers must review these to ensure changes did not introduce side-effects.
- **Improvements (🚀)**: Lists prompts that have transitioned from failing to passing or achieved significant quality gains.

### Failure Log & Suggestions
For every failing prompt, the report details:
- **Severity**: Critical, High, Medium, or Low.
- **Issues Identified**: Specific rule infractions (e.g., used robotic filler words, triggered redundant searches, failed to claim ALOY Identity).
- **Suggested Fixes**: Direct action points specifying which files (e.g. `conversation/context_builder.py`, `models/router.py`) require modification.

---

## 3. Pre-Release Workflow Guidelines

Before tagging or shipping any release candidate:
1. **Clean Workspace Run**: Ensure all standard unit tests are passing (`python -m pytest`).
2. **Execute Validation Run**: Run the fast validation suite (`python validation/run.py`).
3. **Audit the Report**: Open `reports/validation_report.md` and check the **Regressions** section. If regressions exist, resolve the root cause in the code.
4. **Finalize Baseline**: Once all regressions are solved, run `python validation/run.py --save-baseline` to store the new baseline. Commit `validation/baseline.json` into git.
