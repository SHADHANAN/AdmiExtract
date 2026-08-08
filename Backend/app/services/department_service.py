from beanie import PydanticObjectId
from app.models.department import Department
from app.repositories.department_repository import DepartmentRepository


class DepartmentNotFoundException(Exception):
    """Exception raised when a department is not found."""
    def __init__(self, message: str = "Department not found"):
        self.message = message
        super().__init__(self.message)


class DepartmentAlreadyExistsException(Exception):
    """Exception raised when a department with the same name already exists."""
    def __init__(self, message: str = "Department with this name already exists"):
        self.message = message
        super().__init__(self.message)


class DepartmentService:
    """
    Service layer for managing Department business operations.
    Communicates strictly via DepartmentRepository and handles all business validation.
    """

    def __init__(self, repository: DepartmentRepository | None = None):
        self.repository = repository or DepartmentRepository()

    async def create_department(self, name: str, code: str, created_by: str, description: str | None = None) -> Department:
        """
        Create a new department after validating unique name & code.
        """
        trimmed_name = name.strip()
        trimmed_code = code.strip().upper()
        if not trimmed_name or not trimmed_code:
            raise ValueError("Department name and code cannot be empty")

        existing_name = await self.repository.get_department_by_name(trimmed_name)
        if existing_name:
            raise DepartmentAlreadyExistsException(f"Department with name '{trimmed_name}' already exists.")

        new_dept = Department(
            name=trimmed_name,
            code=trimmed_code,
            description=description,
            created_by=created_by
        )
        return await self.repository.create_department(new_dept)

    async def get_all_departments(self) -> list[Department]:
        """
        Retrieve all departments sorted newest-first.
        """
        return await self.repository.get_all_departments()

    async def get_department_by_id(self, department_id: PydanticObjectId) -> Department:
        """
        Retrieve a department by its ID, raising an exception if it doesn't exist.
        """
        department = await self.repository.get_department_by_id(department_id)
        if not department:
            raise DepartmentNotFoundException(f"Department with ID {department_id} not found.")
        return department

    async def update_department(self, department_id: PydanticObjectId, update_data: dict) -> Department:
        """
        Update the department. Ensures the department exists, and checks name uniqueness
        if the name is being changed.
        """
        # Verify the department exists
        department = await self.repository.get_department_by_id(department_id)
        if not department:
            raise DepartmentNotFoundException(f"Department with ID {department_id} not found.")

        # Check if the name is being updated
        new_name = update_data.get("name")
        if new_name is not None:
            trimmed_name = new_name.strip()
            if not trimmed_name:
                raise ValueError("Department name cannot be empty")
            
            # If changing the name, ensure the new name is unique case-insensitively
            if trimmed_name.lower() != department.name.lower():
                existing = await self.repository.get_department_by_name(trimmed_name)
                if existing:
                    raise DepartmentAlreadyExistsException(f"Department with name '{trimmed_name}' already exists.")
                update_data["name"] = trimmed_name

        updated_dept = await self.repository.update_department(department_id, update_data)
        if not updated_dept:
            raise DepartmentNotFoundException(f"Department with ID {department_id} not found.")
        return updated_dept

    async def delete_department(self, department_id: PydanticObjectId) -> bool:
        """
        Delete a department. Easily adaptable to soft deletion (e.g. updating is_active to False).
        Currently performs a hard delete using the repository layer.
        """
        # Verify the department exists
        department = await self.repository.get_department_by_id(department_id)
        if not department:
            raise DepartmentNotFoundException(f"Department with ID {department_id} not found.")

        # To support soft deletion in the future, we could replace this call with:
        # return await self.repository.update_department(department_id, {"is_active": False})
        return await self.repository.delete_department(department_id)
