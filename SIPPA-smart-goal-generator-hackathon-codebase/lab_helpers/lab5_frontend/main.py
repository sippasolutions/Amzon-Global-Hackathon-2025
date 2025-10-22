import os
import streamlit as st
from chat import ChatManager, invoke_endpoint_streaming
import uuid
from streamlit_cognito_auth import CognitoAuthenticator
import json
import time
from chat_utils import make_urls_clickable
import os
import sys
import tempfile
import boto3
from s3_config import get_upload_bucket, ensure_bucket_exists
from hipaa_cleanup import register_hipaa_file, check_hipaa_compliance, force_hipaa_cleanup



# Get the current file's directory and add the project root to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.append(project_root)

from utils import get_ssm_parameter, get_smart_goal_secret

secret = get_smart_goal_secret()
secret = json.loads(secret)

authenticator = CognitoAuthenticator(
    pool_id=secret['pool_id'],
    app_client_id=secret['client_id'],
    app_client_secret=secret['client_secret'],
    use_cookies=False
)

is_logged_in = authenticator.login()
if not is_logged_in:
    st.stop()


def logout():
    print("Logout in example")
    authenticator.logout()

qualifier = "DEFAULT"

# Available model IDs
AVAILABLE_MODELS = {
    "Claude 3.7 Sonnet": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "OpenAI GPT": "openai.gpt-oss-120b-1:0",
    "Amazon Nova Premier": "us.amazon.nova-premier-v1:0",
    "Cohere Command-R": "cohere.command-r-v1:0", 
    "Mistral 7b Instruct": "mistral.mistral-7b-instruct-v0:2"
}

def format_response_text(text):
    """Format response text by unescaping quotes and newlines"""
    if not text:
        return text
    
    # Remove outer quotes if present
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    
    # Unescape common escape sequences
    text = text.replace('\\"', '"')
    text = text.replace('\\n', '\n')
    text = text.replace('\\t', '\t')
    text = text.replace('\\r', '\r')
    
    return text

def save_uploaded_file(uploaded_file):
    """Save uploaded file to temporary location and return path"""
    if uploaded_file is None:
        return None
    
    # Create temporary file
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"upload_{uuid.uuid4().hex}_{uploaded_file.name}")
    
    # Write file content
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    
    return temp_path


def upload_file_to_s3(uploaded_file):
    """Upload file to S3 and return S3 URI"""
    if uploaded_file is None:
        return None
    
    try:
        # Get S3 bucket and ensure it exists
        bucket_name = get_upload_bucket()
        
        if not ensure_bucket_exists(bucket_name):
            raise Exception(f"Cannot access or create S3 bucket: {bucket_name}")
        
        # Generate unique S3 key
        file_key = f"uploads/{uuid.uuid4().hex}_{uploaded_file.name}"
        
        # Initialize S3 client
        s3_client = boto3.client('s3')
        
        # Upload file to S3
        uploaded_file.seek(0)
        s3_client.upload_fileobj(
            uploaded_file,
            bucket_name,
            file_key,
            ExtraArgs={'ContentType': uploaded_file.type or 'application/octet-stream'}
        )
        
        # Return S3 URI
        s3_uri = f"s3://{bucket_name}/{file_key}"
        print(f"✅ File uploaded to S3: {s3_uri}")

        # HIPAA-compliant registration for 2-hour deletion
        # if register_hipaa_file(s3_uri):
        #     print(f"🏥 HIPAA compliance: File registered for 2-hour deletion")
        # else:
        #     print(f"⚠️ HIPAA warning: Could not register file for cleanup")

        if register_hipaa_file(s3_uri):
            print(f"🏥 File registered for 2-minute deletion")
        else:
            print(f"⚠️ Warning: Could not register file for cleanup")
            
        return s3_uri
        
    except Exception as e:
        print(f"❌ S3 upload failed: {e}")
        st.error(f"S3 upload failed: {e}")
        # Fallback to temporary file for backward compatibility
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"upload_{uuid.uuid4().hex}_{uploaded_file.name}")
        
        # Reset file pointer and write to temp file
        uploaded_file.seek(0)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.read())
        
        print(f"⚠️ Using temporary file fallback: {temp_path}")
        st.warning(f"Using temporary file fallback: {temp_path}")
        return temp_path




def parse_smart_goals(response_text):
    """Parse SMART goals from the agent response"""
    try:
        # If response_text is already a list (from our filtering), return it
        if isinstance(response_text, list):
            return response_text
            
        # Try to parse as JSON first
        if response_text.strip().startswith('{'):
            data = json.loads(response_text)
            if 'smart_goals' in data:
                return data['smart_goals']
            elif 'goals' in data:
                return data['goals']
        
        # If not JSON, try to extract goals from text
        goals = []
        lines = response_text.split('\n')
        current_goal = ""
        goal_number = 1
        
        for line in lines:
            line = line.strip()
            if line and (line.startswith(f"{goal_number}.") or line.startswith(f"Goal {goal_number}:")):
                if current_goal:
                    goals.append({"goal_number": goal_number - 1, "description": current_goal.strip()})
                current_goal = line
                goal_number += 1
            elif line and current_goal:
                current_goal += " " + line
        
        if current_goal:
            goals.append({"goal_number": goal_number - 1, "description": current_goal.strip()})
        
        return goals if goals else [{"goal_number": 1, "description": response_text}]
    
    except Exception as e:
        print(f"Error parsing goals: {e}")
        return [{"goal_number": 1, "description": response_text}]

# Configure page
st.set_page_config(
    page_title="SMART Goal Generator",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Header with user info and logout
col1, col2 = st.columns([4, 1])
with col1:
    st.title("🎯 SMART Goal Treatment Planner")
    st.markdown("**Generate evidence-based SMART goals from patient encounter summary notes**")
with col2:
    st.markdown(f"**Welcome, {authenticator.get_username()}**")
    if st.button("🚪 Logout", type="secondary"):
        logout()

st.markdown("---")

st.markdown("""
<style>
.main-container {
    background-color: #f8f9fa;
    padding: 2rem;
    border-radius: 10px;
    margin: 1rem 0;
}
.upload-section {
    background-color: #ffffff;
    padding: 1.5rem;
    border-radius: 8px;
    border: 2px dashed #e0e0e0;
    margin: 1rem 0;
    text-align: center;
}
.model-section {
    background-color: #ffffff;
    padding: 1.5rem;
    border-radius: 8px;
    border: 1px solid #e0e0e0;
    margin: 1rem 0;
}
.results-section {
    background-color: #ffffff;
    padding: 1.5rem;
    border-radius: 8px;
    border: 1px solid #e0e0e0;
    margin: 1rem 0;
}
.goal-card {
    background-color: #f8f9fa;
    padding: 1rem;
    border-radius: 6px;
    border-left: 4px solid #007bff;
    margin: 0.5rem 0;
}
.success-banner {
    background-color: #d4edda;
    color: #155724;
    padding: 1rem;
    border-radius: 6px;
    border: 1px solid #c3e6cb;
    margin: 1rem 0;
}
.processing-banner {
    background-color: #fff3cd;
    color: #856404;
    padding: 1rem;
    border-radius: 6px;
    border: 1px solid #ffeaa7;
    margin: 1rem 0;
    text-align: center;
}
.stButton > button {
    width: 100%;
    background-color: #007bff;
    color: white;
    border: none;
    padding: 0.75rem 1.5rem;
    border-radius: 6px;
    font-weight: 600;
}
.stButton > button:hover {
    background-color: #0056b3;
}
</style>
""", unsafe_allow_html=True)


# Initialize session state
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
if "generated_goals" not in st.session_state:
    st.session_state["generated_goals"] = None
if "processing" not in st.session_state:
    st.session_state["processing"] = False
if "error_message" not in st.session_state:
    st.session_state["error_message"] = None

chat_manager = ChatManager("default")

# Main interface layout
col1, col2 = st.columns([1, 1])

with col1:
    st.markdown('<div class="model-section">', unsafe_allow_html=True)
    st.subheader("🤖 AI Model Selection")
    
    selected_model_name = st.selectbox(
        "Choose AI Model:",
        options=list(AVAILABLE_MODELS.keys()),
        index=0,  # Default to Claude 3.7 Sonnet
        help="Select the AI model for generating SMART goals"
    )
    
    st.session_state["selected_model_id"] = AVAILABLE_MODELS[selected_model_name]
    
    st.info(f"**Selected:** {selected_model_name}")
    st.caption(f"Model optimized for healthcare goal generation")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="upload-section">', unsafe_allow_html=True)
    st.subheader("📄 Patient Summary Upload")
    
    uploaded_file = st.file_uploader(
        "Upload Patient Summary Document",
        type=['pdf', 'docx', 'txt'],
        help="Upload patient summary in PDF, DOCX, or TXT format",
        label_visibility="collapsed"
    )
    
    if uploaded_file is not None:
        st.success(f"✅ **{uploaded_file.name}** uploaded successfully")
        st.caption(f"📊 Size: {uploaded_file.size:,} bytes | 📄 Type: {uploaded_file.type}")
    else:
        st.info("📁 Please upload a patient summary document")
        st.caption("Supported formats: PDF, DOCX, TXT")
    
    st.markdown('</div>', unsafe_allow_html=True)

# Generate Goals Section
st.markdown('<div class="main-container">', unsafe_allow_html=True)

# Show processing state
if st.session_state.get("processing", False):
    st.markdown("""
    <div class="processing-banner">
        <h4>🔄 Generating SMART Goals...</h4>
        <p>Analyzing patient summary and generating evidence-based goals. Please wait...</p>
    </div>
    """, unsafe_allow_html=True)

# Generate button
generate_disabled = uploaded_file is None or st.session_state.get("processing", False)
if st.button("🎯 Generate SMART Goals", disabled=generate_disabled, type="primary"):
    if uploaded_file is not None:
        st.session_state["processing"] = True
        st.session_state["uploaded_file_for_processing"] = uploaded_file
        st.session_state["selected_model_for_processing"] = selected_model_name
        # Clear any previous error messages
        st.session_state["error_message"] = None
        st.session_state["generated_goals"] = None
        st.rerun()

# Process the file if we're in processing state
if st.session_state.get("processing", False) and "uploaded_file_for_processing" in st.session_state:
    uploaded_file_to_process = st.session_state["uploaded_file_for_processing"]
    selected_model_name_to_process = st.session_state["selected_model_for_processing"]
    
    try:
        # Upload file to S3
        file_path = upload_file_to_s3(uploaded_file_to_process)
        if not file_path:
            raise Exception("File upload failed - no file path returned")
        
        # Verify S3 upload succeeded (S3 paths start with s3://)
        if not file_path.startswith('s3://'):
            st.warning(f"⚠️ Using temporary file fallback: {file_path}")
            st.info("Note: Temporary files may not be accessible by the agent runtime. Consider checking S3 permissions.")
        else:
          #  st.success(f"✅ File uploaded to S3: {file_path}")
            # Verify the file exists in S3
            try:
                bucket_name = get_upload_bucket()
                file_key = file_path.replace(f"s3://{bucket_name}/", "")
                s3_client = boto3.client('s3')
                s3_client.head_object(Bucket=bucket_name, Key=file_key)
               # st.success("✅ S3 upload verified")
            except Exception as verify_error:
                st.error(f"❌ S3 upload verification failed: {verify_error}")

            prompt = f"Please analyze the uploaded patient summary and generate SMART goals. [UPLOADED_FILE: {file_path}]"

            
            # Prepare payload
            payload_data = {
                "prompt": prompt,
                "actor_id": st.session_state["auth_username"],
                "model_id": st.session_state["selected_model_id"]
            }
            payload = json.dumps(payload_data)
            
            # Call the agent
            start_time = time.time()
            response = chat_manager.invoke_endpoint_nostreaming(
                agent_arn=st.session_state["agent_arn"],
                payload=payload,
                bearer_token=st.session_state["auth_access_token"],
                session_id=st.session_state["session_id"]
            )
            
            elapsed_time = time.time() - start_time
            
            # TEMPORARY DEBUG: Store full HTTP response details
            debug_info = {
                "status_code": getattr(response, 'status_code', 'Unknown'),
                "headers": dict(getattr(response, 'headers', {})),
                "raw_content": None,
                "content_type": getattr(response, 'headers', {}).get('content-type', 'Unknown')
            }
            
            # Extract and parse the response
            if hasattr(response, 'text'):
                response_text = response.text
                debug_info["raw_content"] = response_text
            elif hasattr(response, 'content'):
                response_text = response.content.decode('utf-8') if isinstance(response.content, bytes) else str(response.content)
                debug_info["raw_content"] = response_text
            else:
                response_text = str(response)
                debug_info["raw_content"] = response_text
            
            # Store debug info in session state for display
            st.session_state["debug_response"] = debug_info
            
            # Parse the HTTP response to extract the actual agent output
            filtered_output = {}
            try:
                # Try to parse as JSON (HTTP response format)
                if response_text.strip().startswith('{"statusCode"'):
                    http_response = json.loads(response_text)
                    if 'body' in http_response:
                        # Extract the body and parse it
                        body_content = http_response['body']
                        if isinstance(body_content, str):
                            # Parse the body as JSON
                            agent_output = json.loads(body_content)
                        else:
                            agent_output = body_content
                        
                        # Extract just the smart_goals and evaluator_result
                        if 'model_output' in agent_output and 'smart_goals' in agent_output['model_output']:
                            filtered_output['smart_goals'] = agent_output['model_output']['smart_goals']
                        if 'evaluator_result' in agent_output:
                            filtered_output['evaluator_result'] = agent_output['evaluator_result']
                        
                        # Convert back to formatted text for display
                        formatted_response = json.dumps(filtered_output, indent=2)
                        goals = filtered_output.get('smart_goals', [])
                    else:
                        # Fallback to original parsing
                        formatted_response = format_response_text(response_text)
                        goals = parse_smart_goals(formatted_response)
                else:
                    # Not an HTTP response format, use original parsing
                    formatted_response = format_response_text(response_text)
                    goals = parse_smart_goals(formatted_response)
            except (json.JSONDecodeError, KeyError) as e:
                # Fallback to original parsing if JSON parsing fails
                formatted_response = format_response_text(response_text)
                goals = parse_smart_goals(formatted_response)
            
            # Store results
            result_data = {
                "goals": goals,
                "raw_response": formatted_response,
                "elapsed_time": elapsed_time,
                "model_used": selected_model_name_to_process,
                "file_name": uploaded_file_to_process.name
            }
            
            # Add evaluator result if it exists in the filtered output
            if 'evaluator_result' in filtered_output:
                result_data["evaluator_result"] = filtered_output['evaluator_result']
            
            st.session_state["generated_goals"] = result_data
            
            # Clean up temporary file
            if file_path and not file_path.startswith('s3://') and os.path.exists(file_path):
                os.remove(file_path)
                
    except Exception as e:
        # Store error in session state so it persists across reruns
        import traceback
        error_info = {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        
        # Include debug response info if available
        if "debug_response" in st.session_state:
            error_info["http_response"] = st.session_state["debug_response"]
        
        st.session_state["error_message"] = error_info
    finally:
        st.session_state["processing"] = False
        # Clean up processing variables
        if "uploaded_file_for_processing" in st.session_state:
            del st.session_state["uploaded_file_for_processing"]
        if "selected_model_for_processing" in st.session_state:
            del st.session_state["selected_model_for_processing"]
        st.rerun()

# Display Error Message
if st.session_state.get("error_message"):
    error_info = st.session_state["error_message"]
    
    st.markdown("""
    <div style="background-color: #f8d7da; color: #721c24; padding: 1rem; border-radius: 6px; border: 1px solid #f5c6cb; margin: 1rem 0;">
        <h4>❌ Error Generating SMART Goals</h4>
    </div>
    """, unsafe_allow_html=True)
    
    st.error(f"**Error:** {error_info['error']}")
    
    # Show detailed error in an expander
    with st.expander("🔍 View Technical Details"):
        st.code(error_info['traceback'], language='python')
        
        # Show HTTP response details if available
        if 'http_response' in error_info:
            st.subheader("HTTP Response Details")
            http_resp = error_info['http_response']
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Status Code", http_resp.get('status_code', 'Unknown'))
            with col2:
                st.metric("Content Type", http_resp.get('content_type', 'Unknown'))
            
            st.subheader("Response Headers")
            st.json(http_resp.get('headers', {}))
            
            st.subheader("Raw Response Content")
            raw_content = http_resp.get('raw_content', 'No content available')
            st.code(raw_content, language='json' if 'json' in str(http_resp.get('content_type', '')).lower() else 'text')
    
    # Clear error button
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("🔄 Try Again", type="secondary"):
            st.session_state["error_message"] = None
            st.rerun()

# Display Results
if st.session_state.get("generated_goals"):
    results = st.session_state["generated_goals"]
    
    st.markdown("""
    <div class="success-banner">
        <h4>✅ SMART Goals Generated Successfully!</h4>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="results-section">', unsafe_allow_html=True)
    
    # Results header
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.subheader(f"📋 Generated Goals for: {results['file_name']}")
    with col2:
        st.metric("Model Used", results['model_used'])
    with col3:
        st.metric("Processing Time", f"{results['elapsed_time']:.2f}s")
    
    # Display goals
    for i, goal in enumerate(results['goals'], 1):
        st.markdown(f"""
        <div class="goal-card">
            <h5>🎯 Goal {i}</h5>
            <p>{goal.get('description', 'No description available')}</p>
        </div>
        """, unsafe_allow_html=True)


     # Display goals as JSON
    st.subheader("🧾 SMART Goals (JSON Format)")
    try:
        json_display = {
            "smart_goals": results["goals"]
        }
        st.code(json.dumps(json_display, indent=2), language="json")
        
        # Download JSON button
        goals_json = json.dumps(json_display, indent=2)
        st.download_button(
            label="💾 Download as JSON",
            data=goals_json,
            file_name=f"smart_goals_{results['file_name']}.json",
            mime="application/json"
        )
        
    except Exception as e:
        st.error(f"Error displaying goals as JSON: {e}")



    
    # # TEMPORARY DEBUG: Display HTTP response details
    # if st.session_state.get("debug_response"):
    #     with st.expander("🔧 Debug: HTTP Response Details", expanded=False):
    #         debug_resp = st.session_state["debug_response"]
            
    #         col1, col2 = st.columns(2)
    #         with col1:
    #             st.metric("Status Code", debug_resp.get('status_code', 'Unknown'))
    #         with col2:
    #             st.metric("Content Type", debug_resp.get('content_type', 'Unknown'))
            
    #         st.subheader("Response Headers")
    #         st.json(debug_resp.get('headers', {}))
            
    #         st.subheader("Raw Response Content")
    #         raw_content = debug_resp.get('raw_content', 'No content available')
            
    #         # Try to format as JSON if it looks like JSON
    #         try:
    #             if raw_content.strip().startswith('{'):
    #                 formatted_json = json.loads(raw_content)
    #                 st.json(formatted_json)
    #             else:
    #                 st.code(raw_content, language='text')
    #         except json.JSONDecodeError:
    #             st.code(raw_content, language='text')
            
    #         # Show what was extracted for goals
    #         st.subheader("Extracted Goals Data")
    #         st.json({"extracted_goals": results["goals"]})

    # Display evaluator result
    if 'evaluator_result' in results:
        evaluator_result = results['evaluator_result']
        st.subheader("📊 Evaluation Result")
        
        if isinstance(evaluator_result, dict) and 'error' in evaluator_result:
            st.warning(f"⚠️ Evaluator Error: {evaluator_result['error']}")
        else:
            # Parse evaluator result - it might be a JSON string
            try:
                if isinstance(evaluator_result, str):
                    # Try to parse as JSON string
                    parsed_evaluator = json.loads(evaluator_result)
                else:
                    parsed_evaluator = evaluator_result
                
                # Check if this is the expected evaluation format
                if isinstance(parsed_evaluator, dict) and 'scores' in parsed_evaluator:
                    # Display successful evaluation results with rich formatting
                    st.success("✅ Goals successfully evaluated by evaluator agent")
                    
                    # Summary metrics
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        eval_type = parsed_evaluator.get("evaluation_type", "smart_goals_rubric")
                        st.metric("Evaluation Type", eval_type.replace("_", " ").title())
                    with col2:
                        cases_scored = parsed_evaluator.get("cases_scored", len(parsed_evaluator.get("scores", [])))
                        st.metric("Goals Evaluated", cases_scored)
                    with col3:
                        # Calculate average score across all metrics
                        scores_data = parsed_evaluator.get("scores", [])
                        total_scores = 0
                        total_metrics = 0
                        for score in scores_data:
                            metric_scores = score.get("metric_scores", {})
                            for metric, value in metric_scores.items():
                                if isinstance(value, (int, float)):
                                    total_scores += value
                                    total_metrics += 1
                        avg_score = total_scores / total_metrics if total_metrics > 0 else 0
                        st.metric("Average Score", f"{avg_score:.2f}")
                    
                    # Detailed scores for each goal
                    st.subheader("📈 Detailed Goal Evaluation")
                    
                    for i, score_data in enumerate(scores_data, 1):
                        case_id = score_data.get("case_id", str(i))
                        with st.expander(f"🎯 Goal {case_id} Evaluation", expanded=True):
                            
                            # Display metric scores as progress bars
                            st.write("**SMART Criteria Scores:**")
                            metrics = score_data.get("metric_scores", {})
                            
                            if metrics:
                                col1, col2 = st.columns(2)
                                metric_items = list(metrics.items())
                                mid_point = len(metric_items) // 2
                                with col1:
                                    for metric, value in metric_items[:mid_point]:
                                        if isinstance(value, (int, float)):
                                            st.progress(float(value), text=f"{metric.replace('_', ' ').title()}: {value:.1f}")
                                
                                with col2:
                                    for metric, value in metric_items[mid_point:]:
                                        if isinstance(value, (int, float)):
                                            st.progress(float(value), text=f"{metric.replace('_', ' ').title()}: {value:.1f}")
                                
                                # Overall score for this goal
                                numeric_values = [v for v in metrics.values() if isinstance(v, (int, float))]
                                if numeric_values:
                                    goal_avg = sum(numeric_values) / len(numeric_values)
                                    st.metric("Overall Goal Score", f"{goal_avg:.2f}")
                            
                            # Notes and agreement
                            notes = score_data.get("notes", "")
                            agreement = score_data.get("agreement", "")
                            
                            if notes and notes != "n/a":
                                st.write("**Evaluator Notes:**")
                                st.info(notes)
                            
                            if agreement and agreement != "n/a":
                                st.write("**Agreement Level:**")
                                st.write(agreement)
                    
                    # Raw JSON display
                    with st.expander("🔍 View Raw Evaluation JSON"):
                        st.code(json.dumps(parsed_evaluator, indent=2), language="json")
                
                else:
                    # Fallback for other evaluation formats
                    st.success("✅ Goals successfully evaluated")
                    if isinstance(parsed_evaluator, dict):
                        for key, value in parsed_evaluator.items():
                            if key != 'error':
                                st.write(f"**{key.replace('_', ' ').title()}:** {value}")
                    else:
                        st.write(parsed_evaluator)
                        
            except json.JSONDecodeError as e:
                # If it's not valid JSON, display as text
                st.success("✅ Goals evaluated")
                st.write("**Evaluation Result:**")
                st.text(evaluator_result)
            except Exception as e:
                st.error(f"Error parsing evaluator result: {e}")
                st.write("**Raw Evaluator Result:**")
                st.text(str(evaluator_result))

    

    #     # TEST SECTION: Mock evaluator result for testing
    # st.subheader("🧪 Test: Mock Evaluator Result")
    
    # # Mock evaluator data
    # mock_evaluator_data = {
    #     "evaluation_type": "smart_goals_rubric",
    #     "cases_scored": 5,
    #     "scores": [
    #         {
    #             "case_id": "1",
    #             "metric_scores": {
    #                 "specific": 1.0,
    #                 "measurable": 1.0,
    #                 "achievable": 0.9,
    #                 "relevant": 1.0,
    #                 "time_bound": 1.0,
    #                 "clarity": 1.0
    #             },
    #             "agreement": "n/a",
    #             "notes": "Goal specifies exact carb targets (45g/meal), tracking method (food diary app), and review timeline (2 weeks)."
    #         },
    #         {
    #             "case_id": "2",
    #             "metric_scores": {
    #                 "specific": 1.0,
    #                 "measurable": 1.0,
    #                 "achievable": 0.9,
    #                 "relevant": 1.0,
    #                 "time_bound": 1.0,
    #                 "clarity": 1.0
    #             },
    #             "agreement": "n/a",
    #             "notes": "Goal clearly specifies activity duration (150/75 min), intensity levels, tracking method, and includes evaluation timeline."
    #         },
    #         {
    #             "case_id": "3",
    #             "metric_scores": {
    #                 "specific": 0.8,
    #                 "measurable": 0.7,
    #                 "achievable": 0.9,
    #                 "relevant": 1.0,
    #                 "time_bound": 0.8,
    #                 "clarity": 0.9
    #             },
    #             "agreement": "n/a",
    #             "notes": "Goal lacks specificity about exact medications/doses, though monitoring is clear. Could be more measurable with compliance targets."
    #         },
    #         {
    #             "case_id": "4",
    #             "metric_scores": {
    #                 "specific": 1.0,
    #                 "measurable": 1.0,
    #                 "achievable": 0.9,
    #                 "relevant": 1.0,
    #                 "time_bound": 0.9,
    #                 "clarity": 1.0
    #             },
    #             "agreement": "n/a",
    #             "notes": "Goal provides specific timing (before meals/bedtime), exact target ranges, and clear action steps for deviations."
    #         },
    #         {
    #             "case_id": "5",
    #             "metric_scores": {
    #                 "specific": 1.0,
    #                 "measurable": 1.0,
    #                 "achievable": 0.9,
    #                 "relevant": 1.0,
    #                 "time_bound": 0.9,
    #                 "clarity": 1.0
    #             },
    #             "agreement": "n/a",
    #             "notes": "Goal specifies exact weight loss target (0.5-1 lb/week), monitoring method (weekly weighing), and tracking approach."
    #         }
    #     ]
    # }
    
    # # Display mock evaluation in a more structured way
    # st.success("✅ Mock Evaluation Complete")
    
    # # Summary metrics
    # col1, col2, col3 = st.columns(3)
    # with col1:
    #     st.metric("Evaluation Type", mock_evaluator_data["evaluation_type"].replace("_", " ").title())
    # with col2:
    #     st.metric("Goals Evaluated", mock_evaluator_data["cases_scored"])
    # with col3:
    #     # Calculate average score across all metrics
    #     total_scores = 0
    #     total_metrics = 0
    #     for score in mock_evaluator_data["scores"]:
    #         for metric, value in score["metric_scores"].items():
    #             total_scores += value
    #             total_metrics += 1
    #     avg_score = total_scores / total_metrics if total_metrics > 0 else 0
    #     st.metric("Average Score", f"{avg_score:.2f}")
    
    # # Detailed scores for each goal
    # st.subheader("📈 Detailed Goal Evaluation")
    
    # for i, score_data in enumerate(mock_evaluator_data["scores"], 1):
    #     with st.expander(f"🎯 Goal {score_data['case_id']} Evaluation", expanded=True):
            
    #         # Display metric scores as progress bars
    #         st.write("**SMART Criteria Scores:**")
    #         metrics = score_data["metric_scores"]
            
    #         col1, col2 = st.columns(2)
    #         with col1:
    #             st.progress(metrics["specific"], text=f"Specific: {metrics['specific']:.1f}")
    #             st.progress(metrics["measurable"], text=f"Measurable: {metrics['measurable']:.1f}")
    #             st.progress(metrics["achievable"], text=f"Achievable: {metrics['achievable']:.1f}")
            
    #         with col2:
    #             st.progress(metrics["relevant"], text=f"Relevant: {metrics['relevant']:.1f}")
    #             st.progress(metrics["time_bound"], text=f"Time-bound: {metrics['time_bound']:.1f}")
    #             st.progress(metrics["clarity"], text=f"Clarity: {metrics['clarity']:.1f}")
            
    #         # Overall score for this goal
    #         goal_avg = sum(metrics.values()) / len(metrics)
    #         st.metric("Overall Goal Score", f"{goal_avg:.2f}")
            
    #         # Notes
    #         if score_data["notes"]:
    #             st.write("**Evaluator Notes:**")
    #             st.info(score_data["notes"])
    
    # # Raw JSON display
    # with st.expander("🔍 View Raw Evaluation JSON"):
    #     st.code(json.dumps(mock_evaluator_data, indent=2), language="json")

    # Action buttons
    col1, col2, col3 = st.columns([2, 1, 1])
    with col3:
        if st.button("🔄 Generate New Goals", type="primary"):
            st.session_state["generated_goals"] = None
            st.rerun()

    
    st.markdown('</div>', unsafe_allow_html=True)

elif not st.session_state.get("processing", False):
    # Instructions when no goals generated

    st.markdown("""
    ### 📋 How to Generate SMART Goals
    
    1. **Select an AI Model:** Choose the most appropriate model for your needs
    2. **Upload Patient Summary:** Upload a PDF, DOCX, or TXT file containing patient information
    3. **Generate Goals:** Click the "Generate SMART Goals" button to create evidence-based goals
    
    ### 💡 Tips for Best Results
    
    - Ensure patient summaries include relevant medical history, current conditions, and treatment goals
    - Generated goals follow SMART criteria: Specific, Measurable, Achievable, Relevant, Time-bound
    """)



st.markdown('</div>', unsafe_allow_html=True)

