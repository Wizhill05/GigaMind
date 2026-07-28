import secrets
import time
from typing import Dict, Any, Optional

# In-memory stores for auth codes and valid access tokens
_auth_codes: Dict[str, Dict[str, Any]] = {}
_valid_access_tokens: set = set()

def generate_random_token(bytes_len: int = 32) -> str:
    return secrets.token_hex(bytes_len)

def create_authorization_code(client_id: str, redirect_uri: str, code_challenge: Optional[str] = None) -> str:
    code = f"code_{generate_random_token(24)}"
    _auth_codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "expires_at": time.time() + 600 # 10 minutes
    }
    return code

def consume_authorization_code(code: str, client_id: str, redirect_uri: str) -> bool:
    entry = _auth_codes.pop(code, None)
    if not entry:
        return False
    if time.time() > entry["expires_at"]:
        return False
    return True

def issue_access_token() -> Dict[str, Any]:
    access_token = f"gm_at_{generate_random_token(32)}"
    refresh_token = f"gm_rt_{generate_random_token(32)}"
    _valid_access_tokens.add(access_token)

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 30 * 86400, # 30 days
        "refresh_token": refresh_token,
        "scope": "memory"
    }

def verify_access_token(token: str) -> bool:
    return token in _valid_access_tokens
