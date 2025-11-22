from core.config import Settings
try:
    s = Settings()
    print("Settings loaded successfully")
    print(s.model_dump())
except Exception as e:
    print(f"Error loading settings: {e}")
