
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
logger = logging.getLogger(__name__) 
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

# Validate environment variables (Ensure these are set in your .env file)
if not all([endpoint, api_key, embedding_endpoint, embedding_deployment, embedding_api_version, embedding_model]):
    raise ValueError("One or more required Azure environment variables are missing.")

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

def clean_and_parse_json(raw_content: str) -> dict:
    """A robust function to extract and parse JSON from LLM responses."""
    logging.info(f"Raw LLM content for parsing: {raw_content}")
    
    # Attempt to find JSON within code fences
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_content, re.MULTILINE)
    if match:
        content_to_parse = match.group(1).strip()
    else:
        # If no fences, find the first '{' and last '}'
        start = raw_content.find('{')
        end = raw_content.rfind('}') + 1
        if start != -1 and end != 0:
            content_to_parse = raw_content[start:end].strip()
        else:
            content_to_parse = raw_content.strip()

    logging.info(f"Cleaned content for JSON parsing: {content_to_parse}")
    try:
        return json.loads(content_to_parse)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse JSON: {e}. Content was: {content_to_parse}")
        raise ValueError(f"Failed to parse LLM JSON response. Raw content was: {raw_content}")

def propose_architecture_with_llm(summary: dict) -> dict:
    prompt = prompts['propose_architecture'].format(summary=json.dumps(summary, indent=2))
    logger.info("="*20 + " PROPOSING ARCHITECTURE " + "="*20)
    logger.info(f"Sending prompt for architecture proposal. Prompt length: {len(prompt)} characters.")
    logger.debug(f"Architecture Prompt:\n{prompt}")
    logger.info("="*68)
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a .NET 8 Worker Service architect. Respond with a single, valid JSON object."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    raw_content = response.choices[0].message.content
    logger.info(f"Received architecture proposal from LLM. Content length: {len(raw_content)} characters.")
    # Since we use json_object mode, direct parsing should work.
    return json.loads(raw_content)

def analyze_single_vb6_file_with_llm(file_data: dict, schema: dict) -> dict:
    prompt = prompts['analyze_vb6_single_file'].format(
        file_data=json.dumps(file_data, indent=2),
        schema=json.dumps(schema, indent=2)
    )

    logger.info("-" * 20 + f" ANALYZING FILE: {file_data.get('file')} " + "-" * 20)
    logger.info(f"Sending prompt for file analysis. Prompt length: {len(prompt)} characters.")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a VB6 to .NET expert. Return a single, valid JSON object with your analysis."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
    )
    raw_content = response.choices[0].message.content
    logger.info(f"LLM analysis for file '{file_data.get('file')}' received. Content length: {len(raw_content)} characters.")
    logger.info(f"Raw Analysis JSON:\n{raw_content}")
    logger.info("-" * (42 + len(file_data.get('file'))))
    return json.loads(raw_content)

def refine_with_llm(files: dict, errors: list):
    prompt = prompts['refine_code'].format(
        files=json.dumps(files, indent=2),
        errors="\n".join(errors)
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Refine .NET code to fix build errors. Respond in valid JSON format."},
            {"role": "user", "content": prompt}
        ]
    )
    raw_content = response.choices[0].message.content
    return clean_and_parse_json(raw_content)

# --- NEW AND REFACTORED GENERATORS ---

def generate_model_with_llm(context: dict) -> str:
    """Generates C# code for a model class."""
    prompt = prompts['generate_model'].format(context=json.dumps(context, indent=2))
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

def generate_worker_with_llm(context: dict, rag_context: str) -> str:
    """Generates C# code for a BackgroundService worker class."""
    prompt = prompts['generate_worker'].format(
        context=json.dumps(context, indent=2),
        rag_context=rag_context
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


def summarize_vb6_code_with_llm(code: str) -> str:
    """
    Takes a string of VB6 code and returns a concise summary of its purpose,
    key functions, and important logic.
    """
    logging.info(f"Summarizing VB6 code of length {len(code)}...")
    prompt = f"""
    You are an expert VB6 analyst. Summarize the following VB6 code. Focus on:
    1. The overall purpose of the code.
    2. Key public functions and subroutines and what they do.
    3. Any database interactions (ADO queries).
    4. Any important UI elements or timer controls mentioned.
    5. Any Win32 API declarations (`Declare Function`).

    Do not provide a line-by-line explanation. Provide a high-level summary.

    VB6 Code:
    ```vb
    {code}
    ```
    """
    
    # --- LOGGING ADDED ---
    logger.info("-" * 20 + " SUMMARIZING LARGE FILE " + "-" * 20)
    logger.info(f"Code length: {len(code)} characters. Prompt length: {len(prompt)} characters.")
    # --- END LOGGING ---

    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Or a cheaper/faster model like gpt-3.5-turbo if available
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1, # Low temperature for factual summarization
        )
        summary = response.choices[0].message.content
        logger.info(f"Generated summary. Length: {len(summary)} characters.")
        logger.info("-" * 62)        
        return summary
    except Exception as e:
        logging.error(f"Failed to summarize VB6 code: {e}")
        # Return a simple message indicating failure, so the process can continue
        return "Error: Could not summarize code."


# ---------------------------------------------------
# --- PYDANTIC MODELS FOR WINDOWS SERVICE TARGET ---
# ---------------------------------------------------

class AnalysisInput(BaseModel):
    # This model is now defined in main.py, keeping it here for reference is fine
    # but the primary one will be in main.py
    vb6_project_path: Optional[str] = None

class FileInfo(BaseModel):
    file_name: Optional[str] = Field(default=None, alias="file")
    purpose: str
    functionality: str
    dependencies: List[str] = Field(default=[])
    net_mapping: Optional[Dict[str, Optional[str]]] = Field(default={}, alias="netMappings")
    controls: List[str] = Field(default=[], description="UI controls (useful for inferring timers)")
    events: List[str] = Field(default=[], description="Events (useful for inferring timers)")
    ado_queries: List[str] = Field(default=[], description="ADO queries", alias="adoQueries")
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class AnalysisSummary(BaseModel):
    files: List[FileInfo]
    overall_purpose: Optional[str] = Field(default="Generated summary", description="Overall project purpose")
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class ModelProperty(BaseModel):
    name: str
    data_type: str = Field(alias="dataType")
    attributes: List[str] = Field(default=[])

class MethodParameter(BaseModel):
    # This allows the field to be populated from JSON keys "dataType" OR "type"
    data_type: str = Field(alias="type", validation_alias="dataType") 
    name: str

class ServiceMethod(BaseModel):
    name: str
    # Make return_type optional and give it a default value
    return_type: Optional[str] = Field(alias="returnType", default="void")
    # This Union allows the list to contain either a MethodParameter object or a string
    parameters: List[Union[MethodParameter, str]] = Field(default=[])
class TargetFile(BaseModel):
    file_path: str = Field(alias="filePath")
    type: str  # e.g., "worker", "service", "model", "interface", "program", "csproj"
    namespace: Optional[str] = None
    dependencies: List[str] = Field(default=[])
    description: Optional[str] = None # For workers

    # Type-specific properties
    properties: Optional[List[ModelProperty]] = None # For models
    methods: Optional[List[ServiceMethod]] = None # For services/interfaces

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class TargetArchitecture(BaseModel):
    project_name: str = Field(alias="projectName", default="MigratedWindowsService")
    files: List[TargetFile]
    customizations: Dict[str, Any] = Field(default={})

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)