import os
import re
import json
import time
import uuid

import boto3
import json

# ===========================================
# ===== Runtime / Model Imports ============
# ===========================================
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from scripts.utils import get_ssm_parameter

# Project helpers (must be in your deployment package)
from lab_helpers.smartgoalgenerator_model_util import (
    model_supports_system_prompt,
    model_supports_tools,
    get_analyzer_prompt,
)

# Optional tools
try:
    from lab_helpers.smartgoalgenerator_mcp_tools import (
        load_analyzer_runs_v2,
        build_eval_plan_v2,
        fetch_data,
    )
except Exception:
    load_analyzer_runs_v2 = None
    build_eval_plan_v2 = None
    fetch_data = None

# ===================================
# ============ CONSTANTS ============
# ===================================
#MODEL_ID = "mistral.mistral-7b-instruct-v0:2"
#MODEL_ID = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
#MODEL_ID = "meta.llama3-70b-instruct-v1:0"
#MODEL_ID = "mistral.mistral-large-2402-v1:0"
#MODEL_ID = "cohere.command-r-v1:0"
#MODEL_ID = "openai.gpt-oss-120b-1:0"

# ===================================
# ============ MODELS THAT WORKED ============
MODEL_ID = "mistral.mistral-7b-instruct-v0:2"
#MODEL_ID = "us.anthropic.claude-3-7-sonnet-20250219-v1:0" 
#MODEL_ID = "cohere.command-r-v1:0"    
#MODEL_ID = "openai.gpt-oss-120b-1:0"  
#MODEL_ID = "us.amazon.nova-premier-v1:0"

EVAL_MODEL_ID = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"

OUTPUT_DIR_INDIVIDUAL = "./outputs"
output_jsonl = "./outputs/results.jsonl"

# =========================================
# Evaluator runtime ARN
# =========================================
EVALUATOR_RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:711246752798:runtime/llm_evaluator_agent-M3IWgT3T7l"
# =========================================
# Helper function to call evaluator runtime
# =========================================
def call_evaluator_runtime(payload: dict) -> dict:
    # Initialize the Bedrock AgentCore client
    agent_core_client = boto3.client('bedrock-agentcore')
  
    # Prepare the payload prompt
    #payload={'analyzer_payload':output_obj}
    prompt = json.dumps(payload).encode()
  
    # Invoke the agent
    response = agent_core_client.invoke_agent_runtime(
                    agentRuntimeArn=EVALUATOR_RUNTIME_ARN,
                    #agentRuntimeArn="arn:aws:bedrock-agentcore:us-east-1:711246752798:runtime/llm_evaluator_agent-jf0YsKAH8C", 
                    #runtimeSessionId=session_id,
                    payload=prompt
                    )

    # Process and print the response
    if "text/event-stream" in response.get("contentType", ""):
        # Handle streaming response
        content = []
        for line in response["response"].iter_lines(chunk_size=10):
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                    print(line)
                    content.append(line)
        #print("\nComplete response:", "\n".join(content))
        return "\n".join(content)
        
    elif response.get("contentType") == "application/json":
        # Handle standard JSON response
        content = []
        for chunk in response.get("response", []):
            content.append(chunk.decode('utf-8'))
        #print(json.loads(''.join(content)))
        return json.loads(''.join(content))
  
    #else:
        # Print raw response for other content types
        #print(response)
    return response


# ===============================================
# ===== Json/Jsonl Utility Helper Functions =====
# ===============================================
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


def _append_jsonl(path: str, obj: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


# ===========================================
# ---------- helpers for filenames ----------
# ===========================================
def _basename_no_ext(path_or_uri: str) -> str:
    """
    's3://bucket/path/patient1_summary.docx' -> 'patient1_summary'
    'patient2.pdf' -> 'patient2'
    'https://.../file.txt?x=y' -> 'file' (best effort)
    """
    s = path_or_uri.split("?", 1)[0]
    if s.lower().startswith("s3://"):
        _, key = s[5:].split("/", 1)
        base = os.path.basename(key)
    else:
        base = os.path.basename(s)
    name, _ext = os.path.splitext(base)
    return name or "unknown_source"

def _safe_fragment(s: str) -> str:
    """
    Make a safe filename fragment: replace non [A-Za-z0-9_-] with '_'.
    Also replace ':', '.', '/' commonly found in model ids.
    """
    s = s.replace(":", "_").replace("/", "_").replace(".", "_")
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in s)
    

# =============================================
# ===== Model Selection and configuration =====
# =============================================

# Lab1 import: Create the Bedrock model
#model = BedrockModel(model_id=MODEL_ID)

model = BedrockModel(
                model_id=MODEL_ID,
                max_tokens=1024,
                temperature=0.8,
                top_k=50,
                top_p=0.95,
)

# Check model capabilities
supports_system_prompt = model_supports_system_prompt(MODEL_ID)
supports_tools = model_supports_tools(MODEL_ID)

# Build a static system prompt (rules only, no src embedded)
SYSTEM_PROMPT = get_analyzer_prompt("")

# Prepare agent configuration
#agent_kwargs = {"model": model}

"""
if supports_tools:
    agent_kwargs["tools"] = [fetch_data]


if supports_system_prompt:
    agent_kwargs["system_prompt"] = SYSTEM_PROMPT

# Initialize agent once with the right capabilities
agent = Agent(**agent_kwargs)
"""

# Add tools if available
optional_tools = []
if fetch_data:
    optional_tools.append(fetch_data)
if build_eval_plan_v2:
    optional_tools.append(build_eval_plan_v2)

# if supports_tools and optional_tools:
#     agent_kwargs["tools"] = optional_tools

# if supports_system_prompt:
#     agent_kwargs["system_prompt"] = SYSTEM_PROMPT

# agent = Agent(**agent_kwargs)

# Initialize the AgentCore Runtime App
app = BedrockAgentCoreApp()  #### AGENTCORE RUNTIME - LINE 2 ####


@app.entrypoint  #### AGENTCORE RUNTIME - LINE 3 ####
def invoke(payload):
    """AgentCore Runtime entrypoint function"""
    try:
        user_input = payload.get("prompt", "").strip()
        if not user_input:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No prompt provided."})
            }

        file_path = None
        original_data_source = user_input  # Preserve original for data_source field
        
        if "[UPLOADED_FILE:" in user_input:
            import re
            file_match = re.search(r'\[UPLOADED_FILE:\s*([^\]]+)\]', user_input)
            if file_match:
                file_path = file_match.group(1).strip()
                # Set data_source to the file path for better tracking
                original_data_source = file_path
                # Remove the file marker from user input
                user_input = re.sub(r'\[UPLOADED_FILE:[^\]]+\]', '', user_input).strip()
                print(f"📁 Processing uploaded file: {file_path}")
        
        # Get model ID from payload, fallback to default
        requested_model_id = payload.get("model_id", MODEL_ID)
        print(f"Using model: {requested_model_id}")

        
        # Create model instance with requested model ID
        dynamic_model = BedrockModel(
            model_id=requested_model_id,
            max_tokens=4096,
            temperature=0.8,
            top_k=50,
            top_p=0.95,
        )
        
        # Check model capabilities for the requested model
        dynamic_supports_system_prompt = model_supports_system_prompt(requested_model_id)
        dynamic_supports_tools = model_supports_tools(requested_model_id)
        
        # Create agent with dynamic model
        dynamic_agent_kwargs = {"model": dynamic_model}
        
        if dynamic_supports_tools and optional_tools:
            dynamic_agent_kwargs["tools"] = optional_tools
        
        # Set system prompt based on whether we have a file or not
        if dynamic_supports_system_prompt:
            if file_path:
                # Use dynamic system prompt with file path as data_source
                try:
                    dynamic_system_prompt = get_analyzer_prompt(file_path)
                    print(f"📋 System prompt length: {len(dynamic_system_prompt)} characters")
                    dynamic_agent_kwargs["system_prompt"] = dynamic_system_prompt
                except Exception as e:
                    print(f"❌ Error generating system prompt: {e}")
                    # Fallback to static prompt
                    dynamic_agent_kwargs["system_prompt"] = SYSTEM_PROMPT
            else:
                # Use static system prompt for non-file inputs
                dynamic_agent_kwargs["system_prompt"] = SYSTEM_PROMPT
        
        # Initialize dynamic agent
        dynamic_agent = Agent(**dynamic_agent_kwargs)

        # Step 1: Run the dynamic agent with requested model
        if file_path:
            # The system prompt already instructs the agent to use fetch_data with the file_path
            print(f"📁 File path for agent: {file_path}")
            
            if dynamic_supports_tools and dynamic_supports_system_prompt:
                # Agent has tools and system prompt - pass the user's original input
                response = dynamic_agent(user_input)
            elif dynamic_supports_tools:
                # Agent has tools but no system prompt - provide the system prompt manually
                system_prompt_with_file = get_analyzer_prompt(file_path)
                response = dynamic_agent(system_prompt_with_file)
            else:
                # No tools available, try direct fetch as fallback
                try:
                    file_result = fetch_data(file_path)
                    if file_result.get("formatted_text"):
                        file_context = f"\n\nFile content:\n{file_result['formatted_text'][:2000]}..."
                        if dynamic_supports_system_prompt:
                            # System prompt already set, just add file content
                            response = dynamic_agent(f"{user_input}\n\nFile content: {file_context}")
                        else:
                            # No system prompt, provide everything
                            system_prompt_with_content = get_analyzer_prompt(file_path)
                            response = dynamic_agent(f"{system_prompt_with_content}\n\nUser request: {user_input}\n\nFile content: {file_context}")
                    else:
                        raise Exception("No file content extracted")
                except Exception as e:
                    print(f"Error processing file: {e}")
                    error_message = f"Error reading file {file_path}: {str(e)}"
                    if dynamic_supports_system_prompt:
                        response = dynamic_agent(f"{user_input}\n\n{error_message}")
                    else:
                        system_prompt_with_error = get_analyzer_prompt(file_path)
                        response = dynamic_agent(f"{system_prompt_with_error}\n\nUser request: {user_input}\n\n{error_message}")
        else:
            # No file uploaded, proceed normally
            if dynamic_supports_tools and dynamic_supports_system_prompt:
                response = dynamic_agent(f"DATA_SOURCE: {user_input}")
            elif dynamic_supports_tools:
                response = dynamic_agent(f"{SYSTEM_PROMPT}\n\nDATA_SOURCE: {user_input}")
            elif dynamic_supports_system_prompt:
                response = dynamic_agent(f"DATA_SOURCE: {user_input}")
            else:
                response = dynamic_agent(f"{SYSTEM_PROMPT}\n\nDATA_SOURCE: {user_input}")



        # Step 2: Parse agent output
        parsed = _coerce_json(response)

        # Step 3: Normalize smart goals
        smart_goals = []
        goals_data = parsed.get("smart_goals") or parsed.get("goals") or []

        for idx, goal in enumerate(goals_data, start=1):
            if isinstance(goal, dict):
                desc = goal.get("description") or goal.get("goal") or str(goal)
            else:
                desc = str(goal)
            smart_goals.append({
                "goal_number": idx,
                "description": desc.strip()
            })

        # Step 4: Final structured output
        output_obj = {
            "model_id": requested_model_id,
            "data_source": original_data_source,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "smart_goals": smart_goals,
        }

        # Step 5: Save outputs
        os.makedirs(OUTPUT_DIR_INDIVIDUAL, exist_ok=True)
        base = _basename_no_ext(user_input)
        safe_model = _safe_fragment(MODEL_ID)
        out_path = os.path.join(
            OUTPUT_DIR_INDIVIDUAL, f"{base}_{safe_model}_output.json"
        )

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output_obj, f, ensure_ascii=False, indent=2)

        _append_jsonl(output_jsonl, output_obj)

        # Step 6: Call evaluator runtime (optional)
        evaluator_result = None
        if build_eval_plan_v2:
            try:
                output_obj1 = output_obj
                payload={'analyzer_payload':output_obj1}
                raw_output = call_evaluator_runtime(payload) 
                eval_dict = json.loads(raw_output['body'])['evaluator_output']
                evaluator_result = json.dumps(eval_dict, indent=2)
                
            except Exception as ex:
                print(f"Evaluator runtime failed: {ex}")
                evaluator_result = {"error": str(ex)}


        # Cleanup temporary file if it exists
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"Cleaned up temporary file: {file_path}")
            except Exception as cleanup_error:
                print(f"Could not cleanup file {file_path}: {cleanup_error}")

        
        # Step 7: Return HTTP-style response
        combined = {"model_output": output_obj}
        if evaluator_result:
            combined["evaluator_result"] = evaluator_result

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(combined, ensure_ascii=False),
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        # Cleanup temporary file even on error
        if 'file_path' in locals() and file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"Cleaned up temporary file after error: {file_path}")
            except:
                pass
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


    #user_input = payload.get("prompt", "")      #user_input is the file path
    # Invoke the agent
    #response = agent(user_input)
    #return response.message["content"][0]["text"]


if __name__ == "__main__":
    app.run()  #### AGENTCORE RUNTIME - LINE 4 ####



