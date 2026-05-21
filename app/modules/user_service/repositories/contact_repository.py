from sqlalchemy.ext.asyncio import AsyncSession
from app.config.base_repositories import BaseRepository
from app.modules.user_service.models.contact_model import ContactMessage

class ContactRepository(BaseRepository[ContactMessage]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, ContactMessage)
