try:
    from kuro_backend import reminder_service
    print(f"Import successful: {reminder_service.__file__}")
except ImportError as e:
    print(f"Import failed: {e}")
except Exception as e:
    print(f"An error occurred: {e}")
