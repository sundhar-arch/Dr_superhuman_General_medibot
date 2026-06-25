import os
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel
from groq import Groq

# Import database and retrieval chains
from database import sql_rag_chain
from retrieval import hybrid_rag_chain, hybrid_search

load_dotenv()

app = FastAPI(title="Dr. Superhuman General MediBot API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mock user credentials database
MOCK_USERS = {
    "dr.mehta": {"password": "password", "role": "doctor"},
    "nurse.priya": {"password": "password", "role": "nurse"},
    "billing.ravi": {"password": "password", "role": "billing_executive"},
    "tech.anand": {"password": "password", "role": "technician"},
    "admin.sys": {"password": "password", "role": "admin"}
}

ROLE_COLLECTIONS = {
    "doctor": ["clinical", "nursing", "general"],
    "nurse": ["nursing", "general"],
    "billing_executive": ["billing", "general"],
    "technician": ["equipment", "general"],
    "admin": ["clinical", "nursing", "billing", "equipment", "general"]
}

class LoginRequest(BaseModel):
    username: str
    password: str

class ChatRequest(BaseModel):
    question: str
    role: str
    username: str = "user"

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/login")
def login(req: LoginRequest):
    user = MOCK_USERS.get(req.username.lower())
    if not user or user["password"] != req.password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # Mock token is simply the username tagged with role
    token = f"token-{req.username}-{user['role']}"
    return {
        "token": token,
        "role": user["role"],
        "username": req.username
    }

@app.get("/collections/{role}")
def get_collections(role: str):
    collections = ROLE_COLLECTIONS.get(role.lower())
    if not collections:
        raise HTTPException(status_code=404, detail="Role not found")
    return {"role": role, "collections": collections}

def classify_question(question: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "document"
        
    client = Groq(api_key=api_key)
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    
    prompt = f"""Categorize the user's question into one of two categories:
1. "analytical": The question requires counts, sums, database stats, tickets, billing claims, or other structured database calculations.
2. "document": The question asks about treatment guidelines, procedures, handbooks, calibration steps, or textual knowledge.

Respond ONLY with the word "analytical" or "document". Do not include any other text or markdown formatting.

Question: {question}
"""
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=10
        )
        category = completion.choices[0].message.content.strip().lower()
        if "analytical" in category:
            return "analytical"
        return "document"
    except Exception as e:
        print(f"Error classifying question: {e}")
        return "document"

@app.post("/chat")
def chat(req: ChatRequest):
    role = req.role.lower()
    question = req.question
    
    # 1. Determine if analytical query
    query_type = classify_question(question)
    print(f"Question classified as: {query_type}")
    
    if query_type == "analytical":
        # Check permissions for SQL database RAG
        if role not in ["billing_executive", "admin"]:
            return {
                "answer": f"Access Denied: As a {role}, you do not have permission to view analytical billing claims or maintenance databases. SQL query generation is restricted to billing executives and administrators.",
                "sources": [],
                "retrieval_type": "sql_rag_blocked",
                "role": role
            }
            
        result = sql_rag_chain(question)
        return {
            "answer": result["answer"],
            "sources": [{"source_document": "Database: mediassist.db", "section_title": f"SQL: {result['sql_query']}", "collection": "SQL Database"}],
            "retrieval_type": "sql_rag",
            "role": role
        }
        
    else:
        # Document search RAG
        # First, run search WITHOUT filter to see if the content is restricted
        unfiltered_results = hybrid_search(question, "admin", limit=3)
        
        # Check if the top unfiltered result belongs to a collection the user cannot access
        allowed_collections = ROLE_COLLECTIONS.get(role, ["general"])
        
        if unfiltered_results:
            top_payload = unfiltered_results[0].payload
            top_collection = top_payload.get("collection", "general")
            
            if top_collection not in allowed_collections:
                # User is attempting to access restricted collection documents
                readable_list = ", ".join(allowed_collections)
                return {
                    "answer": f"Access Denied: As a {role}, you don't have access to {top_collection} documents. I can only answer questions from the following permitted collections: {readable_list}.",
                    "sources": [],
                    "retrieval_type": "hybrid_rag_blocked",
                    "role": role
                }
                
        # Run normal hybrid RAG with RBAC filter
        result = hybrid_rag_chain(question, role)
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "retrieval_type": "hybrid_rag",
            "role": role
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
