"""Admin settings > System > Chat > "Files in a chat" (chat_file_memory_setting.py)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# How a question about an earlier image is answered: "off" from the reply that described it; "again" the vision model
# reads the image again; "fallback" the description first, the image only when the chat's model says it needs it.
ImageFollowUp = Literal["off", "again", "fallback"]


class ChatFileMemorySetting(BaseModel):
    # A file up to this share of the context window stays whole in the chat; a longer one is searched per question.
    whole_file_percent: int = Field(25, ge=5, le=90)
    image_follow_up: ImageFollowUp = "off"
    # How close in meaning (0 to 1, embedding similarity) a question is to an earlier image's description or a long
    # file's best-matching part: from `related_above` it is used, under `unrelated_below` never; in between, an image
    # follows the recency rule and a file's matching parts are still given.
    related_above: float = Field(0.35, ge=0.0, le=1.0)
    unrelated_below: float = Field(0.10, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _marks_in_order(self) -> "ChatFileMemorySetting":
        if self.unrelated_below > self.related_above:
            raise ValueError("The 'unrelated' mark must not be above the 'about the image' mark.")
        return self

    @field_validator("image_follow_up", mode="before")
    @classmethod
    def _from_on_off(cls, value: object) -> object:
        """Stored by the first version as a checkbox: on was "again"."""
        if isinstance(value, bool):
            return "again" if value else "off"
        return value
