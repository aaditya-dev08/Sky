"""Vector store with fastembed (ONNX Runtime) - no PyTorch dependency."""

import json
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Any
import logging

import lancedb
from lancedb.table import Table
import pyarrow as pa

logger = logging.getLogger(__name__)


class VectorStoreManager:
    """LanceDB vector store with fastembed embeddings."""
    
    _instance: Optional['VectorStoreManager'] = None
    _embedding_model = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, db_path: Path, model_name: str = "BAAI/bge-small-en-v1.5"):
        """Initialize vector store with fastembed."""
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.model_name = model_name
        
        # Initialize fastembed (lazy load - minimal startup cost)
        self._embedding_model = None  # Lazy loaded
        self._embedding_dim = 384  # bge-small-en-v1.5 is 384d
        
        # Initialize LanceDB
        self._db = lancedb.connect(str(self.db_path))
        self._table = self._get_or_create_table()
        
        self._initialized = True
        logger.info(f"VectorStore initialized at {self.db_path} with {model_name}")
    
    @property
    def embedding_model(self):
        """Lazy load embedding model."""
        if self._embedding_model is None:
            try:
                from fastembed import TextEmbedding
                self._embedding_model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(Path.home() / ".sky" / "cache" / "fastembed")
                )
                logger.info(f"Embedding model loaded: {self.model_name}")
            except ImportError as e:
                logger.error(f"fastembed not installed: {e}")
                raise
        return self._embedding_model
    
    def _get_or_create_table(self) -> Table:
        """Get or create the code_chunks table."""
        table_name = "code_chunks"
        
        if table_name in self._db.table_names():
            return self._db.open_table(table_name)
        
        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("file_path", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("content", pa.string()),
            pa.field("embedding", pa.list_(pa.float32(), 384)),
            pa.field("content_hash", pa.string()),
            pa.field("last_modified", pa.string()),
            pa.field("language", pa.string()),
            pa.field("chunk_type", pa.string()),
        ])
        
        return self._db.create_table(table_name, schema=schema)
    
    def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding using fastembed."""
        try:
            # fastembed returns a generator
            embeddings = list(self.embedding_model.embed([text]))
            if embeddings:
                return embeddings[0].tolist()
            return [0.0] * self._embedding_dim
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return [0.0] * self._embedding_dim
    
    def _get_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts in batch."""
        try:
            embeddings = list(self.embedding_model.embed(texts))
            return [e.tolist() for e in embeddings]
        except Exception as e:
            logger.error(f"Batch embedding error: {e}")
            return [[0.0] * self._embedding_dim for _ in texts]
    
    def add_chunk(
        self,
        file_path: str,
        chunk_index: int,
        content: str,
        content_hash: str,
        last_modified: str,
        language: str = "text",
        chunk_type: str = "text"
    ) -> str:
        """Add a chunk to the vector store."""
        chunk_id = str(uuid.uuid4())
        embedding = self._get_embedding(content)
        
        data = [{
            "id": chunk_id,
            "file_path": file_path,
            "chunk_index": chunk_index,
            "content": content,
            "embedding": embedding,
            "content_hash": content_hash,
            "last_modified": last_modified,
            "language": language,
            "chunk_type": chunk_type,
        }]
        
        self._table.add(data)
        return chunk_id
    
    def add_chunks_batch(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """Add multiple chunks in batch for performance."""
        if not chunks:
            return []
        
        texts = [c["content"] for c in chunks]
        embeddings = self._get_batch_embeddings(texts)
        
        data = []
        for i, chunk in enumerate(chunks):
            data.append({
                "id": str(uuid.uuid4()),
                "file_path": chunk["file_path"],
                "chunk_index": chunk["chunk_index"],
                "content": chunk["content"],
                "embedding": embeddings[i] if i < len(embeddings) else [0.0] * self._embedding_dim,
                "content_hash": chunk["content_hash"],
                "last_modified": chunk["last_modified"],
                "language": chunk.get("language", "text"),
                "chunk_type": chunk.get("chunk_type", "text"),
            })
        
        self._table.add(data)
        return [d["id"] for d in data]
    
    def delete_chunks(self, file_path: str) -> None:
        """Delete all chunks for a file."""
        self._table.delete(f"file_path = '{file_path}'")
    
    def delete_file(self, file_path: str) -> None:
        """Delete all chunks for a file (alias)."""
        self.delete_chunks(file_path)
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        file_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar chunks."""
        try:
            embedding = self._get_embedding(query)
            
            query_builder = self._table.search(embedding)
            
            if file_filter:
                query_builder = query_builder.where(f"file_path LIKE '{file_filter}%'")
            
            results = query_builder.limit(top_k).to_list()
            
            return [{
                "id": r["id"],
                "file_path": r["file_path"],
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "score": r["_distance"],
                "language": r.get("language", "text"),
                "chunk_type": r.get("chunk_type", "text"),
            } for r in results]
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def get_file_chunks(self, file_path: str) -> List[Dict[str, Any]]:
        """Get all chunks for a file."""
        try:
            results = self._table.search().where(f"file_path = '{file_path}'").limit(1000).to_list()
            return sorted(results, key=lambda x: x.get("chunk_index", 0))
        except Exception as e:
            logger.error(f"Get file chunks error: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        try:
            count = self._table.count_rows()
            # Get unique files
            results = self._table.search().limit(10000).to_list()
            unique_files = len(set(r["file_path"] for r in results))
            
            return {
                "total_chunks": count,
                "total_files": unique_files,
                "embedding_dim": self._embedding_dim,
                "model_name": self.model_name,
                "provider": "fastembed",
            }
        except Exception as e:
            logger.error(f"Get stats error: {e}")
            return {
                "total_chunks": 0,
                "total_files": 0,
                "embedding_dim": self._embedding_dim,
                "model_name": self.model_name,
                "provider": "fastembed",
                "error": str(e),
            }
    
    def update_chunk(self, chunk_id: str, content: str, content_hash: str, last_modified: str) -> None:
        """Update a chunk."""
        results = self._table.search().where(f"id = '{chunk_id}'").limit(1).to_list()
        if not results:
            return
            
        old = results[0]
        self._table.delete(f"id = '{chunk_id}'")
        
        embedding = self._get_embedding(content)
        data = [{
            "id": chunk_id,
            "file_path": old["file_path"],
            "chunk_index": old["chunk_index"],
            "content": content,
            "embedding": embedding,
            "content_hash": content_hash,
            "last_modified": last_modified,
            "language": old.get("language", "text"),
            "chunk_type": old.get("chunk_type", "text"),
        }]
        self._table.add(data)
    
    def close(self) -> None:
        """Close the vector store connection."""
        # LanceDB handles this via context manager
        pass
    
    def clear(self) -> None:
        """Clear all data (for testing)."""
        table_name = "code_chunks"
        if table_name in self._db.table_names():
            self._db.drop_table(table_name)
        self._table = self._get_or_create_table()


def get_vector_store(db_path: Path, model_name: str = "BAAI/bge-small-en-v1.5") -> VectorStoreManager:
    """Get or create the vector store singleton."""
    return VectorStoreManager(db_path, model_name)
