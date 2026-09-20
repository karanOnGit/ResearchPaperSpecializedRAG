import os
import json
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
from app.config import config
from app.okf.models import DocumentChunk

class VectorManager:
    """Vector Index manager for chunk embeddings and semantic similarity search.

    Uses ChromaDB with local persistent storage, storing chunks, embeddings,
    and structured metadata.
    """

    def __init__(self, persist_dir: Path = None, collection_name: str = "okf_chunks"):
        self.persist_dir = str(persist_dir or config.vector_db_dir)
        self.collection_name = collection_name
        self.client = None
        self.collection = None
        self.embedding_fn = None
        self._init_vector_store()

    def _init_vector_store(self):
        """Initialize ChromaDB with sentence-transformers or default embeddings."""
        try:
            import chromadb
            from chromadb.config import Settings
            from chromadb.utils import embedding_functions

            self.client = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=Settings(anonymized_telemetry=False)
            )

            # Use sentence-transformers embedding function if available
            try:
                self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name="all-MiniLM-L6-v2"
                )
            except Exception as ef_err:
                print(f"[VectorManager] SentenceTransformer init note: {ef_err}. Using default Chroma embedding.")
                self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()

            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )
            print(f"[VectorManager] ChromaDB collection '{self.collection_name}' initialized at {self.persist_dir}")
        except Exception as e:
            print(f"[VectorManager] ChromaDB initialization warning: {e}. Fallback to internal vector store.")
            self._init_memory_fallback()

    def _init_memory_fallback(self):
        """Simple in-memory vector store fallback with TF-IDF/keyword similarity."""
        self._memory_chunks: Dict[str, DocumentChunk] = {}
        fallback_file = Path(self.persist_dir) / "memory_chunks.json"
        if fallback_file.exists():
            try:
                with open(fallback_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        chunk = DocumentChunk(**item)
                        self._memory_chunks[chunk.chunk_id] = chunk
            except Exception:
                pass

    def add_chunks(self, chunks: List[DocumentChunk]):
        """Index a batch of DocumentChunks into the vector store."""
        if not chunks:
            return

        if self.collection:
            ids = []
            documents = []
            metadatas = []

            for c in chunks:
                ids.append(c.chunk_id)
                documents.append(c.cleaned_content)
                metadatas.append({
                    "doc_id": c.doc_id,
                    "chunk_id": c.chunk_id,
                    "source_title": c.source_title,
                    "source_type": c.source_type,
                    "page_number": c.page_number if c.page_number is not None else -1,
                    "section": c.section or "",
                    "chunk_index": c.chunk_index,
                    "token_count": c.token_count,
                    "concepts": json.dumps(c.concepts),
                    "source_path_or_url": c.metadata.get("source_path_or_url", "")
                })

            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
        else:
            for c in chunks:
                self._memory_chunks[c.chunk_id] = c
            # Persist memory chunks
            fallback_file = Path(self.persist_dir) / "memory_chunks.json"
            fallback_file.parent.mkdir(parents=True, exist_ok=True)
            with open(fallback_file, "w", encoding="utf-8") as f:
                json.dump([c.model_dump() for c in self._memory_chunks.values()], f, indent=2)

    def search(
        self,
        query: str,
        top_k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """Dense semantic search returning top matching DocumentChunks with similarity scores."""
        if not query.strip():
            return []

        results: List[Tuple[DocumentChunk, float]] = []

        if self.collection:
            query_kwargs = {
                "query_texts": [query],
                "n_results": min(top_k, max(1, self.collection.count())),
            }
            if filter_dict:
                query_kwargs["where"] = filter_dict

            try:
                res = self.collection.query(**query_kwargs)
            except Exception as e:
                print(f"[VectorManager] Query error: {e}")
                return []

            if res and res.get("ids") and len(res["ids"][0]) > 0:
                ids = res["ids"][0]
                docs = res["documents"][0]
                metadatas = res["metadatas"][0]
                distances = res["distances"][0] if res.get("distances") else [0.5] * len(ids)

                for cid, doc_text, meta, dist in zip(ids, docs, metadatas, distances):
                    # Cosine distance to similarity: similarity = 1 - distance (or max(0, 1 - dist))
                    similarity = max(0.0, min(1.0, 1.0 - dist))

                    concepts_list = []
                    if meta.get("concepts"):
                        try:
                            concepts_list = json.loads(meta["concepts"])
                        except Exception:
                            pass

                    chunk = DocumentChunk(
                        chunk_id=meta.get("chunk_id", cid),
                        doc_id=meta.get("doc_id", ""),
                        source_title=meta.get("source_title", ""),
                        source_type=meta.get("source_type", ""),
                        content=doc_text,
                        cleaned_content=doc_text,
                        page_number=meta.get("page_number") if meta.get("page_number", -1) != -1 else None,
                        section=meta.get("section", ""),
                        chunk_index=meta.get("chunk_index", 0),
                        token_count=meta.get("token_count", 0),
                        concepts=concepts_list,
                        metadata={"source_path_or_url": meta.get("source_path_or_url", "")}
                    )
                    results.append((chunk, similarity))
        else:
            # Fallback keyword match
            q_words = set(query.lower().split())
            scored = []
            for c in self._memory_chunks.values():
                c_words = set(c.cleaned_content.lower().split())
                overlap = len(q_words.intersection(c_words))
                if overlap > 0:
                    score = overlap / (len(q_words) + 1)
                    scored.append((c, score))
            scored.sort(key=lambda x: x[1], reverse=True)
            results = scored[:top_k]

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        if self.collection:
            total_vectors = self.collection.count()
            return {
                "engine": "ChromaDB",
                "collection": self.collection_name,
                "total_chunks": total_vectors,
                "persist_dir": self.persist_dir,
            }
        else:
            return {
                "engine": "MemoryFallback",
                "collection": self.collection_name,
                "total_chunks": len(getattr(self, "_memory_chunks", {})),
                "persist_dir": self.persist_dir,
            }
