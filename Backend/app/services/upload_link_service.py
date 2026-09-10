import uuid
import re
from datetime import datetime, timezone
from beanie import PydanticObjectId
from app.models.upload_link import UploadLink
from app.schemas.upload_link import UploadLinkCreate
from app.repositories.upload_link_repository import UploadLinkRepository


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')


class UploadLinkNotFoundException(Exception):
    def __init__(self, message: str = "Upload link not found"):
        self.message = message
        super().__init__(self.message)


class UploadLinkService:
    def __init__(self, repository: UploadLinkRepository | None = None):
        self.repository = repository or UploadLinkRepository()

    async def create_link(self, data: UploadLinkCreate, created_by: str) -> UploadLink:
        token = f"lnk_{uuid.uuid4().hex[:12]}"
        
        # Generate unique slug from title
        base_slug = slugify(data.title)
        if not base_slug:
            base_slug = "upload-portal"
        
        slug = base_slug
        count = 0
        while await UploadLink.find_one(UploadLink.slug == slug):
            count += 1
            slug = f"{base_slug}-{count}"

        new_link = UploadLink(
            department_id=data.department_id,
            batch_id=data.batch_id,
            class_id=data.class_id,
            token=token,
            slug=slug,
            title=data.title.strip(),
            description=data.description.strip() if data.description else None,
            is_active=True,
            expires_at=data.expires_at,
            max_submissions=data.max_submissions,
            submission_count=0,
            created_by=created_by,
        )
        return await self.repository.create_link(new_link)


    async def get_link_by_id(self, link_id: PydanticObjectId) -> UploadLink:
        link = await self.repository.get_link_by_id(link_id)
        if not link:
            raise UploadLinkNotFoundException(f"Upload link with ID '{link_id}' not found.")
        return link

    async def get_link_by_slug_or_token(self, identifier: str) -> UploadLink:
        link = await UploadLink.find_one(UploadLink.slug == identifier)
        if not link:
            link = await UploadLink.find_one(UploadLink.token == identifier)
        if not link:
            raise UploadLinkNotFoundException(f"Upload link with identifier '{identifier}' not found.")
        return link

    async def get_link_by_token(self, token: str) -> UploadLink:
        link = await self.repository.get_link_by_token(token)
        if not link:
            raise UploadLinkNotFoundException(f"Upload link with token '{token}' not found.")
        return link

    async def get_all_links(self) -> list[UploadLink]:
        return await self.repository.get_all_links()

    async def get_links_by_department(self, department_id: PydanticObjectId) -> list[UploadLink]:
        return await self.repository.get_links_by_department(department_id)

    async def update_link(self, link_id: PydanticObjectId, update_data: dict) -> UploadLink:
        updated = await self.repository.update_link(link_id, update_data)
        if not updated:
            raise UploadLinkNotFoundException(f"Upload link with ID '{link_id}' not found.")
        return updated

    async def delete_link(self, link_id: PydanticObjectId) -> bool:
        deleted = await self.repository.delete_link(link_id)
        if not deleted:
            raise UploadLinkNotFoundException(f"Upload link with ID '{link_id}' not found.")
        return True

    async def increment_submission_count(self, token: str) -> UploadLink | None:
        link = await self.repository.get_link_by_token(token)
        if not link:
            return None
        link.submission_count += 1
        await link.save()
        return link
