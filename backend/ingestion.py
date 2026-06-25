import os
import glob
import uuid
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, SparseVectorParams, SparseIndexParams, PointStruct
from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from fastembed import TextEmbedding, SparseTextEmbedding

load_dotenv()

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_IN_MEMORY = os.getenv("QDRANT_IN_MEMORY", "True").lower() == "true"
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "medibot_documents")

ACCESS_ROLES_MAP = {
    "general": ["doctor", "nurse", "billing_executive", "technician", "admin"],
    "clinical": ["doctor", "admin"],
    "nursing": ["nurse", "doctor", "admin"],
    "billing": ["billing_executive", "admin"],
    "equipment": ["technician", "admin"]
}

def get_qdrant_client():
    if QDRANT_IN_MEMORY:
        # In-memory storage persists locally to a file so it stays between runs!
        db_path = Path(__file__).parent / "data" / "qdrant_storage"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Connecting to Local In-Memory Qdrant at {db_path}")
        return QdrantClient(path=str(db_path))
    else:
        print(f"Connecting to Qdrant Server at {QDRANT_HOST}:{QDRANT_PORT}")
        try:
            client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            # Ping to verify
            client.get_collections()
            return client
        except Exception as e:
            print(f"Failed to connect to Qdrant server: {e}. Falling back to in-memory storage.")
            db_path = Path(__file__).parent / "data" / "qdrant_storage"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            return QdrantClient(path=str(db_path))

# C7 fix: always drop and recreate so stale chunks from removed documents never survive
def recreate_collection(client: QdrantClient):
    existing = [col.name for col in client.get_collections().collections]
    if COLLECTION_NAME in existing:
        print(f"Dropping existing collection: {COLLECTION_NAME}")
        client.delete_collection(collection_name=COLLECTION_NAME)
    print(f"Creating Qdrant collection: {COLLECTION_NAME}")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=384,  # BAAI/bge-small-en-v1.5 output dimension
            distance=Distance.COSINE
        ),
        sparse_vectors_config={
            "text-sparse": SparseVectorParams(
                index=SparseIndexParams(on_disk=False)
            )
        }
    )
    print("Collection created successfully.")

def parse_and_chunk_documents():
    data_dir = Path(__file__).parent / "mediassist_data"
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found at {data_dir}")

    converter = DocumentConverter()
    chunker = HybridChunker()
    all_chunks = []

    # Map collections
    folders = ["general", "clinical", "nursing", "billing", "equipment"]
    
    for folder in folders:
        folder_path = data_dir / folder
        if not folder_path.exists():
            print(f"Folder not found: {folder_path}, skipping...")
            continue
            
        # Support PDF and Markdown
        files = glob.glob(str(folder_path / "*.pdf")) + glob.glob(str(folder_path / "*.md"))
        
        for file_path in files:
            file_name = Path(file_path).name
            print(f"Parsing file: {file_name} under collection: {folder}")
            
            try:
                result = converter.convert(file_path)
                doc = result.document
                chunks = list(chunker.chunk(doc))
                print(f"Generated {len(chunks)} chunks for {file_name}")
                
                for idx, chunk in enumerate(chunks):
                    # Section Context
                    headings = getattr(chunk.meta, "headings", [])
                    section_title = headings[-1] if headings else "General"
                    
                    # Prepend context to chunk text as required
                    contextualized_text = f"Document: {file_name} | Section: {section_title} | Content: {chunk.text}"
                    
                    all_chunks.append({
                        "text": contextualized_text,
                        "raw_text": chunk.text,
                        "metadata": {
                            "source_document": file_name,
                            "collection": folder,
                            "access_roles": ACCESS_ROLES_MAP[folder],
                            "section_title": section_title,
                            "chunk_type": "text" if not hasattr(chunk.meta, "doc_items") else "structural"
                        }
                    })
            except Exception as e:
                print(f"Error parsing file {file_path}: {e}")
                
    return all_chunks

def run_ingestion():
    client = get_qdrant_client()
    recreate_collection(client)
    
    print("Starting document parsing...")
    chunks = parse_and_chunk_documents()
    print(f"Parsing complete. Total chunks generated: {len(chunks)}")
    
    if not chunks:
        print("No chunks generated. Ingestion finished.")
        return

    print("Initializing embedding models...")
    dense_model = TextEmbedding("BAAI/bge-small-en-v1.5")
    sparse_model = SparseTextEmbedding("Qdrant/bm25")
    
    texts = [chunk["text"] for chunk in chunks]
    
    print("Generating dense embeddings...")
    dense_embeddings = list(dense_model.embed(texts))
    
    print("Generating sparse embeddings...")
    sparse_embeddings = list(sparse_model.embed(texts))
    
    print("Upserting points to Qdrant...")
    points = []
    for i, chunk in enumerate(chunks):
        dense_vec = dense_embeddings[i].tolist()
        sparse_vec = sparse_embeddings[i]
        
        # Convert sparse embedding to Qdrant format
        sparse_val = {
            "indices": sparse_vec.indices.tolist(),
            "values": sparse_vec.values.tolist()
        }
        
        # C7 fix: content-derived UUID so the same doc+chunk always maps to the same ID
        point_id = str(uuid.uuid5(
            uuid.NAMESPACE_DNS,
            f"{chunk['metadata']['source_document']}:{i}"
        ))
        points.append(
            PointStruct(
                id=point_id,
                vector={
                    "": dense_vec,
                    "text-sparse": sparse_val
                },
                payload={
                    "text": chunk["text"],
                    "raw_text": chunk["raw_text"],
                    **chunk["metadata"]
                }
            )
        )
        
    # Batch upsert
    batch_size = 100
    for idx in range(0, len(points), batch_size):
        batch = points[idx:idx+batch_size]
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=batch
        )
        print(f"Upserted batch {idx // batch_size + 1}/{((len(points)-1)//batch_size)+1}")
        
    print("Ingestion complete. Qdrant storage successfully populated.")

if __name__ == "__main__":
    run_ingestion()
