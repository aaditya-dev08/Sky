"""Diagnose SKY startup performance."""

import time
import sys
import importlib

def time_import(name):
    """Time an import."""
    start = time.perf_counter()
    try:
        module = importlib.import_module(name)
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, module
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, None

def main():
    print("=" * 60)
    print("SKY Startup Performance Diagnosis")
    print("=" * 60)
    
    # Test imports
    modules = [
        "sky",
        "sky.cli",
        "sky.config",
        "sky.config.schema",
        "sky.storage",
        "sky.storage.db",
        "sky.tools",
        "sky.tools.registry",
        "sky.core",
        "sky.core.router",
        "sky.core.approval",
        "sky.core.fast_loop",
        "sky.core.workflow",
        "sky.core.subagent",
        "sky.memory",
        "sky.memory.vectorstore",
        "sky.memory.indexer",
    ]
    
    results = []
    for mod in modules:
        elapsed, _ = time_import(mod)
        results.append((mod, elapsed))
        print(f"{mod:40} {elapsed:>8.1f}ms")
    
    print("\n" + "=" * 60)
    
    # Check for heavy modules
    import sys
    heavy = []
    for mod in sys.modules:
        if any(x in mod.lower() for x in ['torch', 'sentence', 'transformers', 'fastembed', 'lancedb', 'onnx']):
            heavy.append(mod)
    
    if heavy:
        print(f"Heavy modules loaded: {len(heavy)}")
        for m in heavy[:10]:
            print(f"  - {m}")
    else:
        print("No heavy modules detected!")

if __name__ == "__main__":
    main()