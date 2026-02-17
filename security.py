from cryptography.fernet import Fernet
import os
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("FERNET_KEY")
if not key:
    # Generate a key if not provided, for strictly local dev/testing if user didn't set it. 
    # But requirement says "Encryption key must come from environment variable".
    # So we should probably raise error or warn. 
    # For now, let's raise error to be strict.
    raise ValueError("FERNET_KEY environment variable is not set")

fernet = Fernet(key)

def encrypt(data: str) -> str:
    if not data:
        return None
    return fernet.encrypt(data.encode()).decode()

def decrypt(token: str) -> str:
    if not token:
        return None
    return fernet.decrypt(token.encode()).decode()
