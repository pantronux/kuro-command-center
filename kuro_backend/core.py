from google import genai
from kuro_backend.config import settings
from kuro_backend import tools
from kuro_backend import compliance_analyzer

# Initialize the Generative AI client (SDK v3)
client = genai.Client(api_key=settings.GEMINI_API_KEY)

def process_chat(message: str):
    """Processes a chat message by sending it to the AI core and handling function calls."""
    try:
        # Using the new client.models.generate_content syntax
        response = client.models.generate_content(
            model=f"models/{settings.MODEL_NAME}",
            contents=message,
            # Function calling tools would be passed here in a `tools` parameter if the client supports it directly
            # For now, we will handle a simple text response
        )
        return response.text
    except Exception as e:
        # In case of an API error, return a formatted error message
        error_message = f"Maaf, Master Irfan. Butler Kuro mengalami sedikit kendala saat memproses permintaan Anda. Detail: {e}"
        return error_message
