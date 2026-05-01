import os
import json
import sqlite3
import sys
from dotenv import load_dotenv

# Add parent dir to path so we can import kuro_backend
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kuro_backend import auth_db

load_dotenv()

def migrate():
    print("Initializing Database...")
    auth_db.init_auth_db()
    
    # Check if users already exist
    existing_users = auth_db.get_all_users()
    if existing_users:
        print(f"Users already exist in database: {existing_users}. Skipping migration.")
        return

    print("Loading master_profile.json...")
    profile_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "master_profile.json")
    with open(profile_path, 'r') as f:
        master_profile = json.load(f)

    # Get hashes from .env
    admin_hash = os.getenv("ADMIN_PASSWORD_HASH", "")
    faikhira_hash = os.getenv("FAIKHIRA_PASSWORD_HASH", "")

    users_to_migrate = [
        {
            "username": os.getenv("ADMIN_USERNAME", "Pantronux"),
            "password_hash": admin_hash,
            "email": "admin@kuro.ai",
            "display_name": master_profile["users"].get("Pantronux", {}).get("master", {}).get("name", "Pantronux"),
            "role": master_profile["users"].get("Pantronux", {}).get("master", {}).get("role", "Administrator"),
            "master_name": "Master Pantronux"
        },
        {
            "username": os.getenv("FAIKHIRA_USERNAME", "Faikhira"),
            "password_hash": faikhira_hash,
            "email": "qa@kuro.ai",
            "display_name": master_profile["users"].get("Faikhira", {}).get("master", {}).get("name", "Faikhira"),
            "role": master_profile["users"].get("Faikhira", {}).get("master", {}).get("role", "Quality Assurance"),
            "master_name": "Master Faikhira"
        }
    ]

    for user in users_to_migrate:
        print(f"Migrating user: {user['username']}...")
        success = auth_db.create_user(
            username=user['username'],
            password_hash=user['password_hash'],
            email=user['email'],
            display_name=user['display_name'],
            role=user['role'],
            master_name=user['master_name']
        )
        if success:
            print(f"Successfully migrated {user['username']}")
        else:
            print(f"Failed to migrate {user['username']}")

if __name__ == "__main__":
    migrate()
