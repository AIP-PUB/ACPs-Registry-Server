from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from app.core.db_session import get_db
from app.core.auth import safe_get_current_user
from app.account.model import User
from app.account.schema_auth import (
    Token,
    VerifyCodeRequest,
    VerifyCodeResponse,
    RegisterRequest,
    PhoneLoginRequest,
    ResetPasswordRequest,
    RefreshTokenRequest,
)
from app.account.service_auth import (
    send_verification_code,
    register_user,
    authenticate_user,
    authenticate_by_phone,
    create_user_token,
    reset_password,
    invalidate_token,
    refresh_access_token,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/verify-code", response_model=VerifyCodeResponse)
async def request_verification_code(
    request: VerifyCodeRequest, db: Session = Depends(get_db)
):
    """
    Request a verification code to be sent to the phone number.
    In production, this would send an SMS. For demo, it returns the code.
    """
    code = send_verification_code(request.phone)
    return {"message": "Verification code sent", "code": code}  # For demonstration only


@router.post("/register", response_model=Token)
async def register_new_user(request: RegisterRequest, db: Session = Depends(get_db)):
    """
    Register a new user using credentials.
    Both username/password-based registration and phone verification are supported.
    """
    # Convert RegisterRequest to user data dict
    user_data = request.dict(exclude={"verify_code"})

    # Validate that either username/password or phone/verify_code is provided
    if not (request.phone and request.verify_code) and not (
        request.username and request.password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either username/password or phone/verify_code must be provided",
        )

    # Register the user - this function already raises AuthException when needed
    verify_code = request.verify_code or ""  # Default to empty string if None
    user = register_user(db, user_data, verify_code)

    # Create and return token
    return create_user_token(user, db)


@router.post("/login", response_model=Token)
async def login_with_username_password(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    # Use raise_exception=True parameter to have the service function handle exceptions
    user = authenticate_user(
        db, form_data.username, form_data.password, raise_exception=True
    )
    return create_user_token(user, db)


@router.post("/login-phone", response_model=Token)
async def login_with_phone(request: PhoneLoginRequest, db: Session = Depends(get_db)):
    """
    Login with phone number and verification code
    """
    # Use raise_exception=True parameter to have the service function handle exceptions
    user = authenticate_by_phone(
        db, request.phone, request.verify_code, raise_exception=True
    )
    return create_user_token(user, db)


@router.post("/reset-password")
async def reset_user_password(
    request: ResetPasswordRequest, db: Session = Depends(get_db)
):
    """
    Reset user password using phone verification
    """
    # This function already raises AuthException when needed
    success = reset_password(
        db, request.phone, request.verify_code, request.new_password
    )

    return {"message": "Password reset successfully"}


@router.post("/logout", response_model=dict)
async def logout(
    current_user: Optional[User] = Depends(safe_get_current_user),
    db: Session = Depends(get_db),
):
    """
    Logout the current user by invalidating their access token.
    Allow logout even if user is not logged in.
    """
    if current_user:
        # Add token to revoked tokens list (for immediate invalidation)
        if current_user.access_token:
            invalidate_token(current_user.access_token)

        # Clear tokens from the user model
        current_user.access_token = None
        current_user.refresh_token = None
        current_user.token_expires_at = None
        current_user.updated_at = datetime.utcnow()

        # Save changes to database
        db.add(current_user)
        db.commit()

    # Always return success, even if not logged in
    return {"success": True, "message": "Successfully logged out"}


@router.post("/refresh-token", response_model=Token)
async def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    """
    Refresh access token using a refresh token
    """
    # Use raise_exception=True parameter to have the service function handle exceptions
    new_token = refresh_access_token(db, request.refresh_token, raise_exception=True)
    return new_token
