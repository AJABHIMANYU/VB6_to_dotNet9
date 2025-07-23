# react_agent.py

import logging
import os
import yaml
from ai_utils import generate_file_with_llm  # For LLM code generation
from unified_rag import UnifiedRagService  # For RAG queries
# Assume FileCache is a simple class or dict for caching VB6 files; implement if needed
from fcache.cache import FileCache

# Load prompts
with open('prompts.yml', 'r') as f:
    prompts = yaml.safe_load(f)

# Expanded static templates (including user-provided ones)
STATIC_TEMPLATES = {
    'csproj': """<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net9.0</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.AspNetCore.Mvc" Version="9.0.0" />
    <PackageReference Include="Microsoft.EntityFrameworkCore" Version="9.0.0" />
    <!-- Dynamic content here -->
  </ItemGroup>
</Project>""",
    'Program.cs': """using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.Hosting;

public class Program
{
    public static void Main(string[] args)
    {
        CreateHostBuilder(args).Build().Run();
    }

    public static IHostBuilder CreateHostBuilder(string[] args) =>
        Host.CreateDefaultBuilder(args)
            .ConfigureWebHostDefaults(webBuilder =>
            {
                webBuilder.UseStartup<Startup>();
            });
}""",
    '_ViewImports.cshtml': """@using {namespace}.Presentation
@using {namespace}.Domain.Entities
@addTagHelper *, Microsoft.AspNetCore.Mvc.TagHelpers""",
    '_ViewStart.cshtml': """@{
    Layout = "_Layout";
}""",
    '_Layout.cshtml': """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>@ViewData["Title"] - {namespace}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" />
    <link rel="stylesheet" href="~/css/site.css" asp-append-version="true" />
</head>
<body>
    <header>
        <nav class="navbar navbar-expand-sm navbar-toggleable-sm navbar-light bg-white border-bottom box-shadow mb-3">
            <div class="container-fluid">
                <a class="navbar-brand" asp-area="" asp-controller="Home" asp-action="Index">{namespace}</a>
            </div>
        </nav>
    </header>
    <div class="container">
        <main role="main" class="pb-3">
            @RenderBody()
        </main>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/jquery@3.6.0/dist/jquery.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script src="~/js/site.js" asp-append-version="true"></script>
    @await RenderSectionAsync("Scripts", required: false)
</body>
</html>""",
    '_ValidationScriptsPartial.cshtml': """<script src="https://cdnjs.cloudflare.com/ajax/libs/jquery-validate/1.19.3/jquery.validate.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jquery-validation-unobtrusive/3.2.12/jquery.validate.unobtrusive.min.js"></script>""",
    'appsettings.json': """{
    "ConnectionStrings": {
        "DefaultConnection": "{connection_string}"
    },
    "Logging": { "LogLevel": { "Default": "Information", "Microsoft.AspNetCore": "Warning" } },
    "AllowedHosts": "*"
}""",
    # Add more templates as needed (e.g., base Controller.cs)
}

# Cache for LLM responses (simple dict; use Redis for production)
llm_cache = {}

def react_agent_generate_files(analysis: dict, architecture: dict, rag_service: UnifiedRagService, file_cache: FileCache):
    generated_files = {}
    namespace = architecture.get('namespace', 'MyApp')
    
    logging.info(f"--- Starting ReAct Agent generation for namespace '{namespace}' ---")
    
    # Iterate over target files in architecture
    for i, target_file in enumerate(architecture.get('files', [])):
        file_path = target_file['file_path']
        file_type = target_file['type']
        
        logging.info(f"\n[Step {i+1}/{len(architecture.get('files', []))}] Processing Target File: {file_path}")
        
        # Step 1: THINK - Formulate a query for RAG
        rag_query = f"Generate .NET code for a '{file_type}' at path '{file_path}'. Use context from the original VB6 project analysis, focusing on file purpose, controls, events, and relevant database schema information."
        logging.info(f"  [1. THINK] Formulated RAG Query: '{rag_query[:150]}...'")
        
        # Step 2: ACT - Query RAG for integrated details
        rag_context_tuples = rag_service.query(rag_query)
        rag_context = "\n".join([text for _, text in rag_context_tuples])
        logging.info(f"  [2. ACT] Retrieved {len(rag_context_tuples)} relevant context chunks from RAG.")
        if rag_context:
            logging.debug(f"  [2a. RAG Context]:\n---\n{rag_context}\n---")

        # Step 3: ACT - Fetch source VB6 content from FileCache (if available)
        source_vb6_filename = target_file.get('source_vb6_file') # You may need to add this to your architecture plan
        vb6_source = file_cache.get(source_vb6_filename) if source_vb6_filename else None
        if vb6_source:
            logging.info(f"  [3. ACT] Fetched source code for '{source_vb6_filename}' from cache.")
        
        # Step 4: THINK/ACT - Generate dynamic content with LLM
        cache_key = f"{file_path}_{hash(rag_context)}"
        if cache_key in llm_cache:
            dynamic_content = llm_cache[cache_key]
            logging.info(f"  [4. ACT] Found cached LLM response for this file.")
        else:
            logging.info(f"  [4. THINK] No cached response. Preparing context for LLM code generation.")
            context_for_llm = {
                'target_file_info': target_file,
                'retrieved_rag_context': rag_context,
                'original_vb6_source': vb6_source or "Source code not available."
            }
            logging.info(f"  [4a. ACT] Calling LLM to generate code for '{file_type}'...")
            dynamic_content = generate_file_with_llm(file_type, context_for_llm)
            llm_cache[cache_key] = dynamic_content
            logging.info(f"  [4b. LLM Response] Received generated code snippet.")
            logging.debug(f"  [4c. LLM Raw Content]:\n---\n{dynamic_content[:500]}...\n---")

        # Step 5: ASSEMBLE - Merge with static template if applicable
        template_key = os.path.basename(file_path)
        template = STATIC_TEMPLATES.get(template_key)
        
        if template:
            logging.info(f"  [5. ASSEMBLE] Merging generated code with static template: '{template_key}'")
            # Basic templating logic
            file_content = template.replace('{namespace}', namespace)
            if 'appsettings.json' in file_path:
                placeholder_conn_str = "Server=YOUR_SERVER_ADDRESS;Database=YOUR_DATABASE_NAME;User=YOUR_USERNAME;Password=YOUR_PASSWORD;"
                file_content = file_content.replace('{connection_string}', placeholder_conn_str)
            
            if '<!-- Dynamic content here -->' in file_content:
                 file_content = file_content.replace('<!-- Dynamic content here -->', dynamic_content)
            else:
                 # If no placeholder, append (or you could decide to prepend/replace)
                 file_content += "\n\n" + dynamic_content
        else:
            logging.info(f"  [5. ASSEMBLE] No static template found. Using LLM output directly.")
            file_content = dynamic_content
        
        generated_files[file_path] = file_content
        logging.info(f"  [Result] Successfully generated content for: {file_path}")

    logging.info(f"--- ReAct Agent finished. Total files generated: {len(generated_files)} ---")
    return generated_files
def convert_resource(resource_file: str):
    # Placeholder: Convert .frx/.res to wwwroot asset (use dedicated library or tool)
    # Example: Copy or transform to .png/.css
    output_path = f"wwwroot/resources/{os.path.basename(resource_file)}.png"
    # Actual conversion logic here (e.g., using PIL for images)
    return output_path
