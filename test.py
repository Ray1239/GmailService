from cryptography.fernet import Fernet

# Generate a valid key
key = Fernet.generate_key()

# Print it out
print(key.decode())