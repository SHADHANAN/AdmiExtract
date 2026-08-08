from beanie import PydanticObjectId
from app.models.upload_link import UploadLink


class UploadLinkRepository:
    async def create_link(self, link: UploadLink) -> UploadLink:
        return await link.insert()

    async def get_link_by_id(self, link_id: PydanticObjectId) -> UploadLink | None:
        return await UploadLink.get(link_id)

    async def get_link_by_token(self, token: str) -> UploadLink | None:
        return await UploadLink.find_one(UploadLink.token == token)

    async def get_all_links(self) -> list[UploadLink]:
        return await UploadLink.find_all().sort("-created_at").to_list()

    async def get_links_by_department(self, department_id: PydanticObjectId) -> list[UploadLink]:
        return await UploadLink.find(UploadLink.department_id == department_id).sort("-created_at").to_list()

    async def update_link(self, link_id: PydanticObjectId, update_data: dict) -> UploadLink | None:
        link = await UploadLink.get(link_id)
        if not link:
            return None

        for key, value in update_data.items():
            if hasattr(link, key):
                setattr(link, key, value)

        await link.save()
        return link

    async def delete_link(self, link_id: PydanticObjectId) -> bool:
        link = await UploadLink.get(link_id)
        if not link:
            return False
        await link.delete()
        return True
