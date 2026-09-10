from beanie import PydanticObjectId
from app.models.user import User


class UserRepository:
    """
    Repository handling direct database operations for the User model using Beanie.
    Contains no business validation, HTTP dependencies, or FastAPI concepts.
    """

    async def create_user(self, user: User) -> User:
        """
        Insert a new user document into MongoDB.
        """
        return await user.insert()

    async def get_user_by_id(self, user_id: PydanticObjectId) -> User | None:
        """
        Find a user by its PydanticObjectId.
        Returns None if no matching user exists.
        """
        return await User.get(user_id)

    async def get_user_by_username(self, username: str) -> User | None:
        """
        Find a user by username (exact match).
        """
        return await User.find_one(User.username == username)

    async def get_user_by_username_or_email(self, identifier: str) -> User | None:
        """
        Find a user by username or email.
        """
        user = await User.find_one(User.username == identifier)
        if user:
            return user
        return await User.find_one(User.email == identifier)

    async def get_user_by_email(self, email: str) -> User | None:
        """
        Find a user by email (exact match).
        """
        return await User.find_one(User.email == email)

    async def get_all_users(self) -> list[User]:
        """
        Retrieve all users in the database.
        """
        return await User.find_all().to_list()

    async def update_user(self, user_id: PydanticObjectId, update_data: dict) -> User | None:
        """
        Update selected fields of a user.
        Only fields present in the update_data dictionary will be modified.
        Returns the updated User document, or None if not found.
        """
        user = await User.get(user_id)
        if not user:
            return None

        for key, value in update_data.items():
            if hasattr(user, key):
                setattr(user, key, value)

        await user.save()
        return user

    async def delete_user(self, user_id: PydanticObjectId) -> bool:
        """
        Hard delete a user from the database by its ID.
        Returns True if the deletion succeeded, False if the user did not exist.
        """
        user = await User.get(user_id)
        if not user:
            return False

        await user.delete()
        return True
