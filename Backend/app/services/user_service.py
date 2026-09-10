from beanie import PydanticObjectId
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import get_password_hash
from app.repositories.user_repository import UserRepository


class UserNotFoundException(Exception):
    """Exception raised when a user is not found."""
    def __init__(self, message: str = "User not found"):
        self.message = message
        super().__init__(self.message)


class UserAlreadyExistsException(Exception):
    """Exception raised when a user with the same username or email already exists."""
    def __init__(self, message: str = "A user with this username or email already exists."):
        self.message = message
        super().__init__(self.message)


class UserService:
    """
    Service layer for managing User business operations.
    Communicates strictly via UserRepository and handles all business validation.
    """

    def __init__(self, repository: UserRepository | None = None):
        self.repository = repository or UserRepository()

    async def create_user(self, user_in: UserCreate) -> User:
        """
        Create a new user with duplicate username/email validation and password hashing.
        """
        existing_username = await self.repository.get_user_by_username(user_in.username)
        if existing_username:
            raise UserAlreadyExistsException("A user with this username already exists.")

        if user_in.email:
            existing_email = await self.repository.get_user_by_email(user_in.email)
            if existing_email:
                raise UserAlreadyExistsException("A user with this email address already exists.")

        hashed_password = get_password_hash(user_in.password)
        new_user = User(
            username=user_in.username,
            name=user_in.name,
            email=user_in.email,
            password=hashed_password,
            role=user_in.role,
            department_code=user_in.department_code,
            register_number=user_in.register_number,
            mobile_number=user_in.mobile_number,
            is_active=True,
        )
        return await self.repository.create_user(new_user)

    async def get_user_by_id(self, user_id: PydanticObjectId) -> User:
        """
        Retrieve a user by its ID, raising an exception if it doesn't exist.
        """
        user = await self.repository.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundException()
        return user

    async def get_all_users(self) -> list[User]:
        """
        Retrieve all users.
        """
        return await self.repository.get_all_users()

    async def reset_password(self, user_id: PydanticObjectId, new_password: str) -> User:
        """
        Reset a user's password.
        """
        user = await self.get_user_by_id(user_id)
        hashed_password = get_password_hash(new_password)
        updated = await self.repository.update_user(user_id, {"password": hashed_password})
        if not updated:
            raise UserNotFoundException()
        return updated

    async def toggle_user_status(self, user_id: PydanticObjectId, is_active: bool) -> User:
        """
        Enable or disable a user.
        """
        user = await self.get_user_by_id(user_id)
        updated = await self.repository.update_user(user_id, {"is_active": is_active})
        if not updated:
            raise UserNotFoundException()
        return updated

    async def update_user(self, user_id: PydanticObjectId, update_data: dict) -> User:
        """
        Update selected fields of a user.
        """
        user = await self.repository.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundException()

        new_username = update_data.get("username")
        if new_username is not None and new_username != user.username:
            existing = await self.repository.get_user_by_username(new_username)
            if existing:
                raise UserAlreadyExistsException("A user with this username already exists.")

        new_email = update_data.get("email")
        if new_email is not None and new_email != user.email:
            existing = await self.repository.get_user_by_email(new_email)
            if existing:
                raise UserAlreadyExistsException("A user with this email address already exists.")

        new_password = update_data.get("password")
        if new_password is not None:
            update_data["password"] = get_password_hash(new_password)

        updated_user = await self.repository.update_user(user_id, update_data)
        if not updated_user:
            raise UserNotFoundException()
        return updated_user

    async def delete_user(self, user_id: PydanticObjectId) -> bool:
        """
        Delete a user by ID.
        """
        user = await self.repository.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundException()
        return await self.repository.delete_user(user_id)
