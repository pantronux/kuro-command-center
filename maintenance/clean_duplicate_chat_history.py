#!/usr/bin/env python3
"""
Kuro AI - Clean Duplicate Chat History Entries
Run this ONCE to remove duplicate messages from chat_history.db
"""
import sqlite3
import os
import sys

# Path to the database
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kuro_chat_history.db")

def clean_duplicates():
    """Remove duplicate consecutive messages with same platform, role, and content."""
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get total count before cleanup
    cursor.execute("SELECT COUNT(*) FROM chat_history")
    total_before = cursor.fetchone()[0]
    print(f"Total messages before cleanup: {total_before}")
    
    # Find and remove duplicates
    # Strategy: Keep the first occurrence of consecutive identical messages
    # A duplicate is defined as same platform, role, content with consecutive IDs
    cursor.execute("""
        DELETE FROM chat_history 
        WHERE id IN (
            SELECT h1.id FROM chat_history h1
            INNER JOIN chat_history h2 ON h1.id = h2.id + 1
            WHERE h1.platform = h2.platform 
            AND h1.role = h2.role 
            AND h1.content = h2.content
        )
    """)
    
    deleted = cursor.rowcount
    conn.commit()
    
    # Get total count after cleanup
    cursor.execute("SELECT COUNT(*) FROM chat_history")
    total_after = cursor.fetchone()[0]
    
    print(f"Deleted {deleted} duplicate messages")
    print(f"Total messages after cleanup: {total_after}")
    
    conn.close()
    print("Cleanup complete!")

if __name__ == "__main__":
    clean_duplicates()
