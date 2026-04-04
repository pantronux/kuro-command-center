from google import genai
from kuro_backend.config import settings

def analyze_document_compliance(document_content: str, standard_filename: str):
    """Analyzes document compliance against a given standard using SDK v3."""
    # CRITICAL CONSTRAINT: Initialize client locally.
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    prompt = f"Document: {document_content}\n\nStandard: {standard_filename}\n\nAnalyze the document for compliance with the standard."
    
    try:
        response = client.models.generate_content(
            model=f"models/{settings.MODEL_NAME}",
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Error during compliance analysis: {e}"
