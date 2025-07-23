# In unified_rag.py

import json
import faiss
import pickle
import os
import numpy as np
from ai_utils import generate_embedding
import logging

# This part is correct
DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

index_file = os.path.join(DATA_DIR, 'rag_index.faiss')
metadata_file = os.path.join(DATA_DIR, 'rag_metadata.pkl')


class UnifiedRagService:
    def __init__(self):
        self.dimension = 3072
        if os.path.exists(index_file) and os.path.exists(metadata_file):
            try:
                self.index = faiss.read_index(index_file)
                if self.index.d != self.dimension:
                    logging.warning(f"Existing RAG index has wrong dimension ({self.index.d}). Re-initializing.")
                    self.index = faiss.IndexFlatL2(self.dimension)
                    self.metadata = []
                else:
                    with open(metadata_file, 'rb') as f:
                        self.metadata = pickle.load(f)
                    logging.info(f"Loaded existing RAG index with {self.index.ntotal} vectors.")
            except Exception as e:
                logging.error(f"Error loading RAG index: {e}. Re-initializing.")
                self.index = faiss.IndexFlatL2(self.dimension)
                self.metadata = []
        else:
            logging.info("No existing RAG index found. Initializing a new one.")
            self.index = faiss.IndexFlatL2(self.dimension)
            self.metadata = []

    def query(self, query_text: str, top_k: int = 5):
        """
        Searches the RAG index for the most relevant context for a given query text.
        """
        if self.index.ntotal == 0:
            logging.warning("RAG index is empty. Cannot perform query.")
            return []

        try:
            # Step 1: Generate an embedding for the user's query
            logging.info(f"Generating embedding for RAG query: '{query_text[:100]}...'")
            query_embedding = np.array([generate_embedding(query_text)]).astype('float32')

            # Step 2: Search the FAISS index for the 'top_k' most similar vectors
            logging.info(f"Searching index with {self.index.ntotal} vectors for top {top_k} results...")
            distances, indices = self.index.search(query_embedding, top_k)

            # Step 3: Retrieve the original text metadata for the matching indices
            results = [self.metadata[i] for i in indices[0] if i < len(self.metadata)]
            logging.info(f"Found {len(results)} relevant results from RAG.")
            return results  # Returns a list of (analysis_id, text) tuples

        except Exception as e:
            logging.error(f"Error during RAG query: {e}", exc_info=True)
            return [] # Return an empty list on failure to prevent crashes

    # This method inside the class is likely already correct, but we confirm it here.
    def index_data(self, analysis_id: str, summary: dict, architecture: dict, parsed_data: list):
        """
        Indexes rich documents containing both the AI summary and the full source code.
        """
        # Create a lookup map from filename to its full raw content from the parser.
        content_map = {item.get('file'): item.get('content', '') for item in parsed_data}

        texts_to_index = []
        
        # Process each file from the AI's summary
        for file_summary in summary.get('files', []):
            file_name = file_summary.get('file_name')
            if not file_name:
                continue

            # Look up the full source code using the map.
            raw_content = content_map.get(file_name, '[Source code not found]')
            
            # Create a rich, combined text chunk for indexing.
            # This is the core of the new logic.
            text_chunk = (
                f"File: {file_name}\n"
                f"Purpose: {file_summary.get('purpose', 'N/A')}\n"
                f"Functionality: {file_summary.get('functionality', 'N/A')}\n"
                f"Identified Controls: {file_summary.get('controls', [])}\n"
                f"Identified Queries: {file_summary.get('ado_queries', [])}\n"
                f"--- FULL VB6 SOURCE CODE ---\n"
                f"{raw_content}"
            )
            texts_to_index.append(text_chunk)
            
        # Also index the target architecture plan as a separate document.
        texts_to_index.append(f"Target .NET Architecture Plan: {json.dumps(architecture, indent=2)}")

        if not texts_to_index:
            logging.warning("No texts were generated for RAG indexing. Skipping.")
            return

        try:
            logging.info(f"Generating embeddings for {len(texts_to_index)} rich text chunks...")
            embeddings = [generate_embedding(text) for text in texts_to_index]
            embeddings_np = np.array(embeddings).astype('float32')

            self.index.add(embeddings_np)
            self.metadata.extend([(analysis_id, text) for text in texts_to_index])
            
            faiss.write_index(self.index, index_file)
            with open(metadata_file, 'wb') as f:
                pickle.dump(self.metadata, f)
                
            logging.info(f"Successfully indexed {len(texts_to_index)} chunks in RAG.")
        except Exception as e:
            logging.error(f"Failed during RAG embedding or indexing process: {e}", exc_info=True)
            raise
# --- THIS IS THE CRITICAL FIX ---
# Update the standalone function to accept and pass the 'parsed_data' argument.
def index_in_rag(analysis_id: str, summary: dict, architecture: dict, parsed_data: list):
    service = UnifiedRagService()
    service.index_data(analysis_id, summary, architecture, parsed_data) # Pass all four arguments here
# --- END OF CRITICAL FIX ---