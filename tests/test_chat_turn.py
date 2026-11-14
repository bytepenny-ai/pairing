"""The stages a chat reply goes through before the model (app/services/chat_turn), each on its own with a hand-made
ChatTurn, and the pipeline that orders them."""

from types import SimpleNamespace

import pytest

from app.models import Message
from app.schemas import ConversationCreate
from app.services import channel_history_setting, chat_attachment_service, conversation_service, model_catalog_service
from app.services.chat_attachment_service import AttachmentInfo
from app.services.chat_turn.assemble import MessagesStage, ModelSwitchStage, StillAskedStage
from app.services.chat_turn.clean_adjust import ChannelHistoryStage, CommandStage, HistoryStage, ParamsStage
from app.services.chat_turn.pipeline import ChatPipelines
from app.services.chat_turn.sanitize import CheckStage, PipelineOrderError, SanitizePipeline, TurnStage
from app.services.chat_turn.turn import ChatTurn
from app.services.prompt_layout.base import PromptLayout


async def _turn(db, user, content="hello", attachments=None) -> ChatTurn:
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    message = Message(conversation_id=conversation.id, role="user", content=content, sender_id=user.id)
    db.add(message)
    await db.commit()
    return ChatTurn(db, conversation, user, message, content, attachments or [], True)


class _Notice(TurnStage):
    name = "notice"
    provides = frozenset({"question"})

    async def run(self, turn: ChatTurn) -> list[str]:
        turn.question = "set"
        return ["cut"]


class _Stop(CheckStage):
    name = "stop"

    async def run(self, turn: ChatTurn) -> list[str]:
        turn.stopped = True
        return []


class _NeedsLayout(TurnStage):
    name = "needs_layout"
    requires = frozenset({"layout"})

    async def run(self, turn: ChatTurn) -> list[str]:
        return []


def test_a_stage_before_what_it_needs_fails_when_the_pipeline_is_built():
    with pytest.raises(PipelineOrderError, match="needs_layout needs"):
        SanitizePipeline([_NeedsLayout()])


def test_personal_chats_and_channels_differ_only_in_their_history_stage():
    personal = [type(s) for s in ChatPipelines.PERSONAL.stages]
    channel = [type(s) for s in ChatPipelines.CHANNEL.stages]
    assert personal[1] is HistoryStage and channel[1] is ChannelHistoryStage
    assert personal[:1] + personal[2:] == channel[:1] + channel[2:]
    assert ChatPipelines.for_chat(SimpleNamespace(channel_id="c")) is ChatPipelines.CHANNEL
    assert ChatPipelines.for_chat(SimpleNamespace(channel_id=None)) is ChatPipelines.PERSONAL


@pytest.mark.asyncio
async def test_the_pipeline_yields_notices_and_stops_where_a_check_says(db, user):
    turn = await _turn(db, user)
    pipeline = SanitizePipeline([_Notice(), _Stop(), _Notice()])
    turn.question = ""
    events = [e async for e in pipeline.run(turn)]
    assert events == [{"notice": "cut"}] and turn.stopped  # the stage after the stop never ran


@pytest.mark.asyncio
async def test_params_keep_room_for_the_reply(db, user):
    turn = await _turn(db, user)
    turn.conversation.params = {"num_predict": 2048}
    await ParamsStage().run(turn)
    assert turn.reserved_tokens == 2048 and turn.params["num_ctx"] > 0
    turn.conversation.params = {}
    await ParamsStage().run(turn)
    assert turn.reserved_tokens == 512


@pytest.mark.asyncio
async def test_the_command_is_removed_and_an_image_is_noticed(db, user, tmp_path):
    image = AttachmentInfo(tmp_path / "a.png", "a.png", "image")
    turn = await _turn(db, user, '/use_skill "Review" is this safe?', [image])
    await CommandStage().run(turn)
    assert turn.question == "is this safe?" and turn.has_image


@pytest.mark.asyncio
async def test_a_channel_may_keep_only_the_posts_for_the_ai(db, user, monkeypatch):
    async def plain(_db):
        return False

    turn = await _turn(db, user)
    calls: list[int] = []
    monkeypatch.setattr(channel_history_setting, "get_include_plain_messages", plain)
    monkeypatch.setattr(
        "app.services.chat_history_service.only_addressed_to_ai", lambda past: calls.append(len(past)) or []
    )
    await ChannelHistoryStage().run(turn)
    assert calls and turn.past == []


@pytest.mark.asyncio
async def test_messages_put_the_turns_files_on_the_newest_user_message(db, user):
    turn = await _turn(db, user)
    turn.plan = SimpleNamespace(history=[{"role": "user", "content": "q"}], image_again=None)
    turn.layout, turn.system_prompt, turn.turn_context = PromptLayout("sys"), "sys", "excerpt"
    await MessagesStage().run(turn)
    assert turn.chat_messages[0] == {"role": "system", "content": "sys"}
    assert turn.chat_messages[1]["content"].startswith("excerpt")


@pytest.mark.asyncio
async def test_a_model_that_sees_images_answers_them_itself(db, user, tmp_path, monkeypatch):
    attached: list[int] = []
    monkeypatch.setattr(chat_attachment_service, "attach_image", lambda files, _msgs: attached.append(len(files)))

    async def installed(_db, _user, model):
        return model

    monkeypatch.setattr(model_catalog_service, "resolve_installed_model", installed)
    turn = await _turn(db, user)
    turn.sees_images, turn.reply_files = True, [AttachmentInfo(tmp_path / "a.png", "a.png", "image")]
    await ModelSwitchStage().run(turn)
    assert attached == [1] and turn.reply_model is None


@pytest.mark.asyncio
async def test_a_deleted_question_stops_the_turn(db, user):
    turn = await _turn(db, user)
    await StillAskedStage().run(turn)
    assert not turn.stopped
    turn.message.status = "deleted"
    await db.commit()
    await StillAskedStage().run(turn)
    assert turn.stopped
