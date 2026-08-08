import re
from beanie import PydanticObjectId
from app.models.department import Department


class DepartmentRepository:
    """
    Repository handling direct database operations for the Department model using Beanie.
    Contains no business validation, HTTP dependencies, or FastAPI concepts.
    """

    async def create_department(self, department: Department) -> Department:
        """
        Insert a new department document into MongoDB.
        """
        return await department.insert()

    async def get_all_departments(self) -> list[Department]:
        """
        Retrieve all departments sorted by newest first (descending created_at).
        """
        return await Department.find_all().sort("-created_at").to_list()

    async def get_department_by_id(self, department_id: PydanticObjectId) -> Department | None:
        """
        Find a department by its PydanticObjectId.
        Returns None if no matching department exists.
        """
        return await Department.get(department_id)

    async def get_department_by_name(self, name: str) -> Department | None:
        """
        Find a department by its name (case-insensitive search).
        """
        escaped_name = re.escape(name.strip())
        return await Department.find_one({"name": {"$regex": f"^{escaped_name}$", "$options": "i"}})


    async def update_department(self, department_id: PydanticObjectId, update_data: dict) -> Department | None:
        """
        Update selected fields of a department.
        Only fields present in the update_data dictionary will be modified.
        Returns the updated Department document, or None if not found.
        """
        department = await Department.get(department_id)
        if not department:
            return None

        for key, value in update_data.items():
            if hasattr(department, key):
                setattr(department, key, value)

        await department.save()
        return department

    async def delete_department(self, department_id: PydanticObjectId) -> bool:
        """
        Hard delete a department from the database by its ID.
        Returns True if the deletion succeeded, False if the department did not exist.
        """
        department = await Department.get(department_id)
        if not department:
            return False

        await department.delete()
        return True
