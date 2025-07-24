# ai_utils.py

import os
from openai import AzureOpenAI
import yaml
from dotenv import load_dotenv
import json
import re
import logging
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Any, Optional, Union

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



def generate_model_with_llm(context: dict) -> str:
    """Generates C# code for a model class."""
    prompt = prompts['generate_model'].format(context=json.dumps(context, indent=2))
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

def generate_controller_with_llm(context: dict, rag_context: str) -> str:
    """Generates C# code for a controller class."""
    prompt = prompts['generate_controller'].format(
        context=json.dumps(context, indent=2),
        rag_context=rag_context
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

def generate_view_with_llm(context: dict) -> str:
    """Generates Razor .cshtml code for a view."""
    prompt = prompts['generate_view'].format(context=json.dumps(context, indent=2))
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

def generate_interface_with_llm(context: dict) -> str:
    """Generates C# code for an interface."""
    prompt = prompts['generate_interface'].format(context=json.dumps(context, indent=2))
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

def generate_service_with_llm(context: dict, rag_context: str) -> str:
    """Generates C# code for a service class."""
    prompt = prompts['generate_service'].format(
        context=json.dumps(context, indent=2),
        rag_context=rag_context
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content





# Pydantic models
# --- CORRECTLY ORDERED PYDANTIC MODELS ---
# Step 1: Define the "sub-models" FIRST.

class ModelProperty(BaseModel):
    name: str
    data_type: str = Field(alias="dataType")
    attributes: List[str] = Field(default=[])

class MethodParameter(BaseModel):
    data_type: str = Field(alias="dataType")
    name: str

class ControllerMethod(BaseModel):
    name: str
    return_type: str = Field(alias="returnType", default="IActionResult")
    parameters: List[MethodParameter] = Field(default=[])
    http_verb: str = Field(alias="httpVerb", default="GET")
    description: Optional[str] = None


# --- FIX for Error 2: Make UIComponent more flexible ---
class UIComponentProperties(BaseModel):
    """Handles the nested properties dictionary the AI is now sending."""
    label: Optional[str] = None
    name: Optional[str] = None
    onclick: Optional[str] = None
    type: Optional[str] = None # For things like <input type="password">
    value: Optional[str] = None

class UIComponent(BaseModel):
    """
    A highly flexible model that can handle multiple structures the AI might produce.
    """
    # Accept both 'componentType' from our prompt and 'type' which the AI seems to prefer.
    component_type: Optional[str] = Field(default=None, alias="componentType")
    type: Optional[str] = None 
    
    # Handle the nested properties structure.
    properties: Optional[UIComponentProperties] = None
    
    # Keep the old top-level fields for backwards compatibility or if the AI uses them.
    label: Optional[str] = None
    binds_to: Optional[str] = Field(default=None, alias="bindsTo")
    attributes: List[Any] = Field(default=[]) # Make attributes very flexible

# Original models (FileInfo, AnalysisSummary)
class FileInfo(BaseModel):
    file_name: Optional[str] = Field(default=None, alias="file")
    purpose: str
    functionality: str
    dependencies: List[str] = Field(default=[])
    net_mapping: Optional[Dict[str, Optional[str]]] = Field(default={}, alias="netMappings")
    controls: List[str] = Field(default=[], description="UI controls")
    events: List[str] = Field(default=[], description="Events")
    ado_queries: List[str] = Field(default=[], description="ADO queries", alias="adoQueries")

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class AnalysisSummary(BaseModel):
    files: List[FileInfo]
    overall_purpose: Optional[str] = Field(default="Generated summary", description="Overall project purpose")
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)



class AnalysisInput(BaseModel):
    vb6_project_path: str
    vb6_project_path: str

class TargetFile(BaseModel):
    file_path: str = Field(alias="filePath")
    type: str
    namespace: Optional[str] = None
    dependencies: List[str] = Field(default=[])
    
    properties: Optional[List[ModelProperty]] = Field(default=None)
    methods: Optional[List[ControllerMethod]] = Field(default=None)
    ui_components: Optional[List[UIComponent]] = Field(default=None, alias="uiComponents")

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class TargetArchitecture(BaseModel):
    project_name: str = Field(alias="projectName", default="MigratedApp")
    files: List[TargetFile]
    customizations: Dict[str, Any] = Field(default={})
    ef_core_context: Optional[str] = Field(default=None, alias="efCoreContext")

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)
    project_name: str = Field(alias="projectName", default="MigratedApp")
    files: List[TargetFile]
    customizations: Dict[str, Any] = Field(default={})
    ef_core_context: Optional[str] = Field(default=None, alias="efCoreContext")

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)