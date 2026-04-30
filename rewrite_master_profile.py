import json

with open("master_profile.json", "r", encoding="utf-8") as f:
    old_data = json.load(f)

new_data = {
    "shared": {
        "infrastructure": old_data.get("infrastructure", {}),
        "compliance_standards": old_data.get("compliance_standards", {}),
        "cross_mapping": old_data.get("cross_mapping", {}),
        "notes": old_data.get("notes", [])
    },
    "users": {
        "Pantronux": {
            "master": old_data.get("master", {}),
            "preferences": old_data.get("preferences", {})
        },
        "kagetoki": {
            "master": {
                "name": "Kagetoki",
                "role": "Quality Assurance",
                "telegram_chat_id": ""
            },
            "preferences": {
                "ai_model": "gemini-3.1-pro",
                "language": "Indonesian/English",
                "persona": "Kuro - QA Auditor",
                "persona_mode": "auditor",
                "runtime_context": {}
            }
        }
    }
}

with open("master_profile.json", "w", encoding="utf-8") as f:
    json.dump(new_data, f, indent=4, ensure_ascii=False)
print("Done")
