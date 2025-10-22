# evaluator_agent_runtime.py
import json
import uuid
import time
from typing import Optional, Dict, Any

import re

from strands import Agent
from strands.models import BedrockModel

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from lab_helpers.smartgoalgenerator_mcp_tools import build_eval_plan_v2, load_analyzer_runs_v2

# =========================================
# ===== Module-level constants ============
# =========================================
EVALUATOR_MODEL_ID = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"

# ==================================
# ===== LLM-as-Judge essential =====
# ==================================
def evaluator_system_prompt() -> str:
    return """You are an Evaluator (LLM-as-Judge) that supports multiple evaluation modes via a plan.

CRITICAL: You MUST evaluate ALL cases provided in the plan. Do not stop early or skip any cases.

You will be given a plan from the tool build_eval_plan_v2(analyzer_json_src, limit) with:
- evaluation_type: "engagement_vs_clinician" or "smart_goals_rubric"
- metrics: list of metric names to score in [0.0, 1.0]
- rubric: guidance for scoring
- cases: a list of cases to evaluate

CALLS:
1) Call build_eval_plan_v2(analyzer_json_src, limit) EXACTLY ONCE (use the user-provided {"analyzer_json_src":analyzer_json_src} if present; otherwise none).

SCORING:
- For "engagement_vs_clinician":
  Each case has:
    { case_id, timestamp, device_id, analyzer{category_recommended, rationale}, clinician{category_recommended, rationale} }
  Score metrics: correctness, completeness, helpfulness, coherence, relevance.
  Also produce:
    agreement = "match" | "partial" | "mismatch"
  Rules:
    - match if categories are the same (case-insensitive).
    - partial if different but analyzer rationale substantially overlaps clinician intent.
    - mismatch otherwise.

- For "smart_goals_rubric":
  Each case has:
    { case_id, timestamp, goal_number, goal_text }
  Score metrics: specific, measurable, achievable, relevant, time_bound, clarity.
  Focus only on the goal_text vs rubric. If unsafe, note it briefly.

OUTPUT: STRICT JSON ONLY:
{
  "evaluation_type": "string",
  "cases_scored": 0,
  "scores": [
    {
      "case_id": "string",
      "metric_scores": { "<metric>": 0.0 },
      "agreement": "match|partial|mismatch|n/a",
      "notes": "short justification (<=40 words)"
    }
  ]
}

PROCESS:
- Produce one score object per case with values in [0.0, 1.0].
- Use "agreement":"n/a" for smart_goals_rubric (no clinician).
- Keep notes concise and specific.
"""

# ==============================
# ===== Json/Jsonl helpers =====
# ==============================
def clean_json_str(s: str) -> str:
    # remove trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # strip any junk after final closing brace
    last_brace = max(s.rfind("}"), s.rfind("]"))
    if last_brace != -1:
        s = s[:last_brace+1]
    return s

def _coerce_json(s):
    import json, re

    if not isinstance(s, str):
        if hasattr(s, "output"): s = s.output
        elif hasattr(s, "content"): s = s.content
        elif hasattr(s, "text"): s = s.text
        else: s = str(s)

    s = s.strip()

    if s.startswith("{") and s.endswith("}"):
        candidate = s
    else:
        m = re.search(r"\{.*\}", s, flags=re.DOTALL)
        if not m:
            raise ValueError("No JSON object found in agent output.")
        candidate = m.group(0)

    candidate = clean_json_str(candidate)
    
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        # Print useful debug info
        snippet = candidate[max(0, e.pos-80):e.pos+80]
        print(f"\n--- JSON parse error ---\n{e}\nContext:\n...{snippet}...\n")
        raise

# =========================================
# ===== Module-level evaluator agent ======
# =========================================

# Step 1: Initialize BedrockModel at module load (only if tool is available)
evaluator_model = BedrockModel(
    model_id=EVALUATOR_MODEL_ID,
    max_tokens=8192,
    temperature=0.8,
    top_k=50,
    top_p=0.95,
)

# Prepare evaluator agent configuration
evaluator_agent_kwargs = {"model": evaluator_model}

# Add tools if available
try:
    evaluator_agent_kwargs["tools"] = [build_eval_plan_v2, load_analyzer_runs_v2]
except Exception as e:
    print(f"Tool listing failed: {e}")

# Add system prompt
evaluator_agent_kwargs["system_prompt"] = evaluator_system_prompt()

# Initialize evaluator agent once with the right capabilities
evaluator_agent = Agent(**evaluator_agent_kwargs)

# =========================================
# ===== Bedrock AgentCore Entrypoint --- Initialize the agentcore runtime ======
# =========================================
app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload: Dict[str, Any]):
    """AgentCore Runtime entrypoint function"""
    try:
        analyzer_payload = payload.get("analyzer_payload")
        if not analyzer_payload:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No analyzer_payload provided."})
            }

        # Step 1: Run the evaluator agent
        text = "Please analyze this analyzer output and provide evaluation metrics: " + json.dumps(analyzer_payload)
        response = evaluator_agent(text)

        # Step 2: Parse agent output using the same helper function as smart goal generator
        parsed = _coerce_json(response)

        # Step 3: Structure the evaluation output
        output_obj = {
            "run_id": str(uuid.uuid4()),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "evaluator_output": parsed,
            "analyzer_input": analyzer_payload
        }

        # Step 4: Return HTTP-style response
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(output_obj, ensure_ascii=False)
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }    

if __name__ == "__main__":
    app.run()
