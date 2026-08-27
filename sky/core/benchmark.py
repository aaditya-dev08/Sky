"""Performance benchmarking utilities."""

import time
from pathlib import Path
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class Benchmark:
    """Simple performance benchmark."""
    
    @staticmethod
    def measure_startup() -> Dict[str, float]:
        """Measure CLI startup time."""
        start = time.perf_counter()
        
        # Import core modules
        import sky.core  # noqa
        import sky.memory  # noqa
        
        end = time.perf_counter()
        return {"startup_ms": (end - start) * 1000}
    
    @staticmethod
    def measure_embedding() -> Dict[str, float]:
        """Measure embedding generation time."""
        from sky.memory.vectorstore import get_vector_store
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            store = get_vector_store(Path(tmpdir))
            
            start = time.perf_counter()
            embedding = store._get_embedding("test query")
            end = time.perf_counter()
            
            return {"embedding_ms": (end - start) * 1000, "dimension": len(embedding)}
