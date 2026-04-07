import logging
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError
from kuro_backend.config import settings

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

# Reuse the global client instance for memory efficiency (same as core.py)
_client = None

def _get_client():
    """Returns a cached genai client, creating one if needed."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def analyze_document_compliance(document_content: str, standard_filename: str) -> str:
    """Analyzes document compliance against a given standard using SDK v3.
    
    Uses consistent model naming (no double-prefix) and proper error handling.
    """
    prompt = (
        f"Analyze the following document for compliance with the standard '{standard_filename}'.\n\n"
        f"Document Content:\n{document_content}\n\n"
        f"Provide a detailed compliance report highlighting any violations or areas of concern."
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.MODEL_NAME,  # Consistent: no 'models/' prefix (handled by SDK)
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,  # Lower temperature for compliance analysis
                top_p=0.9
            )
        )
        return response.text if response.text else "Unable to generate compliance analysis."

    except ClientError as e:
        logger.error(f"ClientError in compliance analysis: {e}")
        return f"Compliance analysis failed due to invalid request: {e}"

    except APIError as e:
        logger.error(f"APIError in compliance analysis: {e}")
        return "Compliance analysis failed: Gemini API is currently unavailable. Please try again later."

    except Exception as e:
        logger.exception(f"Unexpected error in compliance analysis: {e}")
        return f"Error during compliance analysis: {e}"
