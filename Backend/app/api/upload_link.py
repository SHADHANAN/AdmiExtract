from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from beanie import PydanticObjectId
from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.schemas.upload_link import UploadLinkCreate, UploadLinkUpdate, UploadLinkResponse
from app.services.upload_link_service import UploadLinkService, UploadLinkNotFoundException
from app.services.department_service import DepartmentService

router = APIRouter(
    prefix="/upload-links",
    tags=["Upload Links"],
)


def get_upload_link_service() -> UploadLinkService:
    return UploadLinkService()


def get_department_service() -> DepartmentService:
    return DepartmentService()


@router.post("", response_model=UploadLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_upload_link(
    data: UploadLinkCreate,
    current_user: User = Depends(get_current_user),
    service: UploadLinkService = Depends(get_upload_link_service),
    dept_service: DepartmentService = Depends(get_department_service),
):
    # Department Admin can only create upload links for their own department
    if current_user.role == UserRole.DEPARTMENT_ADMIN:
        dept = await dept_service.get_department_by_id(data.department_id)
        if dept.code != current_user.department_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You can only create upload links for your assigned department.",
            )

    try:
        return await service.create_link(data, created_by=current_user.username)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("", response_model=list[UploadLinkResponse])
async def list_upload_links(
    current_user: User = Depends(get_current_user),
    service: UploadLinkService = Depends(get_upload_link_service),
    dept_service: DepartmentService = Depends(get_department_service),
):
    if current_user.role == UserRole.DEPARTMENT_ADMIN:
        if not current_user.department_code:
            return []
        
        # Get the department document to retrieve its ID
        all_depts = await dept_service.get_all_departments()
        user_dept = next((d for d in all_depts if d.code == current_user.department_code), None)
        if not user_dept:
            return []
        
        return await service.get_links_by_department(user_dept.id)
    
    return await service.get_all_links()


@router.get("/{slug}", response_model=UploadLinkResponse)
async def get_upload_link_by_slug(
    slug: str,
    service: UploadLinkService = Depends(get_upload_link_service),
):
    print(f"[Upload Link Verification] Requested slug: {slug}")
    try:
        link = await service.get_link_by_slug_or_token(slug)
        
        # 1. Validate admission batch exists
        if not link.batch_id:
            print(f"[Upload Link Verification] Validation failed for slug '{slug}': batch_id is missing on link document. Result: 404")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid upload link.",
            )

        from app.services.batch_service import BatchService
        batch_service = BatchService()
        try:
            await batch_service.get_batch_by_id(link.batch_id)
        except Exception:
            print(f"[Upload Link Verification] Validation failed for slug '{slug}': batch '{link.batch_id}' does not exist in DB. Result: 404")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid upload link.",
            )

        # 2. Validate department exists
        from app.services.department_service import DepartmentService
        dept_service = DepartmentService()
        try:
            await dept_service.get_department_by_id(link.department_id)
        except Exception:
            print(f"[Upload Link Verification] Validation failed for slug '{slug}': department '{link.department_id}' does not exist in DB. Result: 404")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid upload link.",
            )

        # 3. Check active status
        if not link.is_active:
            print(f"[Upload Link Verification] Validation failed for slug '{slug}': link is deactivated. Result: 403")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Upload link has been disabled.",
            )

        # 4. Check expiry (if configured)
        if link.expires_at is not None:
            now = datetime.now(timezone.utc)
            expires_at = link.expires_at.replace(tzinfo=timezone.utc) if link.expires_at.tzinfo is None else link.expires_at
            if expires_at < now:
                print(f"[Upload Link Verification] Validation failed for slug '{slug}': link has expired at {expires_at}. Result: 410")
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail="Upload link has expired.",
                )

        print(f"[Upload Link Verification] Validation succeeded for slug '{slug}'. Result: 200 OK")
        return link

    except UploadLinkNotFoundException:
        # Check if slug is a valid ObjectId for admin get_by_id requests
        try:
            if len(slug) == 24:
                obj_id = PydanticObjectId(slug)
                link = await service.get_link_by_id(obj_id)
                print(f"[Upload Link Verification] Found ID lookup for admin request: {slug}. Result: 200 OK")
                return link
        except Exception:
            pass

        print(f"[Upload Link Verification] Validation failed for slug '{slug}': slug/token not found in database. Result: 404")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid upload link.",
        )
    except HTTPException as he:
        # Re-raise HTTPExceptions we explicitly threw
        raise he
    except Exception as e:
        print(f"[Upload Link Verification] Internal error for slug '{slug}': {str(e)}. Result: 500")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error.",
        )


@router.put("/{id}", response_model=UploadLinkResponse)
async def update_upload_link(
    id: PydanticObjectId,
    data: UploadLinkUpdate,
    current_user: User = Depends(get_current_user),
    service: UploadLinkService = Depends(get_upload_link_service),
    dept_service: DepartmentService = Depends(get_department_service),
):
    try:
        link = await service.get_link_by_id(id)
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            dept = await dept_service.get_department_by_id(link.department_id)
            if dept.code != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have access to this department's resources.",
                )
        
        update_dict = data.model_dump(exclude_unset=True)
        return await service.update_link(id, update_dict)
    except UploadLinkNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)


@router.delete("/{id}")
async def delete_upload_link(
    id: PydanticObjectId,
    current_user: User = Depends(get_current_user),
    service: UploadLinkService = Depends(get_upload_link_service),
    dept_service: DepartmentService = Depends(get_department_service),
):
    try:
        link = await service.get_link_by_id(id)
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            dept = await dept_service.get_department_by_id(link.department_id)
            if dept.code != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have access to this department's resources.",
                )
        
        await service.delete_link(id)
        return {"message": "Upload link deleted successfully"}
    except UploadLinkNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
