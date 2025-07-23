# In database.py

import sqlite3
import os
import logging
import json # Use json instead of eval for safety

# This section ensures both functions use the same path
DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_FILE = os.path.join(DATA_DIR, 'analysis.db')

def store_analysis(analysis_id: str, summary: dict, architecture: dict):
    try:
        # This function now correctly saves to 'data/analysis.db'
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS analyses
                          (id TEXT PRIMARY KEY, summary TEXT, architecture TEXT)''')
        cursor.execute("INSERT OR REPLACE INTO analyses (id, summary, architecture) VALUES (?, ?, ?)",
                       (analysis_id, json.dumps(summary), json.dumps(architecture)))
        conn.commit()
        conn.close()
        logging.info(f"Successfully stored analysis for ID: {analysis_id} in {DB_FILE}")
    except Exception as e:
        logging.error(f"Failed to store analysis for ID {analysis_id}: {e}")
        raise

def retrieve_analysis(analysis_id: str):
    try:
        # This function now correctly reads from 'data/analysis.db'
        if not os.path.exists(DB_FILE):
            logging.error(f"Database file not found at {DB_FILE}")
            return None, None
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT summary, architecture FROM analyses WHERE id = ?", (analysis_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            logging.info(f"Successfully retrieved analysis for ID: {analysis_id}")
            summary = json.loads(result[0])
            architecture = json.loads(result[1])
            return summary, architecture
        else:
            logging.warning(f"No analysis found in database for ID: {analysis_id}")
            return None, None
    except Exception as e:
        logging.error(f"Failed to retrieve analysis for ID {analysis_id}: {e}")
        return None, None