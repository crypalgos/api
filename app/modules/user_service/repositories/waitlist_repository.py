from sqlalchemy.ext.asyncio import AsyncSession
from app.config.base_repositories import BaseRepository
from app.modules.user_service.models.waitlist_model import Waitlist

class WaitlistRepository(BaseRepository[Waitlist]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Waitlist)
