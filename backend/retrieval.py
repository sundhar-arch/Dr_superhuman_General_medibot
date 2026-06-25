import os
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchAny, Prefetch, FusionQuery, Fusion
from fastembed import TextEmbedding, SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from groq import Groq

load_dotenv()

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_IN_MEMORY = os.getenv("QDRANT_IN_MEMORY", "True").lower() == "true"
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "medibot_documents")

# Initialize models globally (cached/lazy loaded)
_dense_model = None
_sparse_model = None
_reranker = None
_qdrant_client = None

def get_dense_model():
    global _dense_model
    if _dense_model is None:
        _dense_model = TextEmbedding("BAAI/bge-small-en-v1.5")
    return _dense_model

def get_sparse_model():
    global _sparse_model
    if _sparse_model is None:
        _sparse_model = SparseTextEmbedding("Qdrant/bm25")
    return _sparse_model

def get_reranker():
    global _reranker
    if _reranker is None:
        _reranker = TextCrossEncoder("BAAI/bge-reranker-base")
    return _reranker

def get_qdrant_client():
    global _qdrant_client
    if _qdrant_client is None:
        if QDRANT_IN_MEMORY:
            db_path = Path(__file__).parent / "data" / "qdrant_storage"
            print(f"[Retrieval] Connecting to local Qdrant path: {db_path}")
            _qdrant_client = QdrantClient(path=str(db_path))
        else:
            print(f"[Retrieval] Connecting to server Qdrant: {QDRANT_HOST}:{QDRANT_PORT}")
            try:
                _qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
                _qdrant_client.get_collections()
            except Exception as e:
                print(f"[Retrieval] Failed to connect: {e}. Falling back to in-memory path.")
                db_path = Path(__file__).parent / "data" / "qdrant_storage"
                _qdrant_client = QdrantClient(path=str(db_path))
    return _qdrant_client


# C10 fix: called at startup so all four singletons are initialized before the first request
def warmup_models():
    print("[Retrieval] Warming up models and Qdrant client...")
    get_dense_model()
    get_sparse_model()
    get_reranker()
    get_qdrant_client()
    print("[Retrieval] Warmup complete.")


def hybrid_search(query: str, role: str, limit: int = 10) -> list:
    client = get_qdrant_client()
    
    # 1. Embed query
    dense_model = get_dense_model()
    sparse_model = get_sparse_model()
    
    dense_query = next(dense_model.embed([query])).tolist()
    sparse_query = next(sparse_model.embed([query]))
    
    sparse_val = {
        "indices": sparse_query.indices.tolist(),
        "values": sparse_query.values.tolist()
    }
    
    # 2. Build RBAC filter
    # In Qdrant, we check if the user's role is in the access_roles payload array
    query_filter = Filter(
        must=[
            FieldCondition(
                key="access_roles",
                match=MatchAny(any=[role])
            )
        ]
    )
    
    # 3. Create Prefetches
    prefetch_dense = Prefetch(
        query=dense_query,
        using="",
        limit=limit
    )
    
    prefetch_sparse = Prefetch(
        query=sparse_val,
        using="text-sparse",
        limit=limit
    )
    
    # 4. Search and Fuse (RRF)
    # Qdrant client version 1.18 uses query_points for RRF fusion
    try:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[prefetch_dense, prefetch_sparse],
            query=FusionQuery(fusion=Fusion.RRF),
            query_filter=query_filter,
            limit=limit
        ).points
    except Exception as e:
        print(f"Error during Qdrant query_points: {e}. Attempting fallback search.")
        # Fallback to dense search if Fusion/BM25 has issues
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=dense_query,
            query_filter=query_filter,
            limit=limit
        )
        
    return results

def rerank_results(query: str, search_results: list, top_k: int = 3) -> list:
    if not search_results:
        return []
        
    reranker = get_reranker()
    
    # Extract text from results
    # Standard qdrant search results are ScoredPoint objects
    documents = [res.payload["text"] for res in search_results]
    
    # Rerank
    reranked = list(reranker.rerank(query, documents))
    
    # Sort by score descending
    reranked.sort(key=lambda x: x.score, reverse=True)
    
    # Build final subset
    final_results = []
    for item in reranked[:top_k]:
        idx = item.index
        orig_res = search_results[idx]
        final_results.append({
            "payload": orig_res.payload,
            "score": item.score
        })
        
    return final_results

def hybrid_rag_chain(question: str, role: str) -> dict:
    # Step 1: Hybrid retrieval
    candidates = hybrid_search(question, role, limit=10)
    
    # Step 2: Rerank
    top_chunks = rerank_results(question, candidates, top_k=3)
    
    if not top_chunks:
        return {
            "answer": "No relevant documents found or you do not have permission to view them.",
            "sources": []
        }
        
    # Step 3: LLM generation
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {
            "answer": "Error: GROQ_API_KEY is missing from environment.",
            "sources": []
        }
        
    client = Groq(api_key=api_key)
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    
    # Construct context
    context_blocks = []
    sources = []
    
    for c in top_chunks:
        payload = c["payload"]
        context_blocks.append(payload["text"])
        sources.append({
            "source_document": payload["source_document"],
            "section_title": payload["section_title"],
            "collection": payload["collection"]
        })
        
    context_str = "\n\n".join(context_blocks)
    
    system_prompt = f"""You are MediBot, an internal intelligent clinical assistant for MediAssist Health Network.
Answer the staff member's question accurately and safely, based strictly on the retrieved document context below.
If the answer is not in the context, state that you cannot find the information in your documents.

Retrieved Context:
{context_str}
"""

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        answer = completion.choices[0].message.content
        
        # Remove duplicate sources
        unique_sources = []
        for src in sources:
            if src not in unique_sources:
                unique_sources.append(src)
                
        return {
            "answer": answer.strip(),
            "sources": unique_sources
        }
    except Exception as e:
        print(f"Error in Hybrid RAG chain: {e}")
        return {
            "answer": "Unable to generate a response at this time. Please try again.",
            "sources": []
        }
