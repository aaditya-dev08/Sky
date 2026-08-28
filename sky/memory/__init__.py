"""Project Context Memory Module."""

from typing import TYPE_CHECKING

from sky.memory.indexer import RepoIndexer
from sky.memory.vectorstore import VectorStoreManager

def get_vector_store(*args, **kwargs):
    from sky.memory.vectorstore import get_vector_store as _get_vector_store
    return _get_vector_store(*args, **kwargs)

def get_indexer(*args, **kwargs):
    from sky.memory.indexer import get_indexer as _get_indexer
    return _get_indexer(*args, **kwargs)

def search_context(*args, **kwargs):
    from sky.memory.indexer import search_context as _search_context
    return _search_context(*args, **kwargs)

__all__ = [
    "VectorStoreManager",
    "RepoIndexer",
    "get_vector_store",
    "get_indexer",
    "search_context",
]
