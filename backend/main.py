# main.py
import json
import logging
import os
from typing import Dict, Optional
import uuid
import tempfile
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from openai import AzureOpenAI
from pydantic import BaseModel
import git
import uvicorn
from utils import validate_git_url, secure_temp_dir, parse_vb6_project, build_dependency_graph, validate_code, package_as_zip
from ai_utils import AnalysisInput, analyze_single_vb6_file_with_llm,  propose_architecture_with_llm, AnalysisSummary, TargetArchitecture, summarize_vb6_code_with_llm
from database import retrieve_analysis, store_analysis
from unified_rag import index_in_rag
from react_agent import react_agent_generate_files
from ai_utils import refine_with_llm
from unified_rag import UnifiedRagService
from database import retrieve_analysis, store_analysis
import logging.handlers
import sys

# --- ADD THIS ENTIRE BLOCK FOR BETTER LOGGING ---
# Create a logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create handlers
# A handler to write to the console (your terminal)
c_handler = logging.StreamHandler(sys.stdout)
# A handler to write to a file
f_handler = logging.FileHandler('logs/migration_activity.log')
c_handler.setLevel(logging.INFO)
f_handler.setLevel(logging.INFO)

# Create formatters and add it to handlers
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
c_handler.setFormatter(log_format)
f_handler.setFormatter(log_format)

# Add handlers to the logger
logger.addHandler(c_handler)
logger.addHandler(f_handler)


app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.mount("/static", StaticFiles(directory="."), name="static")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow your frontend origin or all for testing
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods, including OPTIONS
    allow_headers=["*"],  # Allow all headers
)

class AnalyzeInput(BaseModel):
    git_repo_url: str
    mysql_conn_details: dict = None  # e.g., {"host": "...", "user": "...", etc.}

@app.post("/analyze")
async def analyze(
    vb6_project_path: Optional[str] = Form(None), 
    uploaded_file: Optional[UploadFile] = File(None)
):
    if not vb6_project_path and not uploaded_file:
        raise HTTPException(status_code=400, detail="Either 'vb6_project_path' or an uploaded file must be provided.")
    if vb6_project_path and uploaded_file:
        raise HTTPException(status_code=400, detail="Provide either 'vb6_project_path' or an uploaded file, not both.")
        
    try:
        logger.info(f"Received analysis request. Path: {vb6_project_path}, File: {uploaded_file.filename if uploaded_file else 'None'}")
        # Pass arguments to the updated parser
        parsed_data, ado_queries, classes, dep_graph = parse_vb6_project(
            vb6_project_path=vb6_project_path, 
            uploaded_file=uploaded_file
        )
        logger.info(f"Completed parsing VB6 project with {len(parsed_data)} files.")
        # The rest of the function remains the same as before...
        schema = {} # analyze_schema(ado_queries=ado_queries, classes=classes) # Temporarily disable for speed if needed

        logger.info("Starting individual file analysis with LLM...")
        analyzed_files_data = []
        # Define a character limit. 15000 chars is ~4000-5000 tokens, a safe limit.
        CHARACTER_LIMIT_FOR_FULL_ANALYSIS = 15000

        for file_item in parsed_data:
            file_name = file_item.get('file')
            content = file_item.get('content', '')
            
            analysis_input_data = {
                'file': file_name,
                'win32_declarations': file_item.get('win32_declarations', [])
            }

            # --- THIS IS THE CRITICAL LOGIC ---
            if len(content) > CHARACTER_LIMIT_FOR_FULL_ANALYSIS:
                logger.warning(f"File '{file_name}' is too long ({len(content)} chars). Summarizing before analysis.")                # Summarize the code because it's too long
                summary_of_content = summarize_vb6_code_with_llm(content)
                # Use the shorter summary INSTEAD of the full content
                analysis_input_data['content'] = f"[[CONTENT WAS SUMMARIZED DUE TO LENGTH]]\n\n{summary_of_content}"
            else:
                # The content is short enough, pass it directly
                analysis_input_data['content'] = content
                
            # --- END OF CRITICAL LOGIC ---
            logger.info(f"Analyzing file: {file_name}...")
            
            try:
                analysis_result = analyze_single_vb6_file_with_llm(file_data=analysis_input_data, schema=schema)
                analyzed_files_data.append(analysis_result)
            except Exception as e:
                logger.error(f"Could not analyze file {file_name}. Error: {e}. Skipping this file.")                
                continue

        full_summary_data = {"files": analyzed_files_data, "overall_purpose": "Generated from file-by-file analysis"}
        validated_summary = AnalysisSummary(**full_summary_data)
        
        # --- CRITICAL FIX: Create a "lean" summary for the architect LLM ---
        logger.info("Creating a lean summary for architecture proposal to avoid token limits...")        
        lean_summary_files = []
        for file_analysis in validated_summary.model_dump().get('files', []):
            lean_file_info = {
                "file": file_analysis.get("file_name"),
                "purpose": file_analysis.get("purpose"),
                # We only include controls that are timers, as they are key for Windows Services
                "timers_found": [ctrl for ctrl in file_analysis.get("controls", []) if "timer" in ctrl.lower()],
                "ado_queries_count": len(file_analysis.get("ado_queries", [])),
                # This is important for identifying dependencies
                "dependencies": file_analysis.get("dependencies", [])
            }
            lean_summary_files.append(lean_file_info)

        lean_summary = {
            "overall_purpose": validated_summary.overall_purpose,
            "files": lean_summary_files
        }
        logger.info(f"Lean summary created. Sending to architect LLM:\n{json.dumps(lean_summary, indent=2)}")
        # --- END OF CRITICAL FIX ---

        # Now, call the architect with the SMALLER lean_summary
        validated_architecture = TargetArchitecture(**propose_architecture_with_llm(lean_summary))
        
        analysis_id = str(uuid.uuid4())

        
        logger.info(f"Storing analysis results for ID: {analysis_id}")
        store_analysis(analysis_id, validated_summary.model_dump(), validated_architecture.model_dump())
        
        logger.info("Indexing data in RAG service...")
        index_in_rag(analysis_id, validated_summary.model_dump(), validated_architecture.model_dump(), parsed_data)

        # Return the architecture as well for immediate review in the frontend
        return {"analysis_id": analysis_id, "proposed_architecture": validated_architecture.model_dump()}

    except Exception as e:
        logger.error(f"Error in /analyze endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

class MigrateInput(BaseModel):
    analysis_id: str
    # This change explicitly allows the input to be a dictionary OR None (null)
    modified_architecture: Optional[Dict] = None



# @app.post("/migrate")
# def migrate(input: MigrateInput):
#     try:
#         logging.info("="*50)
#         logging.info(f"MIGRATION STARTED for Analysis ID: {input.analysis_id}")
        
#         # Step 1: Retrieve analysis and architecture
#         logging.info("Retrieving analysis and architecture from database...")
#         analysis, architecture = retrieve_analysis(input.analysis_id)
#         if not analysis:
#             logging.error(f"Analysis ID not found: {input.analysis_id}")
#             raise HTTPException(status_code=404, detail="Analysis ID not found")
#         logging.info("Successfully retrieved data.")

#         if input.modified_architecture:
#             logging.info("User has provided a modified architecture. Overriding the original.")
#             architecture = input.modified_architecture

#         # Step 2: Initialize RAG and File Cache
#         logging.info("Initializing services (RAG, FileCache)...")
#         rag_service = UnifiedRagService()
        
#         # This part requires a bit of thought: where is the VB6 source code now?
#         # It was deleted after the analysis. For a real system, you'd keep it.
#         # For now, let's simulate by creating an empty cache.
#         from fcache.cache import FileCache
#         file_cache = FileCache('vb6_source_cache', flag='cs')
#         file_cache.clear() # Ensure cache is empty for this run
#         logging.warning("VB6 source file cache is simulated/empty for migration phase. RAG will rely on indexed data.")

#         # Step 3: Use ReAct agent for file generation
#         logging.info("Invoking ReAct agent to generate files...")
#         generated_files = react_agent_generate_files(analysis, architecture, rag_service, file_cache)
#         logging.info(f"ReAct agent generated {len(generated_files)} files.")

#         # Step 4: Validate generated code
#         logging.info("Validating generated .NET code with 'dotnet build'...")
#         validation_result = validate_code(generated_files)
        
#         if not validation_result["success"]:
#             logging.warning("Initial code validation failed. Starting refinement loop...")
#             # Refine with LLM (up to 3 retries)
#             for i in range(3):
#                 logging.info(f"Refinement attempt #{i + 1}...")
#                 generated_files = refine_with_llm(generated_files, validation_result["errors"])
#                 logging.info("Re-validating refined code...")
#                 validation_result = validate_code(generated_files)
#                 if validation_result["success"]:
#                     logging.info("Code validation successful after refinement!")
#                     break
#             else:
#                 logging.error("Code validation failed after 3 refinement retries.")
#                 raise HTTPException(status_code=500, detail=f"Code validation failed after retries. Last errors: {validation_result['errors']}")
#         else:
#             logging.info("Code validation successful on the first attempt!")

#         # Step 5: Package as ZIP
#         logging.info("Packaging final code into a ZIP file...")
#         zip_path = package_as_zip(generated_files)
#         logging.info(f"Code packaged successfully at: {zip_path}")
        
#         logging.info(f"MIGRATION COMPLETED for Analysis ID: {input.analysis_id}")
#         logging.info("="*50)
#         return {"zip_path": zip_path, "status": "Migration complete"}

#     except Exception as e:
#         logging.error(f"An unhandled error occurred in the /migrate endpoint: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=str(e))

@app.post("/migrate")
def migrate(input: MigrateInput):
    try:
        logging.info("="*50)
        logging.info(f"MIGRATION STARTED for Analysis ID: {input.analysis_id}")
        
        # Step 1: Retrieve analysis and architecture
        logging.info("Retrieving analysis and architecture from database...")
        analysis, architecture = retrieve_analysis(input.analysis_id)
        if not analysis:
            logging.error(f"Analysis ID not found: {input.analysis_id}")
            raise HTTPException(status_code=404, detail="Analysis ID not found")
        logging.info("Successfully retrieved data.")

        if input.modified_architecture:
            logging.info("User has provided a modified architecture. Overriding the original.")
            architecture = input.modified_architecture

        # Step 2: Initialize RAG and File Cache
        logging.info("Initializing services (RAG, FileCache)...")
        rag_service = UnifiedRagService()
        from fcache.cache import FileCache
        file_cache = FileCache('vb6_source_cache', flag='cs')
        file_cache.clear()
        logging.warning("VB6 source file cache is simulated/empty for migration phase.")

        # Step 3: Use ReAct agent for file generation
        logging.info("Invoking ReAct agent to generate files...")
        generated_files = react_agent_generate_files(analysis, architecture, rag_service, file_cache)
        logging.info(f"ReAct agent generated {len(generated_files)} files.")

        # --- BYPASS VALIDATION AND REFINEMENT ---
        logging.warning("SKIPPING code validation and refinement steps as requested.")
        # The entire validation_result and refinement loop is commented out or removed.
        # validation_result = validate_code(generated_files)
        # if not validation_result["success"]:
        #     ... refinement loop ...
        
        # Step 4: Go directly to packaging
        logging.info("Packaging generated files into a ZIP file...")
        zip_path = package_as_zip(generated_files)
        logging.info(f"Code packaged successfully at: {zip_path}")
        
        logging.info(f"MIGRATION COMPLETED for Analysis ID: {input.analysis_id}")
        logging.info("="*50)
        
        # Always return a success response with the zip path
        return {"zip_path": zip_path, "status": "Migration complete (code not validated)"}

    except Exception as e:
        logging.error(f"An unhandled error occurred in the /migrate endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)  # Customize host/port if needed
