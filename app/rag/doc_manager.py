# -*- coding: utf-8 -*-
"""
Document Management & Vector Retrieval System.

Components:
- DocumentManager: file CRUD in data/documents/
- HashRegistry: SHA-256 change detection
- QueryCache: query result caching with auto-invalidation
- DocVectorManager: orchestrates sync + smart query
"""

import os
import json
import hashlib
import time
import shutil

from app.config import logger


class DocumentManager:
    """Manages documents in data/documents/ folder."""

    DOCS_DIR = "./data/documents"
    SUPPORTED_EXTENSIONS = {".txt", ".md"}

    def __init__(self):
        os.makedirs(self.DOCS_DIR, exist_ok=True)

    def list_documents(self):
        """List all documents with metadata."""
        docs = []
        if not os.path.exists(self.DOCS_DIR):
            return docs
        for f in sorted(os.listdir(self.DOCS_DIR)):
            ext = os.path.splitext(f)[1].lower()
            if ext not in self.SUPPORTED_EXTENSIONS:
                continue
            path = os.path.join(self.DOCS_DIR, f)
            if not os.path.isfile(path):
                continue
            docs.append({
                "name": f,
                "size": os.path.getsize(path),
                "modified": os.path.getmtime(path),
            })
        return docs

    def read_document(self, name):
        """Read document content by name."""
        path = os.path.join(self.DOCS_DIR, name)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def add_document(self, name, content):
        """Add or overwrite a document."""
        path = os.path.join(self.DOCS_DIR, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Document added: %s (%d chars)", name, len(content))
        return path

    def delete_document(self, name):
        """Delete a document by name."""
        path = os.path.join(self.DOCS_DIR, name)
        if os.path.exists(path):
            os.remove(path)
            logger.info("Document deleted: %s", name)
            return True
        return False


class HashRegistry:
    """Tracks SHA-256 hashes of documents for change detection."""

    HASH_FILE = "./data/vectorstore/doc_hashes.json"

    def __init__(self):
        self.hashes = {}
        self.load()

    def load(self):
        if os.path.exists(self.HASH_FILE):
            try:
                with open(self.HASH_FILE, "r", encoding="utf-8") as f:
                    self.hashes = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.hashes = {}

    def save(self):
        os.makedirs(os.path.dirname(self.HASH_FILE), exist_ok=True)
        with open(self.HASH_FILE, "w", encoding="utf-8") as f:
            json.dump(self.hashes, f, ensure_ascii=False, indent=2)

    @staticmethod
    def compute_hash(content):
        """Compute SHA-256 hash of text content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get_signature(self):
        """Get a short signature representing the current state of all docs."""
        if not self.hashes:
            return "empty"
        combined = json.dumps(self.hashes, sort_keys=True)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]

    def detect_changes(self, doc_manager):
        """
        Compare stored hashes with current files.
        Returns: (added, modified, deleted) lists of filenames.
        """
        current_files = doc_manager.list_documents()
        current_names = {d["name"] for d in current_files}
        stored_names = set(self.hashes.keys())

        added = []
        modified = []
        deleted = []

        for d in current_files:
            name = d["name"]
            content = doc_manager.read_document(name)
            if content is None:
                continue
            current_hash = self.compute_hash(content)

            if name not in self.hashes:
                added.append(name)
            elif self.hashes[name] != current_hash:
                modified.append(name)

            self.hashes[name] = current_hash

        for name in stored_names:
            if name not in current_names:
                deleted.append(name)
                del self.hashes[name]

        return added, modified, deleted


class QueryCache:
    """Caches query results with TTL and doc-signature invalidation."""

    CACHE_FILE = "./data/vectorstore/query_cache.json"
    TTL = 3600  # 1 hour
    MAX_ENTRIES = 200

    def __init__(self):
        self.cache = {}
        self.load()

    def load(self):
        if os.path.exists(self.CACHE_FILE):
            try:
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.cache = {}

    def save(self):
        os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
        with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def _make_key(self, query, doc_signature):
        raw = f"{query}:{doc_signature}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, query, doc_signature):
        """Get cached result if valid (not expired, signature matches)."""
        key = self._make_key(query, doc_signature)
        if key not in self.cache:
            return None
        entry = self.cache[key]
        if time.time() - entry["timestamp"] > self.TTL:
            del self.cache[key]
            return None
        return entry["result"]

    def set(self, query, doc_signature, result):
        """Cache a query result."""
        key = self._make_key(query, doc_signature)
        self.cache[key] = {
            "query": query[:100],
            "timestamp": time.time(),
            "result": result,
        }
        # Evict oldest entries if over limit
        if len(self.cache) > self.MAX_ENTRIES:
            sorted_keys = sorted(
                self.cache.keys(),
                key=lambda k: self.cache[k]["timestamp"]
            )
            for k in sorted_keys[: len(self.cache) - self.MAX_ENTRIES]:
                del self.cache[k]
        self.save()

    def clear(self):
        self.cache = {}
        if os.path.exists(self.CACHE_FILE):
            os.remove(self.CACHE_FILE)


class DocVectorManager:
    """
    Orchestrates document management, vector store sync, and cached retrieval.

    Usage:
        manager = DocVectorManager()
        manager.sync()                    # Sync docs -> vector store
        results = manager.query("question")  # Cached vector search
    """

    SYNC_INTERVAL = 60  # seconds between auto-sync checks

    def __init__(self):
        self.doc_manager = DocumentManager()
        self.hash_registry = HashRegistry()
        self.query_cache = QueryCache()
        self.last_sync_time = 0
        self._vector_store = None

    @property
    def vector_store(self):
        """Lazy-load vector store."""
        if self._vector_store is None:
            from app.rag.vectorstore import vector_store as vs
            self._vector_store = vs
        return self._vector_store

    def get_status(self):
        """Get current system status."""
        docs = self.doc_manager.list_documents()
        return {
            "total_documents": len(docs),
            "documents": docs,
            "doc_signature": self.hash_registry.get_signature(),
            "cache_entries": len(self.query_cache.cache),
            "vector_store_ready": self.vector_store.vector_store is not None,
            "index_size": (
                self.vector_store.vector_store.index.ntotal
                if self.vector_store.vector_store
                else 0
            ),
        }

    def sync(self, force_rebuild=False):
        """
        Sync documents with vector store.

        Args:
            force_rebuild: If True, rebuild entire index from scratch.

        Returns:
            Dict with sync status and statistics.
        """
        # Ensure embeddings are loaded
        if not self.vector_store.embeddings:
            self.vector_store.load_embeddings()

        # Detect changes
        added, modified, deleted = self.hash_registry.detect_changes(
            self.doc_manager
        )

        has_changes = bool(added or modified or deleted)

        if not has_changes and not force_rebuild:
            logger.info("[DocSync] No changes detected")
            self.last_sync_time = time.time()
            return {
                "status": "no_changes",
                "added": 0,
                "modified": 0,
                "deleted": 0,
            }

        # Decide update strategy
        if force_rebuild or modified or deleted:
            return self._full_rebuild()
        else:
            # Only additions -> incremental
            return self._incremental_update(added)

    def _full_rebuild(self):
        """Full rebuild: recreate FAISS index from all documents."""
        from langchain_core.documents import Document
        # NOTE: FAISS has no standalone package yet
        from langchain_community.vectorstores import FAISS
        from app.rag.vectorstore import text_splitter

        docs_info = self.doc_manager.list_documents()
        all_texts = []
        for d in docs_info:
            content = self.doc_manager.read_document(d["name"])
            if content:
                all_texts.append(content)

        if not all_texts:
            logger.warning("[DocSync] No documents to index")
            self.hash_registry.save()
            self.query_cache.clear()
            return {"status": "full_rebuild", "total_docs": 0, "total_chunks": 0}

        # Delete old index
        index_path = self.vector_store.index_path
        if os.path.exists(index_path):
            shutil.rmtree(index_path)

        # Create documents and split into chunks
        documents = [Document(page_content=t) for t in all_texts]
        chunks = text_splitter.split_documents(documents)

        # Build new FAISS index
        self.vector_store.vector_store = FAISS.from_documents(
            chunks, self.vector_store.embeddings
        )
        self.vector_store.save_local()

        # Update registries
        self.hash_registry.save()
        self.query_cache.clear()
        self.last_sync_time = time.time()

        logger.info(
            "[DocSync] Full rebuild: %d docs -> %d chunks",
            len(all_texts), len(chunks)
        )
        return {
            "status": "full_rebuild",
            "total_docs": len(all_texts),
            "total_chunks": len(chunks),
        }

    def _incremental_update(self, added_files):
        """Incremental update: add only new documents to existing index."""
        from app.rag.vectorstore import text_splitter
        from langchain_core.documents import Document

        new_texts = []
        for name in added_files:
            content = self.doc_manager.read_document(name)
            if content:
                new_texts.append(content)

        if not new_texts:
            self.hash_registry.save()
            return {"status": "no_changes", "added": 0}

        # Split and add to existing index
        documents = [Document(page_content=t) for t in new_texts]
        chunks = text_splitter.split_documents(documents)

        if self.vector_store.vector_store is None:
            # No existing index, need to create one
            # NOTE: FAISS has no standalone package yet
            from langchain_community.vectorstores import FAISS
            self.vector_store.vector_store = FAISS.from_documents(
                chunks, self.vector_store.embeddings
            )
        else:
            self.vector_store.vector_store.add_documents(chunks)

        self.vector_store.save_local()
        self.hash_registry.save()
        self.query_cache.clear()
        self.last_sync_time = time.time()

        logger.info(
            "[DocSync] Incremental: added %d docs -> %d chunks",
            len(added_files), len(chunks)
        )
        return {
            "status": "incremental_update",
            "added": len(added_files),
            "new_chunks": len(chunks),
        }

    def query(self, question, k=3):
        """
        Smart query with caching.

        1. Auto-sync if SYNC_INTERVAL elapsed
        2. Check cache (keyed by query + doc signature)
        3. If cache miss, query vector store via MMR
        4. Cache and return result

        Args:
            question: Query string
            k: Number of results

        Returns:
            List of retrieved document texts.
        """
        # Auto-sync check
        if time.time() - self.last_sync_time > self.SYNC_INTERVAL:
            self.sync()
            self.last_sync_time = time.time()

        doc_signature = self.hash_registry.get_signature()

        # Try cache first
        cached = self.query_cache.get(question, doc_signature)
        if cached is not None:
            logger.info("[DocQuery] Cache hit for: %s", question[:50])
            return cached, True  # (results, from_cache)

        # Query vector store
        if self.vector_store.vector_store is None:
            self.vector_store.initialize()

        docs = self.vector_store.similarity_search(question, k=k)
        results = [doc.page_content for doc in docs]

        # Cache result
        self.query_cache.set(question, doc_signature, results)

        logger.info(
            "[DocQuery] Vector search for: %s -> %d results",
            question[:50], len(results)
        )
        return results, False  # (results, from_cache)


# Singleton
doc_vector_manager = DocVectorManager()
