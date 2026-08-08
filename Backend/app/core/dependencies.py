from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from beanie import PydanticObjectId

from app.core.security import decode_access_token
from app.models.user import User, UserRole

from app.repositories.user_repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    Dependency to validate JWT token and return the current user.
    Raises 401 Unauthorized if the token is invalid or the user does not exist.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
        
    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception
        
    try:
        user_id = PydanticObjectId(user_id_str)
    except Exception:
        raise credentials_exception
        
    user_repo = UserRepository()
    user = await user_repo.get_user_by_id(user_id)
    if user is None:
        raise credentials_exception
        
    return user


async def get_optional_current_user(token: str | None = Depends(oauth2_scheme_optional)) -> User | None:
    """
    Optional dependency to return current user if valid JWT token present, else None.
    Does not raise 401.
    """
    if not token:
        return None
    try:
        return await get_current_user(token)
    except HTTPException:
        return None



class RoleChecker:
    def __init__(self, allowed_roles: list[UserRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return current_user


def check_department_access(current_user: User, resource_department_code: str | None) -> None:
    """
    RBAC Department Access Check:
    - Super Admin can access all resources across all departments.
    - Department Admin can ONLY access resources belonging to their assigned department_code.
    Raises HTTP 403 Forbidden if a Department Admin attempts to access another department's resources.
    """
    if current_user.role == UserRole.SUPER_ADMIN:
        return

    if current_user.role == UserRole.DEPARTMENT_ADMIN:
        if not current_user.department_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Department Admin has no assigned department.",
            )
        if resource_department_code is not None and str(resource_department_code).strip().upper() != str(current_user.department_code).strip().upper():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to access another department's resources",
            )


