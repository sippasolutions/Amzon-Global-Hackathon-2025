#from utils.strands_sagemaker import SageMakerAIModel
from strands.models.bedrock import BedrockModel

# Import Required Libraries
import os, io
from strands import Agent, tool
from strands_tools import http_request 
import json, time, uuid, re, requests, mimetypes
from typing import Tuple, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from PyPDF2 import PdfReader
from docx import Document

os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
boto3.setup_default_session(region_name="us-east-1")

#### Check support for tools and system prompt
def model_supports_system_prompt(model_id: str) -> bool:
    """Check if a model supports system prompts"""
    models = [
        "mistral.mistral-7b-instruct-v0:2",
    ]
    return model_id not in models


def model_supports_tools(model_id: str) -> bool:
    """Check if a model supports tool use"""
    # models on Bedrock don't support tools
    models = [
        "mistral.mistral-7b-instruct-v0:2",
        "meta.llama3-70b-instruct-v1:0",
    ]
    return model_id not in models


################ Set up system prompt ####################
# ===== analyzer prompt (with multi-shot style prompts integrated) =====
def get_analyzer_prompt(data_source: str, raw_text: str = "", formatted_text: str = "") -> str:
    """
    Build the analyzer prompt with multi-shot style instructions.
    If raw_text and formatted_text are available, they are injected into the multi-shot instructions.
    """

# Multi-shot style prompts
    prompt1 = f"Develop behavioral intervention actionable goals from the following content:\n\n{data_source}\n\n"
    prompt2 = f"Derive SMART goals that are specific, measurable, actionable, relevant, and time-bounded from the following content:\n\n{data_source}\n\n"
    prompt3 = f"Generate multiple SMART goals across domains (diet, activity, medication, monitoring, etc.) if the content allows:\n\n{data_source}\n\n"
    #prompt2 = f"Derive SMART goals that are specific, measurable, actionable, relevant, and time-bounded from the following content:\n\n{formatted_text}\n\n"
    #prompt3 = f"Generate multiple SMART goals across domains (diet, activity, medication, monitoring, etc.) if the content allows:\n\n{formatted_text}\n\n"

# Combine prompts into a single meta-instruction
    multi_shot_prompt = (
        "You are a diabetes health coach. Read the following instructions and then generate SMART goals from the provided content. "
        "Do not force a fixed number—produce as many SMART goals as are relevant, based on the text.\n\n"
        f"Instruction 1:\n{prompt1}\n\n"
        f"Instruction 2:\n{prompt2}\n\n"
        f"Instruction 3:\n{prompt3}\n\n"
        "Final Task: Generate structured SMART goals, grouped by domain if possible. "
        "If the document only supports 1 or 2 goals, output only those."
    )

    return f"""You are an Analyzer Agent. I will provide you with a data source and you need to analyze it.

Tool available:
- fetch_data(data_source) -> {{raw_text, formatted_text, meta}}

INSTRUCTIONS:
1) Call fetch_data EXACTLY ONCE with the data_source: "{data_source}"
2) Use "formatted_text" as your working input. It is newline-separated if the source used '@' row delimiters; otherwise it may be free text/paragraphs.
3) Perform the analysis according to the TASK below.
4) Produce output that matches the OUTPUT CONTRACT below EXACTLY (keys and structure). Output ONLY that JSON object and nothing else.
5) Do not call any other tools. Do not print anything except the final JSON. Do not retry fetch_data.

TASK:
{multi_shot_prompt}

OUTPUT CONTRACT:
{{
  "smart_goals": [
    {{
      "goal_number": "integer (starts at 1 and increments for each goal)",
      "description": "string (time-bound, measurable details)"
    }}
  ]
}}

Data source to analyze: {data_source}"""
