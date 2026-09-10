from fastapi import APIRouter, Depends, HTTPException, status
from beanie import PydanticObjectId

from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserResponse, UserUpdate, ResetPasswordSchema, ToggleUserStatusSchema
from app.core.dependencies import get_current_user, RoleChecker
from app.services.user_service import (
    UserService,
    UserNotFoundException,
    UserAlreadyExistsException,
)

# Protect all CRUD endpoints under /users to be Super Admin-only
router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN]))],
)


def get_user_service() -> UserService:
    """Dependency injector for UserService."""
    return UserService()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    service: UserService = Depends(get_user_service),
):
    """
    Create a new Department user.
    Accessible only by authenticated Super Admin users.
    """
    try:
        return await service.create_user(user_in)
    except UserAlreadyExistsException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.get("", response_model=list[UserResponse], status_code=status.HTTP_200_OK)
async def list_users(
    service: UserService = Depends(get_user_service),
):
    """
    Retrieve all users.
    Accessible only by authenticated Super Admin users.
    """
    try:
        return await service.get_all_users()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.get("/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_user(
    user_id: PydanticObjectId,
    service: UserService = Depends(get_user_service),
):
    """
    Retrieve a single user by ID.
    Accessible only by authenticated Super Admin users.
    """
    try:
        return await service.get_user_by_id(user_id)
    except UserNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.put("/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def update_user(
    user_id: PydanticObjectId,
    user_data: UserUpdate,
    service: UserService = Depends(get_user_service),
):
    """
    Update user information. Only specified fields will be modified.
    Accessible only by authenticated Super Admin users.
    """
    try:
        update_dict = user_data.model_dump(exclude_unset=True)
        return await service.update_user(user_id, update_dict)
    except UserNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except UserAlreadyExistsException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.put("/{user_id}/reset-password", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def reset_user_password(
    user_id: PydanticObjectId,
    payload: ResetPasswordSchema,
    service: UserService = Depends(get_user_service),
):
    """
    Reset a user's password.
    Accessible only by authenticated Super Admin users.
    """
    try:
        return await service.reset_password(user_id, payload.new_password)
    except UserNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.patch("/{user_id}/toggle-status", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def toggle_user_status(
    user_id: PydanticObjectId,
    payload: ToggleUserStatusSchema,
    service: UserService = Depends(get_user_service),
):
    """
    Enable or disable a user.
    Accessible only by authenticated Super Admin users.
    """
    try:
        return await service.toggle_user_status(user_id, payload.is_active)
    except UserNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: PydanticObjectId,
    service: UserService = Depends(get_user_service),
):
    """
    Delete a user by ID.
    Accessible only by authenticated Super Admin users.
    """
    try:
        await service.delete_user(user_id)
        return {"message": "User deleted successfully"}
    except UserNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )

