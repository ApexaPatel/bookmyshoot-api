import bcrypt
import hashlib

def get_password_hash(password: str) -> str:
    """
    Hash a password using SHA-256 and then bcrypt.
    
    Args:
        password: The plain text password to hash
        
    Returns:
        str: The hashed password
    """
    try:
        # First hash with SHA-256 to handle long passwords
        sha256_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
        # Then hash with bcrypt
        return bcrypt.hashpw(sha256_hash.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    except Exception as e:
        raise ValueError(f"Error hashing password: {str(e)}")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash using SHA-256 + bcrypt.
    
    Args:
        plain_password: The plain text password to verify
        hashed_password: The hashed password to verify against
        
    Returns:
        bool: True if the password matches, False otherwise
    """
    try:
        # First hash with SHA-256 to handle long passwords
        sha256_hash = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()
        # Then verify with bcrypt
        return bcrypt.checkpw(
            sha256_hash.encode('utf-8'), 
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False
