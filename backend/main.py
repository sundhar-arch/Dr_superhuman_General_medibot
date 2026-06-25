import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel
from groq import Groq

from database import sql_rag_chain
from retrieval import hybrid_rag_chain, warmup_models

load_dotenv()

app = FastAPI(title="Dr. Superhuman General MediBot API")

# C4 fix: explicit origin instead of wildcard; credentials=False for bearer-token flow
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MOCK_USERS = {
    "dr.mehta":     {"password": "password", "role": "doctor"},
    "nurse.priya":  {"password": "password", "role": "nurse"},
    "billing.ravi": {"password": "password", "role": "billing_executive"},
    "tech.anand":   {"password": "password", "role": "technician"},
    "admin.sys":    {"password": "password", "role": "admin"}
}

ROLE_COLLECTIONS = {
    "doctor":            ["clinical", "nursing", "general"],
    "nurse":             ["nursing", "general"],
    "billing_executive": ["billing", "general"],
    "technician":        ["equipment", "general"],
    "admin":             ["clinical", "nursing", "billing", "equipment", "general"]
}


# C1 fix: token verified server-side; role never taken from request body
def verify_token(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[len("Bearer "):]
    # Token format: token-{username}-{role}  (usernames use dots, not hyphens — safe split)
    parts = token.split("-", 2)
    if len(parts) != 3 or parts[0] != "token":
        raise HTTPException(status_code=401, detail="Invalid token")
    username, role = parts[1], parts[2]
    user = MOCK_USERS.get(username)
    if not user or user["role"] != role:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"username": username, "role": role}


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    question: str


# C10 fix: models loaded eagerly at startup — no race on first concurrent request
@app.on_event("startup")
def startup_event():
    warmup_models()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/login")
def login(req: LoginRequest):
    user = MOCK_USERS.get(req.username.lower())
    if not user or user["password"] != req.password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = f"token-{req.username}-{user['role']}"
    return {"token": token, "role": user["role"], "username": req.username}


# C9 fix: requires valid token; role derived from token, not URL param
@app.get("/collections")
def get_collections(current_user: dict = Depends(verify_token)):
    role = current_user["role"]
    return {"role": role, "collections": ROLE_COLLECTIONS.get(role, [])}


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
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10
        )
        category = completion.choices[0].message.content.strip().lower()
        return "analytical" if "analytical" in category else "document"
    except Exception as e:
        print(f"Error classifying question: {e}")
        return "document"


# C1 fix: role from verified token; C5+C6 fix: pre-check removed, Qdrant RBAC filter is authoritative
@app.post("/chat")
def chat(req: ChatRequest, current_user: dict = Depends(verify_token)):
    role = current_user["role"]
    question = req.question

    query_type = classify_question(question)
    print(f"Question classified as: {query_type} for role: {role}")

    if query_type == "analytical":
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

    result = hybrid_rag_chain(question, role)
    if not result["sources"]:
        allowed = ", ".join(ROLE_COLLECTIONS.get(role, ["general"]))
        return {
            "answer": f"Access Denied: No documents found in your permitted collections ({allowed}). The information you requested may be restricted to another role.",
            "sources": [],
            "retrieval_type": "hybrid_rag_blocked",
            "role": role
        }
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "retrieval_type": "hybrid_rag",
        "role": role
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
