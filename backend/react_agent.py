# react_agent.py

import os
import yaml
import logging
import json

# Import all necessary generator functions from ai_utils
from ai_utils import (
    generate_model_with_llm,
    generate_interface_with_llm,
    generate_service_with_llm,
    generate_worker_with_llm, # New generator
)
from unified_rag import UnifiedRagService
from fcache.cache import FileCache

# --- NEW STATIC TEMPLATES FOR A .NET 8 WORKER SERVICE ---
STATIC_TEMPLATES = {
    'csproj': """<Project Sdk="Microsoft.NET.Sdk.Worker">

  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <UserSecretsId>dotnet-{namespace}-5c8a5a4e-9b7c-4c8d-8a6e-8b9f0e6e7d3b</UserSecretsId>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.Extensions.Hosting" Version="8.0.0" />
    <PackageReference Include="Microsoft.Extensions.Hosting.WindowsServices" Version="8.0.0" />
    <PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="8.0.0" />
    <PackageReference Include="Microsoft.EntityFrameworkCore.Design" Version="8.0.0">
      <IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
      <PrivateAssets>all</PrivateAssets>
    </PackageReference>
  </ItemGroup>
</Project>""",

    'program': """using {namespace};
using {namespace}.Services; // Assuming services are in this namespace

IHost host = Host.CreateDefaultBuilder(args)
    .UseWindowsService(options =>
    {{
        options.ServiceName = "{namespace} Service";
    }})
    .ConfigureServices(services =>
    {{
        // TODO: Register your services here
        // services.AddSingleton<IMyService, MyService>();

        services.AddHostedService<PrimaryWorker>(); // Assuming a worker named PrimaryWorker
    }})
    .Build();

host.Run();
""",

    'appsettings.json': """{{
  "Logging": {{
    "LogLevel": {{
      "Default": "Information",
      "Microsoft.Hosting.Lifetime": "Information"
    }}
  }},
  "ConnectionStrings": {{
    "DefaultConnection": "Server=YOUR_SERVER;Database={namespace}DB;User Id=YOUR_USER;Password=YOUR_PASSWORD;Trusted_Connection=False;Encrypt=True;"
  }}
}}"""
}


def react_agent_generate_files(analysis: dict, architecture: dict, rag_service: UnifiedRagService, file_cache: FileCache):
    generated_files = {}
    project_name = architecture.get('project_name', 'MigratedWindowsService')
    logging.info(f"--- Starting ReAct Agent generation for project '{project_name}' ---")

    architecture_files = architecture.get('files', [])
    for i, target_file_def in enumerate(architecture_files):
        file_path = target_file_def.get('file_path')
        file_type = target_file_def.get('type')

        if not file_path or not file_type:
            logging.warning(f"Skipping file definition at index {i} due to missing 'file_path' or 'type'.")
            continue

        logging.info(f"\n[Step {i+1}/{len(architecture_files)}] Processing Target File: {file_path}")

        content_to_process = ""
        
        # Check for static templates first by type, then by file name
        if file_type in STATIC_TEMPLATES:
            logging.info(f"  Found static template for file type: '{file_type}'.")
            content_to_process = STATIC_TEMPLATES[file_type]
        elif os.path.basename(file_path) in STATIC_TEMPLATES:
            logging.info(f"  Found static template for file name: '{os.path.basename(file_path)}'.")
            content_to_process = STATIC_TEMPLATES[os.path.basename(file_path)]
        else:
            # If not a static template, use RAG and LLM generators
            rag_query = f"Retrieve VB6 source code and analysis for generating the new file: {file_path}"
            rag_context_tuples = rag_service.query(rag_query)
            rag_context = "\n".join([text for _, text in rag_context_tuples])
            logging.info(f"  Retrieved {len(rag_context_tuples)} relevant context chunks from RAG.")

            context_for_llm = target_file_def
            logging.info(f"  Calling specialized generator for file type: '{file_type}'...")
            
            if file_type == 'model':
                content_to_process = generate_model_with_llm(context_for_llm)
            elif file_type == 'interface':
                content_to_process = generate_interface_with_llm(context_for_llm)
            elif file_type == 'service':
                content_to_process = generate_service_with_llm(context_for_llm, rag_context)
            elif file_type == 'worker': # <-- NEW LOGIC
                content_to_process = generate_worker_with_llm(context_for_llm, rag_context)
            else:
                logging.warning(f"  No specialized generator or static template for type '{file_type}'. Skipping file.")
                continue
        
        # Replace placeholders
        final_content = content_to_process.replace('{namespace}', project_name)
        
        generated_files[file_path] = final_content
        logging.info(f"  Successfully generated content for: {file_path}")

    logging.info(f"--- ReAct Agent finished. Total files generated: {len(generated_files)} ---")
    return generated_files