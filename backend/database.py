import os
import re
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

DB_PATH = Path(__file__).parent / "mediassist_data" / "db" / "mediassist.db"

def get_db_connection():
    return sqlite3.connect(str(DB_PATH))

# Schema details to supply to the LLM
DB_SCHEMA = """
Table 1: claims
Columns:
- claim_id (TEXT, Primary Key)
- patient_id (TEXT)
- patient_name (TEXT)
- department (TEXT)
- claim_type (TEXT)
- diagnosis_code (TEXT)
- insurer (TEXT)
- claimed_amount (REAL)
- approved_amount (REAL)
- status (TEXT) (values like 'Approved', 'Rejected', 'Pending', 'Escalated')
- submitted_date (TEXT, YYYY-MM-DD)
- resolved_date (TEXT, YYYY-MM-DD)

Table 2: maintenance_tickets
Columns:
- ticket_id (TEXT, Primary Key)
- equipment_name (TEXT)
- equipment_id (TEXT)
- category (TEXT) (e.g. 'Imaging', 'Ventilators', 'Laboratory', 'Surgical')
- campus (TEXT)
- issue_type (TEXT)
- fault_code (TEXT)
- raised_by (TEXT)
- raised_date (TEXT, YYYY-MM-DD)
- resolved_date (TEXT, YYYY-MM-DD)
- status (TEXT) (values like 'Open', 'In Progress', 'Resolved', 'Closed')
- resolution_note (TEXT)
"""

def clean_sql_query(raw_sql: str) -> str:
    # Remove markdown code block wrapping if present
    sql = re.sub(r"```sql\s*", "", raw_sql, flags=re.IGNORECASE)
    sql = re.sub(r"```\s*", "", sql)
    # Strip any leading/trailing whitespace
    sql = sql.strip()
    # Remove terminating semicolon for safety (optional, but keep it if standard SQLite)
    return sql

def sql_rag_chain(question: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {
            "answer": "Error: GROQ_API_KEY is missing from environment.",
            "sql_query": "",
            "sql_result": ""
        }

    client = Groq(api_key=api_key)
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    sql_query = ""

    # Step 1: Generate SQL query
    system_prompt = f"""You are a SQLite database expert. Write a raw SQLite SQL query to answer the user's question.
Do NOT include any explanations, conversation, or markdown text. Output ONLY the raw SQL query.
If the question is about claims, use the `claims` table. If it is about equipment maintenance, use the `maintenance_tickets` table.

Database Schema:
{DB_SCHEMA}

Example Question: "What is the total claimed amount for approved claims?"
Example Output: SELECT SUM(claimed_amount) FROM claims WHERE status = 'Approved';
"""

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.0,
            max_tokens=150
        )
        
        raw_sql = completion.choices[0].message.content
        sql_query = clean_sql_query(raw_sql)
        
        # Step 2: Execute SQL query
        conn = get_db_connection()
        cursor = conn.cursor()
        print(f"Executing SQL: {sql_query}")
        cursor.execute(sql_query)
        rows = cursor.fetchall()
        
        # Format results
        columns = [description[0] for description in cursor.description]
        results_list = [dict(zip(columns, row)) for row in rows]
        conn.close()
        
        # Step 3: Summarize results in natural language
        summary_system_prompt = f"""You are a helpful healthcare systems data analyst.
Summarize the database query results to answer the user's question. Be precise and ground your answer strictly in the provided query results.
Do not hallucinate any details that are not in the query results.

User Question: {question}
SQL Query Executed: {sql_query}
Query Results: {results_list}
"""
        summary_completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": summary_system_prompt},
                {"role": "user", "content": "Write a concise natural language response summarizing the findings."}
            ],
            temperature=0.3,
            max_tokens=250
        )
        
        answer = summary_completion.choices[0].message.content
        return {
            "answer": answer.strip(),
            "sql_query": sql_query,
            "sql_result": str(results_list)
        }
        
    except Exception as e:
        print(f"Error in SQL RAG chain: {e}")
        return {
            "answer": f"An error occurred while executing the SQL RAG chain: {str(e)}",
            "sql_query": sql_query,
            "sql_result": "Error"
        }
