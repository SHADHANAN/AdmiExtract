from fastapi import HTTPException, status

from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import verify_password
from app.services.user_service import UserService, UserAlreadyExistsException
from app.repositories.user_repository import UserRepository


async def register_user(user_in: UserCreate) -> User:
    """
    Register a new user after verifying that the email address is unique.
    Hashes the password before storing it. Uses UserService to avoid duplication.
    """
    try:
        user_service = UserService()
        return await user_service.create_user(user_in)
    except UserAlreadyExistsException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


async def authenticate_user(identifier: str, password: str) -> User | None:
    """
    Authenticate a user by username or email, verifying password and active status.
    Returns the User document if successful and active, otherwise None.
    """
    user_repo = UserRepository()
    user = await user_repo.get_user_by_username_or_email(identifier)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.password):
        return None
    return user
