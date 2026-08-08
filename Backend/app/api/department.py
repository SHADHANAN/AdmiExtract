from fastapi import APIRouter, Depends, HTTPException, status
from beanie import PydanticObjectId

from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.schemas.department import DepartmentCreate, DepartmentUpdate, DepartmentResponse
from app.services.department_service import (
    DepartmentService,
    DepartmentNotFoundException,
    DepartmentAlreadyExistsException,
)

router = APIRouter(
    prefix="/departments",
    tags=["Departments"],
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)


def get_department_service() -> DepartmentService:
    """Dependency injector for DepartmentService."""
    return DepartmentService()


@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN]))])
async def create_department(
    dep_in: DepartmentCreate,
    current_user: User = Depends(get_current_user),
    service: DepartmentService = Depends(get_department_service),
):
    """
    Create a new department.
    Accessible only by Super Admin users.
    """
    try:
        return await service.create_department(
            name=dep_in.name,
            code=dep_in.code,
            description=dep_in.description,
            created_by=current_user.username,
        )
    except DepartmentAlreadyExistsException as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.get("", response_model=list[DepartmentResponse], status_code=status.HTTP_200_OK)
async def list_departments(
    current_user: User = Depends(get_current_user),
    service: DepartmentService = Depends(get_department_service),
):
    """
    Retrieve all departments.
    Super Admin sees all. Department Admin only sees their own assigned department.
    """
    try:
        all_depts = await service.get_all_departments()
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            return [d for d in all_depts if d.code == current_user.department_code]
        return all_depts
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.get("/{department_id}", response_model=DepartmentResponse, status_code=status.HTTP_200_OK)
async def get_department_by_id(
    department_id: PydanticObjectId,
    current_user: User = Depends(get_current_user),
    service: DepartmentService = Depends(get_department_service),
):
    """
    Retrieve details of a single department by ID.
    Accessible by Super Admin, and Department Admin (scoped to their own department).
    """
    try:
        dept = await service.get_department_by_id(department_id)
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            if dept.code != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access another department's details.",
                )
        return dept
    except DepartmentNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.put("/{department_id}", response_model=DepartmentResponse, status_code=status.HTTP_200_OK, dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN]))])
async def update_department(
    department_id: PydanticObjectId,
    dep_in: DepartmentUpdate,
    current_user: User = Depends(get_current_user),
    service: DepartmentService = Depends(get_department_service),
):
    """
    Update department details.
    Accessible only by Super Admin users.
    """
    try:
        update_dict = dep_in.model_dump(exclude_unset=True)
        return await service.update_department(department_id, update_dict)
    except DepartmentNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DepartmentAlreadyExistsException as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )


@router.delete("/{department_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN]))])
async def delete_department(
    department_id: PydanticObjectId,
    current_user: User = Depends(get_current_user),
    service: DepartmentService = Depends(get_department_service),
):
    """
    Delete a department by ID.
    Accessible only by Super Admin users.
    """
    try:
        await service.delete_department(department_id)
        return {"message": "Department deleted successfully"}
    except DepartmentNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}",
        )
