# Identity Engine & Prompt Integrity — ALOY Version 1.0

ALOY includes an **Identity Engine** designed to maintain a consistent companion personality, align with founder preferences, and secure system prompts from leakage or injection attacks.

---

## 1. Founder & Companion Profile Seeding

On first run, the Identity Engine seeds permanent, decay-exempt profiles into the local database:
* **Creator Profile (Dhanush A.)**: Records creator attribution metadata.
* **User Profile**: Records user details, preferences, and custom instructions (dynamic workspace preferences).
* **Companion Profile (ALOY)**: Seeds the baseline rules of engagement, persona parameters, casual casual-friendly tone limits, and code partner behaviors.

---

## 2. Dynamic Capability Verification

Instead of using static prompt templates, ALOY inspects the active running state of the microkernel before generating system prompts:
* **Module Check**: The context builder checks which endpoints are registered on `FastAPI.state` (e.g. confirming if the memory connection is active, if the evolution engine is running, or if search routing is active).
* **Workspace Status**: Inspects the target repository path to find the current active git branch, recent commits, and working directory files, appending them to the system prompt dynamically.

---

## 3. Prompt Integrity & Leakage Filter

To prevent prompt injection attacks or internal LLM metadata from showing in the chat view:
* **Line-Level Block Filters**: The `PromptIntegrityFilter` checks incoming token streams for model-generated headers (such as `System:`, `Assistant:`, or unclosed XML block tags like `<reasoning>`).
* **Unclosed Tag Buffer**: Holds partial characters in a lookahead buffer to reconstruct and strip tags across chunk boundaries before sending clean text to the client.

---

*Designed and developed by Dhanush A.*
