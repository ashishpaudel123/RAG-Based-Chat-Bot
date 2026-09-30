from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models import User
from app.rate_limit import client_ip, limit
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(user: User) -> TokenResponse:
    token, expires_in = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, db: DB):
    limit("auth", client_ip(request), get_settings().rate_limit_auth)
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(email=email, full_name=body.full_name, hashed_password=hash_password(body.password), role="user")
    db.add(user)
    db.commit()
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: DB):
    limit("auth", client_ip(request), get_settings().rate_limit_auth)
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been disabled")
    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
