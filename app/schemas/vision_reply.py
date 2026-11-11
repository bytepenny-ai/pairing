"""Admin settings > Models > Default models: what a reply to an image includes (vision_reply_setting.py)."""

from typing import Literal

from pydantic import BaseModel

# "all": notes and skills (as for text); "notes": notes only; "none": just the message and the image (the default:
# fast on a CPU; an admin can turn notes and skills back on).
VisionReplyContext = Literal["all", "notes", "none"]


class VisionReplySetting(BaseModel):
    include: VisionReplyContext = "none"
