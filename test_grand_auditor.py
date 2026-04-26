import asyncio
import os
import sys

from kuro_backend.langgraph_core import build_kuro_graph

async def main():
    print("Initializing LangGraph for Project Kuro V7.0...")
    graph = build_kuro_graph()
    
    # Configure the session and persona
    session_id = "test-auditor-session"
    config = {"configurable": {"thread_id": session_id}}
    
    # Flawed logic snippet for the Auditor to critique
    flawed_logic = """
def authenticate_user(username, password):
    # Quick fix for demo, I'll add real auth later
    if username == "admin" and password == "12345":
        return True
    
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
    db.execute(query)
    
    # Trust the user if they got this far
    return True
"""

    user_input = f"Master here. I've written this new authentication module. It works fast and saves a lot of time. Here is the code:\n{flawed_logic}"
    
    # Send the request
    state_input = {
        "messages": [("user", user_input)],
        "persona": "auditor",
        "file_attachments": []
    }
    
    print("\n--- Sending request to The Grand Auditor ---\n")
    print(f"USER: {user_input}\n")
    print("--------------------------------------------\n")
    
    try:
        async for event in graph.astream(state_input, config=config, stream_mode="values"):
            messages = event.get("messages", [])
            if messages:
                last_msg = messages[-1]
                # last_msg can be a tuple or an object
                msg_type = getattr(last_msg, "type", None) or getattr(last_msg, "role", None)
                if not msg_type and isinstance(last_msg, tuple):
                    msg_type = last_msg[0]
                
                content = getattr(last_msg, "content", None)
                if not content and isinstance(last_msg, tuple):
                    content = last_msg[1]
                    
                if msg_type == "ai":
                    print("\n--- Grand Auditor Response ---\n")
                    print(content)
                    print("\n------------------------------\n")
                    
        print("\nTest Complete. You should also check Mem0 to see if the bug report was stored.")
        
    except Exception as e:
        print(f"Error during execution: {e}")

if __name__ == "__main__":
    asyncio.run(main())
