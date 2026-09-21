import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.config import config
from app.okf.models import OKFConcept, OKFRelationship, OKFSource

class MongoManager:
    """Manages MongoDB collections (documents, concepts, sources, relationships, chat_history)

    Supports direct MongoDB URI (local/Atlas) with automatic persistent JSON fallback
    if MongoDB is not running locally.
    """

    def __init__(self, uri: str = None, db_name: str = None):
        self.uri = uri if uri is not None else config.mongodb_uri
        self.db_name = db_name or config.database_name
        self.is_connected_to_live_mongo = False
        self.client = None
        self.db = None
        self.fallback_dir = config.mongo_fallback_dir
        self.fallback_dir.mkdir(parents=True, exist_ok=True)

        self._init_connection()

    def _init_connection(self):
        """Attempt connection to real MongoDB; fallback to persistent mock if unavailable."""
        if self.uri:
            try:
                import pymongo
                import certifi
                self.client = pymongo.MongoClient(
                    self.uri,
                    tlsCAFile=certifi.where(),
                    serverSelectionTimeoutMS=5000
                )
                # Test connection
                self.client.server_info()
                self.db = self.client[self.db_name]
                self.is_connected_to_live_mongo = True
                print(f"[MongoManager] Connected to live MongoDB at {self.uri[:35]}... (DB: {self.db_name})")
                return
            except Exception as e:
                print(f"[MongoManager] Could not connect to live MongoDB ({e}). Falling back to persistent store.")

        # Persistent Mock Fallback
        self._init_fallback_store()

    def _init_fallback_store(self):
        """Initialize local file-backed collection manager using mongomock or internal JSON."""
        try:
            import mongomock
            self.client = mongomock.MongoClient()
            self.db = self.client[self.db_name]
            self._load_fallback_from_disk()
            print(f"[MongoManager] Using persistent embedded MongoDB store at {self.fallback_dir}")
        except Exception as e:
            print(f"[MongoManager] mongomock initialization note: {e}")

    def _load_fallback_from_disk(self):
        """Load collections from disk on startup."""
        collections = ["documents", "concepts", "relationships", "sources", "chat_history"]
        for col_name in collections:
            file_path = self.fallback_dir / f"{col_name}.json"
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data:
                            self.db[col_name].insert_many(data)
                except Exception as e:
                    print(f"[MongoManager] Error loading fallback file {file_path}: {e}")

    def _persist_fallback_to_disk(self, col_name: str):
        """Save a collection to disk when using the fallback store."""
        if self.is_connected_to_live_mongo:
            return
        file_path = self.fallback_dir / f"{col_name}.json"
        try:
            records = list(self.db[col_name].find())
            # Convert ObjectIds to strings if necessary
            clean_records = []
            for r in records:
                r_clean = dict(r)
                if "_id" in r_clean:
                    r_clean["_id"] = str(r_clean["_id"])
                clean_records.append(r_clean)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(clean_records, f, indent=2, default=str)
        except Exception as e:
            print(f"[MongoManager] Error persisting fallback file {file_path}: {e}")

    # ==================== Documents ====================

    def save_document(self, doc_data: Dict[str, Any]) -> str:
        """Insert or update a document in the 'documents' collection."""
        doc_id = doc_data.get("_id") or doc_data.get("id")
        doc_data["_id"] = doc_id
        doc_data["updated_at"] = datetime.utcnow().isoformat()
        
        self.db.documents.replace_one({"_id": doc_id}, doc_data, upsert=True)
        self._persist_fallback_to_disk("documents")
        return doc_id

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        return self.db.documents.find_one({"_id": doc_id})

    def list_documents(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.db.documents.find().sort("created_at", -1).limit(limit))

    # ==================== Sources ====================

    def save_source(self, source: OKFSource) -> str:
        data = source.model_dump()
        data["_id"] = source.id
        self.db.sources.replace_one({"_id": source.id}, data, upsert=True)
        self._persist_fallback_to_disk("sources")
        return source.id

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        return self.db.sources.find_one({"_id": source_id})

    def list_sources(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.db.sources.find().sort("created_at", -1).limit(limit))

    # ==================== Concepts ====================

    def save_concepts(self, concepts: List[OKFConcept]):
        """Save concepts, updating mention counts if existing."""
        for c in concepts:
            c_dict = c.model_dump()
            c_dict["_id"] = c.id
            existing = self.db.concepts.find_one({"_id": c.id})
            if existing:
                # Update mention count and merge aliases
                aliases = list(set(existing.get("aliases", []) + c.aliases))
                mention_count = existing.get("mention_count", 1) + 1
                self.db.concepts.update_one(
                    {"_id": c.id},
                    {"$set": {"aliases": aliases, "mention_count": mention_count, "definition": c.definition}}
                )
            else:
                self.db.concepts.insert_one(c_dict)
        self._persist_fallback_to_disk("concepts")

    def find_concepts_by_names_or_keywords(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """Search concepts by name, aliases, or definition keywords."""
        if not keywords:
            return []
        query_conditions = []
        for kw in keywords:
            kw_clean = kw.strip()
            if len(kw_clean) < 3:
                continue
            # Regex match
            regex = {"$regex": kw_clean, "$options": "i"}
            query_conditions.extend([
                {"name": regex},
                {"aliases": regex},
                {"definition": regex},
                {"tags": regex}
            ])
        if not query_conditions:
            return []
        return list(self.db.concepts.find({"$or": query_conditions}))

    def list_concepts(self, limit: int = 200) -> List[Dict[str, Any]]:
        return list(self.db.concepts.find().sort("mention_count", -1).limit(limit))

    # ==================== Relationships ====================

    def save_relationships(self, relationships: List[OKFRelationship]):
        """Save relationship edges in graph collection."""
        for r in relationships:
            r_dict = r.model_dump()
            r_dict["_id"] = r.id
            self.db.relationships.replace_one({"_id": r.id}, r_dict, upsert=True)
        self._persist_fallback_to_disk("relationships")

    def get_related_edges(self, concept_names: List[str]) -> List[Dict[str, Any]]:
        """1-hop graph search for relationships connecting to any concept in concept_names."""
        if not concept_names:
            return []
        query = {
            "$or": [
                {"source": {"$in": concept_names}},
                {"target": {"$in": concept_names}}
            ]
        }
        return list(self.db.relationships.find(query))

    def list_relationships(self, limit: int = 200) -> List[Dict[str, Any]]:
        return list(self.db.relationships.find().limit(limit))

    # ==================== Chat History ====================

    def save_chat_turn(self, session_id: str, query: str, answer_data: Dict[str, Any]) -> str:
        turn = {
            "session_id": session_id,
            "query": query,
            "answer": answer_data.get("answer", ""),
            "sources": answer_data.get("sources", []),
            "citations": answer_data.get("citations", []),
            "related_concepts": [c.get("name") if isinstance(c, dict) else c.name for c in answer_data.get("related_concepts", [])],
            "confidence_provenance": answer_data.get("confidence_provenance", {}),
            "timestamp": datetime.utcnow().isoformat(),
        }
        res = self.db.chat_history.insert_one(turn)
        self._persist_fallback_to_disk("chat_history")
        return str(res.inserted_id)

    def get_chat_history(self, session_id: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        query = {"session_id": session_id} if session_id else {}
        return list(self.db.chat_history.find(query).sort("timestamp", -1).limit(limit))

    # ==================== Storage Stats ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get collection counts and storage mode status."""
        return {
            "is_live_mongo": self.is_connected_to_live_mongo,
            "database_name": self.db_name,
            "counts": {
                "documents": self.db.documents.count_documents({}),
                "concepts": self.db.concepts.count_documents({}),
                "relationships": self.db.relationships.count_documents({}),
                "sources": self.db.sources.count_documents({}),
                "chat_history": self.db.chat_history.count_documents({}),
            }
        }

    def clear_all(self):
        """Purge all documents, concepts, relationships, sources, and chat_history."""
        collections = ["documents", "concepts", "relationships", "sources", "chat_history"]
        for col in collections:
            self.db[col].delete_many({})
            self._persist_fallback_to_disk(col)
