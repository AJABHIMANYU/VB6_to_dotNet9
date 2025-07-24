# react_agent.py

import os
import yaml
import logging
import json

# Import all necessary generator functions from ai_utils
from ai_utils import (
    generate_model_with_llm, 
    generate_controller_with_llm, 
    generate_view_with_llm,
    generate_interface_with_llm,
    generate_service_with_llm
)
from unified_rag import UnifiedRagService
from fcache.cache import FileCache

# Load prompts once at the top
with open('prompts.yml', 'r') as f:
    prompts = yaml.safe_load(f)

# --- A SINGLE, CONSOLIDATED and MODERNIZED STATIC_TEMPLATES DICTIONARY ---
STATIC_TEMPLATES = {
    'csproj': """<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net9.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.0" />
    <PackageReference Include="Microsoft.EntityFrameworkCore.Design" Version="8.0.0">
      <IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
      <PrivateAssets>all</PrivateAssets>
    </PackageReference>
  </ItemGroup>
</Project>""",
    'Program.cs': """var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllersWithViews();
var app = builder.Build();
if (!app.Environment.IsDevelopment()) { app.UseExceptionHandler("/Home/Error"); app.UseHsts(); }
app.UseHttpsRedirection();
app.UseStaticFiles();
app.UseRouting();
app.UseAuthorization();
app.MapControllerRoute(name: "default", pattern: "{controller=Home}/{action=Index}/{id?}");
app.Run();
""",
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
    '_ViewStart.cshtml': """@{
    Layout = "_Layout";
}""",
    '_ViewImports.cshtml': """@using {namespace}
@using {namespace}.Models
@addTagHelper *, Microsoft.AspNetCore.Mvc.TagHelpers""",
    'appsettings.json': """{
    "ConnectionStrings": {
        "DefaultConnection": "{connection_string}"
    },
    "Logging": { "LogLevel": { "Default": "Information", "Microsoft.AspNetCore": "Warning" } },
    "AllowedHosts": "*"
}"""
}


def react_agent_generate_files(analysis: dict, architecture: dict, rag_service: UnifiedRagService, file_cache: FileCache):
    generated_files = {}
    # --- FIX: Use the snake_case key that is stored in the database ---
    project_name = architecture.get('project_name', 'MigratedApp')

    logging.info(f"--- Starting DETAILED ReAct Agent generation for project '{project_name}' ---")

    architecture_files = architecture.get('files', [])
    for i, target_file_def in enumerate(architecture_files):
        # --- FIX: Use the snake_case keys that are stored in the database ---
        file_path = target_file_def.get('file_path')
        file_type = target_file_def.get('type')

        if not file_path or not file_type:
            logging.warning(f"Skipping file definition at index {i} due to missing 'file_path' or 'type'. Raw data: {target_file_def}")
            continue

        logging.info(f"\n[Step {i+1}/{len(architecture_files)}] Processing Target File: {file_path}")

        content_to_process = ""
        
        template_key = os.path.basename(file_path)
        if template_key in STATIC_TEMPLATES:
            logging.info(f"  Found static template for file name: '{template_key}'.")
            content_to_process = STATIC_TEMPLATES[template_key]
        elif file_type in STATIC_TEMPLATES:
            logging.info(f"  Found static template for file type: '{file_type}'.")
            content_to_process = STATIC_TEMPLATES[file_type]
        else:
            rag_query = f"Retrieve original VB6 source code and analysis related to the new file: {file_path}"
            rag_context_tuples = rag_service.query(rag_query)
            rag_context = "\n".join([text for _, text in rag_context_tuples])
            logging.info(f"  Retrieved {len(rag_context_tuples)} relevant context chunks from RAG.")

            context_for_llm = target_file_def
            logging.info(f"  Calling specialized generator for file type: '{file_type}'...")
            
            if file_type in ['model', 'viewmodel']:
                content_to_process = generate_model_with_llm(context_for_llm)
            elif file_type == 'controller':
                content_to_process = generate_controller_with_llm(context_for_llm, rag_context)
            elif file_type == 'view':
                content_to_process = generate_view_with_llm(context_for_llm)
            elif file_type == 'interface':
                content_to_process = generate_interface_with_llm(context_for_llm)
            elif file_type == 'service':
                content_to_process = generate_service_with_llm(context_for_llm, rag_context)
            else:
                logging.warning(f"  No specialized generator or static template for type '{file_type}'. Skipping file.")
                continue
        
        final_content = content_to_process.replace('{namespace}', project_name)
        if 'appsettings.json' in file_path:
            placeholder_conn_str = "Server=YOUR_SERVER;Database=YOUR_DB;User Id=YOUR_USER;Password=YOUR_PASSWORD;"
            final_content = final_content.replace('{connection_string}', placeholder_conn_str)
        
        generated_files[file_path] = final_content
        logging.info(f"  Successfully generated and assembled content for: {file_path}")

    resources = analysis.get('resources', [])
    if resources:
        logging.info(f"--- Handling {len(resources)} resource files ---")
        for res in resources:
            converted_path = convert_resource(res['file'])
            generated_files[converted_path] = ''
            logging.info(f"  Scheduled resource conversion for '{res['file']}' to '{converted_path}'")

    logging.info(f"--- ReAct Agent finished. Total files generated: {len(generated_files)} ---")
    return generated_files

def convert_resource(resource_file: str):
    output_path = f"wwwroot/resources/{os.path.basename(resource_file)}.png"
    return output_path