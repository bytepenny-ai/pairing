"""Whether the chat sidebar shows the Images Gen link: only while an image engine can take a job.

Checked on every page load, so it never contacts a server: local mode needs a live sd-server process, remote mode a
configured host. Off in a ring (image_gen_ring.py) hides it too.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import image_engine_service, sdcpp_process
from app.services.image_gen_ring import image_gen_ring


class ImageGenLink:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def shown(self) -> bool:
        if await image_gen_ring.is_off(self.db):
            return False
        config = await image_engine_service.get_sdcpp_config(self.db)
        if config.mode == "remote":
            return bool(config.remote_hosts)
        tracked = sdcpp_process.read_tracking()
        return bool(tracked and config.binary_path and sdcpp_process.is_alive(tracked["pid"], config.binary_path))
