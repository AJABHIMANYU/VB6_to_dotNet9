# ai_utils.py

import os
from openai import AzureOpenAI
import yaml
from dotenv import load_dotenv
import json
import re
import logging
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)

# Load .env for credentials
load_dotenv()

# Load prompts.yml
with open('prompts.yml', 'r') as f:
    prompts = yaml.safe_load(f)

# Access environment variables with validation
endpoint = os.getenv("AZURE_ENDPOINT", "").strip()
api_key = os.getenv("AZURE_API_KEY", "").strip()
embedding_endpoint = os.getenv("AZURE_EMBEDDING_ENDPOINT", "").strip()
embedding_deployment = os.getenv("AZURE_EMBEDDING_DEPLOYMENT_NAME", "").strip()
embedding_api_version = os.getenv("AZURE_EMBEDDING_API_VERSION", "").strip()
embedding_model = os.getenv("AZURE_EMBEDDING_MODEL_NAME", "").strip()

# Validate environment variables
if not endpoint or not endpoint.startswith("https://"):
    logging.error(f"Invalid AZURE_ENDPOINT: '{endpoint}'. Must start with 'https://' and be non-empty.")
    raise ValueError("AZURE_ENDPOINT is missing or invalid")
if not api_key:
    logging.error("AZURE_API_KEY is missing.")
    raise ValueError("AZURE_API_KEY is missing")
if not embedding_endpoint or not embedding_endpoint.startswith("https://"):
    logging.error(f"Invalid AZURE_EMBEDDING_ENDPOINT: '{embedding_endpoint}'. Must start with 'https://' and be non-empty.")
    raise ValueError("AZURE_EMBEDDING_ENDPOINT is missing or invalid")
if not embedding_api_version:
    logging.error("AZURE_EMBEDDING_API_VERSION is missing.")
    raise ValueError("AZURE_EMBEDDING_API_VERSION is missing")
if not embedding_model:
    logging.error("AZURE_EMBEDDING_MODEL_NAME is missing.")
    raise ValueError("AZURE_EMBEDDING_MODEL_NAME is missing")

# Initialize clients
client = AzureOpenAI(
    azure_endpoint=endpoint.rstrip('/'),
    api_key=api_key,
    api_version="2024-08-01-preview"
)

embedding_client = AzureOpenAI(
    azure_endpoint=embedding_endpoint.rstrip('/'),
    api_key=api_key,
    api_version=embedding_api_version
)

def generate_embedding(text):
    try:
        response = embedding_client.embeddings.create(
            model=embedding_model,
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logging.error(f"Failed to generate embedding: {e}")
        raise

def propose_architecture_with_llm(summary: dict) -> dict:
    prompt = prompts['propose_architecture'].format(
        summary=summary,
        examples="Example: Map form to Controller.cs and View.cshtml; include auth if login detected."
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Propose .NET 9 MVC structure in JSON."},
            {"role": "user", "content": prompt}
        ]
    )
    raw_content = response.choices[0].message.content
    logging.info(f"Raw LLM content: {raw_content}")
    
    # Extract JSON content between code fences, handling optional 'json' label
    match = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n```', raw_content, re.MULTILINE)
    if match:
        cleaned_content = match.group(1).strip()
    else:
        cleaned_content = raw_content.strip()
        logging.warning("No code fences found in LLM response; using raw content")
    
    logging.info(f"Cleaned content: {cleaned_content}")
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse LLM response: {e} - Cleaned content: {cleaned_content}")
        # Attempt to extract valid JSON subset
        try:
            start = cleaned_content.find('{')
            end = cleaned_content.rfind('}') + 1
            if start != -1 and end != -1:
                subset = cleaned_content[start:end]
                return json.loads(subset)
            else:
                raise ValueError(f"No valid JSON found in response: {cleaned_content}")
        except json.JSONDecodeError as e2:
            raise ValueError(f"Failed to parse JSON subset: {e2} - Cleaned content: {cleaned_content} - Raw: {raw_content}")

def analyze_single_vb6_file_with_llm(file_data: dict, schema: dict) -> dict:
    """Analyzes a single VB6 file's data using an LLM to avoid token limits."""
    
    # We remove the 'content' from the main display in the prompt for brevity,
    # but the LLM still gets it as part of the file_data object.
    # A more advanced version might summarize the content if it's too long.
    prompt = prompts['analyze_vb6_single_file'].format(
        file_data=json.dumps(file_data, indent=2),
        schema=json.dumps(schema, indent=2)
    )
    
    response = client.chat.completions.create(
        model="gpt-4o", # Or whichever model you are using
        messages=[
            {"role": "system", "content": "You are a VB6 to .NET expert. You will receive data for a single VB6 file and must return a single, valid JSON object with its analysis."},
            {"role": "user", "content": prompt}
        ],
        # It's good practice to ask the model to respond in JSON mode if the API supports it
        response_format={"type": "json_object"},
    )
    
    raw_content = response.choices[0].message.content
    logging.info(f"LLM analysis for file '{file_data.get('file')}':\n{raw_content}")
    
    try:
        # Since we are using response_format="json_object", the content should be a valid JSON string
        return json.loads(raw_content)
    except json.JSONDecodeError as e:
        # Fallback for older models or if JSON mode fails
        logging.error(f"Failed to parse LLM JSON response for file '{file_data.get('file')}': {e}. Content: {raw_content}")
        # Add your existing regex/cleanup logic here if needed as a fallback
        match = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n```', raw_content, re.MULTILINE)
        if match:
            cleaned_content = match.group(1).strip()
            return json.loads(cleaned_content)
        raise ValueError(f"Could not extract valid JSON for file '{file_data.get('file')}'.")

def infer_schema_with_llm(ado_queries: list) -> dict:
    prompt = prompts['infer_schema'].format(
        ado_queries=ado_queries,
        examples="Example: From 'SELECT * FROM Users', infer table Users with columns Id, Name."
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "Infer MySQL schema from ADO queries in JSON."}, {"role": "user", "content": prompt}]
    )
    raw_content = response.choices[0].message.content
    logging.info(f"Raw LLM content: {raw_content}")
    
    match = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n```', raw_content, re.MULTILINE)
    if match:
        cleaned_content = match.group(1).strip()
    else:
        cleaned_content = raw_content.strip()
        logging.warning("No code fences found in LLM response; using raw content")
    
    logging.info(f"Cleaned content: {cleaned_content}")
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response: {e} - Cleaned content: {cleaned_content} - Raw: {raw_content}")

def generate_file_with_llm(file_type: str, context: dict):
    prompt = prompts['generate_file'].format(
        file_type=file_type,
        context=context,
        examples="Example: Convert VB6 form to .cshtml with Razor syntax."
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "Generate .NET 9 code in strict format."}, {"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

def refine_with_llm(files: dict, errors: list):
    prompt = prompts['refine_code'].format(
        files=files,
        errors=errors,
        examples="Fix build error: Adjust namespace in Controller.cs."
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "Refine .NET code to fix errors."}, {"role": "user", "content": prompt}]
    )
    raw_content = response.choices[0].message.content
    logging.info(f"Raw LLM content: {raw_content}")
    
    match = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n```', raw_content, re.MULTILINE)
    if match:
        cleaned_content = match.group(1).strip()
    else:
        cleaned_content = raw_content.strip()
        logging.warning("No code fences found in LLM response; using raw content")
    
    logging.info(f"Cleaned content: {cleaned_content}")
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response: {e} - Cleaned content: {cleaned_content} - Raw: {raw_content}")

# Pydantic models
class FileInfo(BaseModel):
    file_name: Optional[str] = Field(default=None, alias="file")
    purpose: str
    functionality: str
    dependencies: List[str]
    # CHANGE THIS LINE to allow for string or None values
    net_mapping: Optional[Dict[str, Optional[str]]] = Field(default={}, alias="netMappings")
    controls: List[str] = Field(default=[], description="UI controls")
    events: List[str] = Field(default=[], description="Events")
    ado_queries: List[str] = Field(default=[], description="ADO queries", alias="adoQueries")
    
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class AnalysisSummary(BaseModel):
    files: List[FileInfo]
    overall_purpose: Optional[str] = Field(default="Generated summary", description="Overall project purpose")

    model_config = ConfigDict(arbitrary_types_allowed=True)

class TargetFile(BaseModel):
    file_path: str
    type: str
    namespace: str
    # Make dependencies optional and default to an empty list if missing
    dependencies: List[str] = Field(default=[])

    model_config = ConfigDict(arbitrary_types_allowed=True)

class TargetArchitecture(BaseModel):
    files: List[TargetFile]
    customizations: Dict[str, bool]
    ef_core_context: str

    model_config = ConfigDict(arbitrary_types_allowed=True)

class AnalysisInput(BaseModel):
    vb6_project_path: str  # Can be a local path or GitHub URL
 