"""The stages a chat's reply goes through before the model, in order. A personal chat and a channel differ only in
their history stage. Both lists are checked when this module loads (SanitizePipeline._check_order)."""

from app.models import Conversation
from app.services.chat_turn.assemble import ImageFallbackStage, MessagesStage, ModelSwitchStage, StillAskedStage
from app.services.chat_turn.clean_adjust import (
    ChannelHistoryStage,
    CommandStage,
    HistoryStage,
    ModelCheckStage,
    ParamsStage,
    WindowStage,
)
from app.services.chat_turn.enrich import FollowUpStage, LayoutStage, SystemPromptStage
from app.services.chat_turn.sanitize import SanitizePipeline, TurnStage


class ChatPipelines:
    @staticmethod
    def _stages(history: TurnStage) -> list[TurnStage]:
        return [
            ParamsStage(),
            history,
            ModelCheckStage(),
            WindowStage(),
            CommandStage(),
            LayoutStage(),
            FollowUpStage(),
            SystemPromptStage(),
            MessagesStage(),
            ModelSwitchStage(),
            ImageFallbackStage(),
            StillAskedStage(),
        ]

    PERSONAL = SanitizePipeline(_stages(HistoryStage()))
    CHANNEL = SanitizePipeline(_stages(ChannelHistoryStage()))

    @classmethod
    def for_chat(cls, conversation: Conversation) -> SanitizePipeline:
        return cls.PERSONAL if conversation.channel_id is None else cls.CHANNEL
