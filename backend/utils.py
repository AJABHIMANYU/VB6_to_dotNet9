import re
import os
from fastapi import HTTPException
import git
import glob
import logging
from pathlib import Path
import tempfile
import mysql.connector
from ai_utils import infer_schema_with_llm  # Updated import from combined file
from urllib.parse import urlparse
import contextlib
import shutil  # For secure cleanup
import subprocess
import zipfile
from typing import Tuple, List, Dict

# Create logs directory if it doesn't exist
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
# Configure logging
logging.basicConfig(filename="logs/migration.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# From security_utils.py
def validate_git_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ('http', 'https', 'git') and bool(parsed.netloc)

@contextlib.contextmanager
def secure_temp_dir():
    temp_dir = tempfile.mkdtemp()
    try:
        # Set restrictive permissions
        os.chmod(temp_dir, 0o700)
        yield temp_dir
    finally:
        # Use shutil.rmtree for safe deletion (handles locked files)
        shutil.rmtree(temp_dir, ignore_errors=True)  # ignore_errors skips permission issues

# From dependency_graph.py
def build_dependency_graph(parsed_data: list) -> dict:
    graph = {}
    for item in parsed_data:
        file = item.get('file')  # Safe access; returns None if missing
        if file:
            graph[file] = item.get('dependencies', [])
        else:
            logging.warning(f"Skipping item without 'file' key: {item}")
    return graph

# From schema_parser.py
def analyze_schema(ado_queries: list = None, classes: list = None):
    """
    Infers a database schema by analyzing ADO queries found in the source code,
    using an LLM as the primary analysis tool.
    
    Args:
        ado_queries: A list of SQL query strings extracted from the VB6 code.
        classes: A list of parsed class data (reserved for future enhancements).

    Returns:
        A dictionary representing the inferred database schema.
    """
    try:
        # Although 'classes' is passed, we primarily rely on the globally parsed ado_queries
        # as the most direct source of schema information.
        all_queries = ado_queries or []

        if not all_queries:
            logging.warning("No ADO queries found to infer a schema from. The generated data models may be incomplete.")
            return {"database": "inferred_db", "tables": []}

        # Use the LLM to infer the schema from the collected queries.
        logging.info(f"Inferring schema from {len(all_queries)} ADO queries using LLM...")
        schema = infer_schema_with_llm(all_queries)
        
        # Ensure the output has a database name for consistency in later steps.
        if "database" not in schema:
            schema["database"] = "inferred_db"

        logging.info("Successfully inferred schema using LLM.")
        return schema

    except Exception as e:
        logging.error(f"An error occurred while inferring schema with LLM: {e}")
        # Return a safe, empty default value to allow the process to continue if possible.
        return {"database": "unknown", "tables": []}

# From parsers.py (all functions combined here)
def parse_vb6_project(vb6_project_path: str) -> Tuple[List[Dict], List[str], List[Dict], Dict]:
    """
    Parse a VB6 project by finding all relevant files within the project
    directory after cloning/copying it to a temporary location. This version
    handles a comprehensive set of VB6 file types.
    """
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        logging.info(f"Created temporary directory for processing: {temp_dir}")
        project_root_in_temp = ""

        if vb6_project_path.startswith(("http://", "https://")):
            logging.info(f"Cloning GitHub repository from {vb6_project_path} into {temp_dir}")
            git.Repo.clone_from(vb6_project_path, temp_dir)
            project_root_in_temp = temp_dir
        else:
            logging.info(f"Processing local VB6 project from: {vb6_project_path}")
            if not os.path.exists(vb6_project_path):
                raise ValueError(f"VB6 project path does not exist: {vb6_project_path}")
            original_project_root = os.path.dirname(vb6_project_path)
            shutil.copytree(original_project_root, temp_dir, dirs_exist_ok=True)
            project_root_in_temp = temp_dir
        
        # Define patterns for all relevant VB6 file types
        text_based_patterns = ["*.vbp", "*.frm", "*.bas", "*.cls", "*.ctl", "*.pag", "*.dsr", "*.vbw"]
        binary_based_patterns = ["*.frx", "*.ctx", "*.dsx", "*.res"]
        
        all_found_files = []
        for pattern in text_based_patterns + binary_based_patterns:
            all_found_files.extend(Path(project_root_in_temp).rglob(pattern))

        if not all_found_files:
            raise ValueError(f"No VB6 project files found in the provided path/repository.")

        parsed_data = []
        ado_queries = []
        all_class_names = []
        
        for file_path_obj in all_found_files:
            file_path = str(file_path_obj)
            file_name = os.path.basename(file_path)
            file_extension = os.path.splitext(file_name)[1].lower()
            file_type = file_extension.replace('.', '')

            file_info = {
                "file": file_name,
                "type": file_type,
                "controls": [],
                "ado_queries": [],
                "content": ""
            }
            
            # --- THIS IS THE CORRECTED LOGIC ---
            if any(file_name.lower().endswith(ext.replace('*', '')) for ext in text_based_patterns):
                logging.info(f"Parsing text-based .{file_type} file: {file_path}")
                try:
                    with open(file_path, 'r', encoding='latin-1', errors='ignore') as code_file:
                        content = code_file.read()
                    
                    file_info["content"] = content
                    
                    if file_type in ['frm', 'ctl', 'pag', 'dsr']:
                        file_info["controls"] = re.findall(r'Begin\s+VB\.(\w+)', content)
                    
                    queries = re.findall(r'SELECT\s+.*?\s+FROM\s+\w+', content, re.IGNORECASE)
                    file_info["ado_queries"] = queries
                    ado_queries.extend(queries)

                    if file_type == 'cls':
                        all_class_names.append(os.path.splitext(file_name)[0])
                except Exception as e:
                    logging.warning(f"Could not read or parse text file {file_name}: {e}")
            
            elif any(file_name.lower().endswith(ext.replace('*', '')) for ext in binary_based_patterns):
                logging.info(f"Identifying binary resource .{file_type} file: {file_path}")
                file_info["content"] = f"[Binary resource file: {file_name}. Content not readable.]"
            # --- END OF CORRECTED LOGIC ---
            
            parsed_data.append(file_info)

        dep_graph = {"project_files": [item["file"] for item in parsed_data]}
        return parsed_data, ado_queries, all_class_names, dep_graph

    except Exception as e:
        logging.error(f"Failed to parse VB6 project: {e}", exc_info=True)
        raise
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

def fallback_simple_parser(project_path):
    """Fallback: Simple content extraction if regex fails (from existing code)."""
    parsed = []
    for root, _, files in os.walk(project_path):
        for file in files:
            file_path = os.path.join(root, file)
            ext = os.path.splitext(file)[1].lower()
            if ext in ('.vbp', '.frm', '.bas', '.cls', '.frx', '.res'):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    controls = re.findall(r'Begin VB\.(\w+)', content) or []  # Fallback pattern
                    events = re.findall(r'Private Sub (\w+)_(\w+)\(', content) or []
                    ado_queries = re.findall(r'CommandText = "(.*?)"', content) or []
                    dependencies = re.findall(r'Object = "{(.*?)}"; "(.*?)"', content) or []
                    parsed.append({
                        'file': file,  # Ensured 'file' key
                        'controls': controls,
                        'events': events,
                        'ado_queries': ado_queries,
                        'dependencies': dependencies,
                        'content': content  # Full content for LLM/RAG
                    })
                except Exception as e:
                    logging.warning("Fallback parsing failed for %s: %s", file, str(e))
    return parsed

# Modified vbp_parser: Added 'file' key to the project_data dict for consistency
def vbp_parser(project_path):
    try:
        vbp_files = glob.glob(os.path.join(project_path, "*.vbp"))
        if not vbp_files:
            logging.error("No .vbp file found in %s", project_path)
            return []
        
        vbp_file = vbp_files[0]
        with open(vbp_file, "r", encoding="utf-8", errors='ignore') as f:  # Added errors='ignore' for robustness
            content = f.read()
        
        project_data = {
            "file": os.path.basename(vbp_file),  # Added 'file' key for consistency with other parsers
            "name": os.path.splitext(os.path.basename(vbp_file))[0],
            "forms": [],
            "modules": [],
            "classes": [],
            "references": []
        }
        
        form_pattern = re.compile(r'^Form=([^\s;]+)', re.MULTILINE)
        module_pattern = re.compile(r'^Module=([^;]+);\s*([^\s]+)', re.MULTILINE)
        class_pattern = re.compile(r'^Class=([^;]+);\s*([^\s]+)', re.MULTILINE)
        reference_pattern = re.compile(r'^Reference=.*\\([^\\]+)$', re.MULTILINE)
        
        project_data["forms"] = [f.strip() for f in form_pattern.findall(content)]
        project_data["modules"] = [m[1].strip() for m in module_pattern.findall(content)]
        project_data["classes"] = [c[1].strip() for c in class_pattern.findall(content)]
        project_data["references"] = [r.strip() for r in reference_pattern.findall(content)]
        
        if not any(project_data.values()):  # If empty, trigger fallback in caller
            logging.warning("vbp_parser returned empty; fallback may be used")
        
        logging.info("Parsed .vbp file: %s", vbp_file)
        return [{"project": project_data}]  # Wrapped in list
    except Exception as e:
        logging.error("Error parsing .vbp file: %s", str(e))
        return []

# Your frm_parser (minor enhancements: errors='ignore', fallback check)
def frm_parser(project_path):
    try:
        frm_files = glob.glob(os.path.join(project_path, "*.frm"))
        results = []
        
        for frm_file in frm_files:
            with open(frm_file, "r", encoding="utf-8", errors='ignore') as f:
                content = f.read()
            
            form_data = {
                "file": os.path.basename(frm_file),  # Ensured 'file' key
                "controls": [],
                "events": [],
                "dependencies": []
            }
            
            control_pattern = re.compile(r'Begin\s+([^\s]+)\s+([^\s]+)\s*.*?End', re.DOTALL)
            property_pattern = re.compile(r'(\w+)\s*=\s*([^\n]+)')
            event_pattern = re.compile(r'Private\s+Sub\s+([^\s(]+)\s*\(', re.MULTILINE)
            db_call_pattern = re.compile(r'(\w+)\.Execute\s*\("([^"]+)"', re.MULTILINE)
            
            for control_type, control_name in control_pattern.findall(content):
                control_block = re.search(rf'Begin\s+{control_type}\s+{control_name}\s*.*?End', content, re.DOTALL)
                if control_block:
                    properties = {k: v.strip() for k, v in property_pattern.findall(control_block.group(0))}
                    form_data["controls"].append({"type": control_type, "name": control_name, "properties": properties})
            
            form_data["events"] = [e for e in event_pattern.findall(content) if not e.startswith("Form_") or e == "Form_Load"]
            form_data["dependencies"] = list(set([d[0] for d in db_call_pattern.findall(content)]))
            
            if not form_data["controls"] and not form_data["events"]:  # Fallback trigger
                logging.warning("frm_parser empty for %s; using fallback in unified parser", frm_file)
            
            results.append(form_data)
            logging.info("Parsed .frm file: %s", frm_file)
        
        return results
    except Exception as e:
        logging.error("Error parsing .frm files: %s", str(e))
        return []

# Your bas_parser (similar enhancements)
def bas_parser(project_path):
    try:
        bas_files = glob.glob(os.path.join(project_path, "*.bas"))
        results = []
        
        for bas_file in bas_files:
            with open(bas_file, "r", encoding="utf-8", errors='ignore') as f:
                content = f.read()
            
            module_data = {
                "file": os.path.basename(bas_file),  # Ensured 'file' key
                "functions": [],
                "variables": []
            }
            
            function_pattern = re.compile(r'(Public|Private)?\s*(Function|Sub)\s+([^\s(]+)\s*\(([^)]*)\)\s*(As\s+[^\s]+)?', re.MULTILINE)
            variable_pattern = re.compile(r'(Public|Private)?\s*Dim\s+([^\s]+)\s+As\s+([^\s]+)', re.MULTILINE)
            
            for _, kind, name, params, return_type in function_pattern.findall(content):
                module_data["functions"].append({
                    "name": name,
                    "type": kind,
                    "parameters": [p.strip() for p in params.split(",") if p.strip()],
                    "return": return_type.strip() if return_type else "None"
                })
            
            module_data["variables"] = [{"name": name, "type": var_type} for _, name, var_type in variable_pattern.findall(content)]
            
            if not module_data["functions"] and not module_data["variables"]:
                logging.warning("bas_parser empty for %s", bas_file)
            
            results.append(module_data)
            logging.info("Parsed .bas file: %s", bas_file)
        
        return results
    except Exception as e:
        logging.error("Error parsing .bas files: %s", str(e))
        return []

# Your cls_parser (enhanced with fallback check)
def cls_parser(project_path):
    try:
        cls_files = glob.glob(os.path.join(project_path, "*.cls"))
        results = []
        
        for cls_file in cls_files:
            with open(cls_file, "r", encoding="utf-8", errors='ignore') as f:
                content = f.read()
            
            class_data = {
                "file": os.path.basename(cls_file),  # Ensured 'file' key
                "class": os.path.splitext(os.path.basename(cls_file))[0],
                "methods": [],
                "properties": [],
                "schema": []
            }
            
            method_pattern = re.compile(r'(Public|Private)?\s*(Function|Sub)\s+([^\s(]+)\s*\(([^)]*)\)\s*(As\s+[^\s]+)?', re.MULTILINE)
            property_pattern = re.compile(r'(Public|Private)?\s*Property\s+(Get|Let|Set)\s+([^\s(]+)\s*\(([^)]*)\)\s*(As\s+[^\s]+)?', re.MULTILINE)
            query_pattern = re.compile(r'Execute\s*\("([^"]+)"', re.MULTILINE)
            
            for _, kind, name, params, return_type in method_pattern.findall(content):
                class_data["methods"].append({
                    "name": name,
                    "type": kind,
                    "parameters": [p.strip() for p in params.split(",") if p.strip()],
                    "return": return_type.strip() if return_type else "None"
                })
            
            for _, kind, name, params, prop_type in property_pattern.findall(content):
                class_data["properties"].append({
                    "name": name,
                    "type": kind,
                    "parameters": [p.strip() for p in params.split(",") if p.strip()],
                    "return": prop_type.strip() if prop_type else "None"
                })
            
            queries = query_pattern.findall(content)
            for query in queries:
                table_match = re.search(r'FROM\s+([^\s]+)', query, re.IGNORECASE)
                if table_match:
                    table = table_match.group(1)
                    columns = []
                    if "SELECT" in query.upper():
                        select_match = re.search(r'SELECT\s+(.+?)\s+FROM', query, re.IGNORECASE)
                        if select_match:
                            columns = [c.strip() for c in select_match.group(1).split(",") if c.strip() != "*"]
                    elif "INSERT INTO" in query.upper():
                        insert_match = re.search(r'INSERT INTO\s+[^\s]+\s*\(([^)]+)\)', query, re.IGNORECASE)
                        if insert_match:
                            columns = [c.strip() for c in insert_match.group(1).split(",")]
                    class_data["schema"].append({
                        "table": table,
                        "columns": [{"name": c, "type": "UNKNOWN"} for c in columns]
                    })
            
            if not class_data["methods"] and not class_data["properties"] and not class_data["schema"]:
                logging.warning("cls_parser empty for %s", cls_file)
            
            results.append(class_data)
            logging.info("Parsed .cls file: %s", cls_file)
        
        return results
    except Exception as e:
        logging.error("Error parsing .cls files: %s", str(e))
        return []

# Your frx_res_parser (enhanced with note for future real parsing)
def frx_res_parser(project_path):
    try:
        frx_files = glob.glob(os.path.join(project_path, "*.frx"))
        res_files = glob.glob(os.path.join(project_path, "*.res"))
        results = []
        
        for resource_file in frx_files + res_files:
            resource_data = {
                "file": os.path.basename(resource_file),  # Ensured 'file' key
                "resources": []
            }
            
            # Placeholder: Extract to wwwroot (enhance with actual parser like 'vb6parser' library in future)
            output_dir = os.path.join("wwwroot", "resources", os.path.splitext(os.path.basename(resource_file))[0])
            os.makedirs(output_dir, exist_ok=True)
            
            resource_data["resources"].append({
                "type": "image",
                "name": f"{os.path.splitext(os.path.basename(resource_file))[0]}.png",
                "path": os.path.join(output_dir, "resource.png")
            })
            
            results.append(resource_data)
            logging.info("Parsed resource file: %s", resource_file)
        
        return results
    except Exception as e:
        logging.error("Error parsing .frx/.res files: %s", str(e))
        return []

# From general utils (validate_code, package_as_zip)
def validate_code(files: dict):
    """
    Validates the generated code by writing it to a temporary directory
    and running 'dotnet build'. Ensures all subdirectories are created.
    """
    temp_dir = "temp_migration"
    # Clean up the directory from previous runs if it exists
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)
    
    logging.info(f"Writing {len(files)} generated files to temporary directory: {temp_dir}")

    for path, content in files.items():
        # Construct the full path for the file
        full_path = os.path.join(temp_dir, path)
        
        # --- THIS IS THE CRITICAL FIX ---
        # Get the directory part of the path
        directory = os.path.dirname(full_path)
        # Create the subdirectory if it doesn't exist
        os.makedirs(directory, exist_ok=True)
        # --- END OF CRITICAL FIX ---
        
        try:
            # Now, safely write the file
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            logging.error(f"Failed to write file {full_path}: {e}")
            # Return an immediate failure if a file can't be written
            return {"success": False, "errors": [f"Failed to write file {path}: {e}"]}

    logging.info("All files written. Running 'dotnet build'...")
    dotnet_executable = r"C:\Program Files\dotnet\dotnet.exe"
    
    # Check if the executable exists at the specified path
    if not os.path.exists(dotnet_executable):
        error_msg = f"'dotnet.exe' not found at the specified path: {dotnet_executable}. Please install the .NET SDK or update the path in utils.py."
        logging.error(error_msg)
        return {"success": False, "errors": [error_msg]}

    try:
        # Use the full path in the subprocess call
        result = subprocess.run(
            [dotnet_executable, "build", temp_dir], 
            capture_output=True, 
            text=True,
            check=False
        )
        
        success = result.returncode == 0
        if success:
            logging.info("'dotnet build' completed successfully.")
            return {"success": True, "errors": []}
        else:
            logging.error(f"'dotnet build' failed. Stderr:\n{result.stderr}")
            return {"success": False, "errors": result.stderr.splitlines()}
    except FileNotFoundError:
        logging.error("'dotnet' command not found. Is the .NET SDK installed and in the system's PATH?")
        return {"success": False, "errors": ["'dotnet' command not found."]}

# --- MODIFIED validate_code FUNCTION END ---
def package_as_zip(files: dict):
    zip_path = "migration_output.zip"
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for path, content in files.items():
            zipf.writestr(path, content)
    return zip_path
