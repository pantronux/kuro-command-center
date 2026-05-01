import sys
import os
import json
import asyncio
from unittest.mock import MagicMock

# Setup path
sys.path.append('/home/kuro/projects/kuro')

from kuro_backend import memory_coordinator, memory_manager

def test_isolation():
    print("Starting Multi-User Isolation Test...")
    
    # Mock some data for Pantronux
    pantronux = "Pantronux"
    faikhira = "Faikhira"
    
    # Add unique short-term memory for each
    memory_manager.add_short_term("user", "Hello from Pantronux", username=pantronux)
    memory_manager.add_short_term("user", "Hello from Faikhira", username=faikhira)
    
    # Set unique runtime context for each
    memory_manager.set_runtime_context_value("current_session_state", json.dumps({"user_message": "Pantronux research"}), username=pantronux)
    memory_manager.set_runtime_context_value("current_session_state", json.dumps({"user_message": "Faikhira audit"}), username=faikhira)
    
    print("\nRetrieving context for Pantronux...")
    ctx_p = memory_coordinator.build_context_for_llm("test", "consultant", username=pantronux)
    print(f"Pantronux context snippets: {ctx_p['memory_injection'][:200]}...")
    
    print("\nRetrieving context for Faikhira...")
    ctx_f = memory_coordinator.build_context_for_llm("test", "auditor", username=faikhira)
    print(f"Faikhira context snippets: {ctx_f['memory_injection'][:200]}...")
    
    # Validation
    if "Pantronux" in ctx_p['memory_injection'] and "Pantronux" not in ctx_f['memory_injection']:
        print("\n✅ SUCCESS: Pantronux data isolated.")
    else:
        print("\n❌ FAILURE: Pantronux data leaked or missing.")
        
    if "Faikhira" in ctx_f['memory_injection'] and "Faikhira" not in ctx_p['memory_injection']:
        print("✅ SUCCESS: Faikhira data isolated.")
    else:
        print("❌ FAILURE: Faikhira data leaked or missing.")

if __name__ == "__main__":
    test_isolation()
