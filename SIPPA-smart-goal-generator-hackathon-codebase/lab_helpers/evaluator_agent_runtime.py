# evaluator_agent_runtime.py

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
        system_prompt="Evaluator LLM-as-Judge",
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

