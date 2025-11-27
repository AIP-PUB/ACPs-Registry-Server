from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO format timestamp when the token expires


class TokenPayload(BaseModel):
    sub: Optional[str] = None


class VerifyCodeRequest(BaseModel):
    phone: str


class VerifyCodeResponse(BaseModel):
    message: str
    code: str  # In a real system, this would not be returned, but sent via SMS


class RegisterRequest(BaseModel):
    username: str
    password: str
    phone: Optional[str] = None
    verify_code: Optional[str] = None
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    org_name: Optional[str] = None
    org_code: Optional[str] = None
    org_address: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class PhoneLoginRequest(BaseModel):
    phone: str
    verify_code: str


class ResetPasswordRequest(BaseModel):
    phone: str
    verify_code: str
    new_password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str
