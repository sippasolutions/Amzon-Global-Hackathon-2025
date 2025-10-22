# evaluator_agent_runtime_v1.py
import json
import uuid
import time
from typing import Optional, Dict, Any

from strands import Agent
from strands.models import BedrockModel
from lab_helpers.smartgoalgenerator_mcp_tools import build_eval_plan_v2

from bedrock_agentcore.runtime import BedrockAgentCoreApp

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


# =========================================
# ===== Module-level evaluator agent ======
# =========================================

# Step 1: Initialize BedrockModel at module load
evaluator_model = BedrockModel(model_id=EVALUATOR_MODEL_ID, max_tokens=8192)

# Step 2: Initialize Agent at module load (only if tool is available)
evaluator_agent: Optional[Agent] = None
if build_eval_plan_v2 and callable(build_eval_plan_v2):
    evaluator_agent = Agent(
        model=evaluator_model,
        system_prompt= evaluator_system_prompt(),   #"Evaluator LLM-as-Judge",
        tools=[build_eval_plan_v2],
    )
else:
    print("Evaluator tool not available; agent will not support evaluation.")

# =========================================
# ===== Evaluator logic ===================
# =========================================
def run_evaluator(analyzer_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not evaluator_agent:
        raise RuntimeError("Evaluator agent not initialized or tool missing.")

    text = "This is analyzer_json_src for evaluation: " + json.dumps(analyzer_payload)
    raw = evaluator_agent(text)  # Already initialized
    try:
        out = json.loads(raw)
    except Exception as e:
        raise ValueError(f"Failed to parse evaluator output: {e}")

    return {
        "run_id": str(uuid.uuid4()),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "evaluator_output": out,
    }

# =========================================
# ===== Bedrock AgentCore Entrypoint ======
# =========================================
app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload: Dict[str, Any]):
    analyzer_payload = payload.get("analyzer_payload")
    if not analyzer_payload:
        return {"statusCode": 400, "body": json.dumps({"error": "Missing analyzer_payload"})}

    try:
        result = run_evaluator(analyzer_payload)
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as ex:
        return {"statusCode": 500, "body": json.dumps({"error": str(ex)})}

if __name__ == "__main__":
    app.run()
