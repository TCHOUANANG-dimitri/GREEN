# ============================================================
# GREEN App — Authentication Router
# Endpoints: /api/auth/register, /api/auth/login, /api/auth/me
# ============================================================

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import UserRegister, UserLogin, UserUpdate, PasswordChange, TokenResponse, UserResponse, MessageResponse
from auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# ---- POST /api/auth/register --------------------------------
@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new GREEN account"
)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new enterprise user.
    - Phone is required and must be unique.
    - Email is optional but must be unique if provided.
    Returns a JWT token and the created user profile.
    """
    # Check phone uniqueness
    if db.query(User).filter(User.phone == user_data.phone).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This phone number is already registered."
        )

    # Check email uniqueness (only if email was provided)
    if user_data.email:
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email address is already registered."
            )

    # Create new user
    new_user = User(
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        phone=user_data.phone,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        company_name=user_data.company_name,
        region=user_data.region,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Issue JWT token
    token = create_access_token({"sub": str(new_user.id), "phone": new_user.phone})

    return TokenResponse(access_token=token, user=UserResponse.model_validate(new_user))


# ---- POST /api/auth/login -----------------------------------
@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in with phone or email"
)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """
    Sign in using phone number OR email address + password.
    Returns a JWT token and the user profile.
    """
    identifier = credentials.identifier.strip()

    # Search by phone or email
    user = db.query(User).filter(
        (User.phone == identifier) | (User.email == identifier)
    ).first()

    # Validate credentials (same error for unknown user AND wrong password
    # to prevent user enumeration attacks)
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect phone/email or password."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated."
        )

    # Issue JWT token
    token = create_access_token({"sub": str(user.id), "phone": user.phone})

    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


# ---- GET /api/auth/me ---------------------------------------
@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the current authenticated user"
)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Returns the profile of the currently logged-in user.
    Requires a valid Bearer token in the Authorization header.
    """
    return current_user


# ---- PUT /api/auth/me ---------------------------------------
@router.put(
    "/me",
    response_model=UserResponse,
    summary="Update current user's profile"
)
def update_me(
    update_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update editable profile fields (name, email, company, region)."""

    # Email uniqueness check (if being changed)
    if update_data.email and update_data.email != current_user.email:
        if db.query(User).filter(User.email == update_data.email).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already used by another account."
            )

    # Apply changes (only fields that were provided)
    for field, value in update_data.model_dump(exclude_none=True).items():
        setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)
    return current_user


# ---- POST /api/auth/change-password -------------------------
@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change the current user's password"
)
def change_password(
    data: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Verify current password, then set a new one."""
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect."
        )

    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    return MessageResponse(message="Password updated successfully.")


# ---- DELETE /api/auth/me ------------------------------------
@router.delete(
    "/me",
    response_model=MessageResponse,
    summary="Delete current user's account"
)
def delete_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Soft-deletes the account by setting is_active = False.
    The user data is retained for audit purposes.
    """
    current_user.is_active = False
    db.commit()
    return MessageResponse(message="Your account has been deactivated.")
