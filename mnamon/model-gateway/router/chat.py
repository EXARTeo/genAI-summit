from fastapi import APIRouter, HTTPException, status

from core.logging import get_logger
from schema.chat import ChatRequest, ChatResponse
from utils.chatbot import reply

router = APIRouter()
logger = get_logger(__name__)

CHATBOT_MODEL = "sys-004-support-bot-simulated"


@router.post("/sys-004", response_model=ChatResponse)
async def chat_sys004(body: ChatRequest) -> ChatResponse:
    user_turns = [m.content for m in body.messages if m.role == "user"]
    if not user_turns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one message with role 'user' is required.",
        )
    text, intent = reply(user_turns[-1])
    # The intent only, never the message content (may hold personal data).
    logger.info("chat_replied", "SYS-004 reply served", intent=intent, turns=len(body.messages))
    return ChatResponse(reply=text, model=CHATBOT_MODEL)
