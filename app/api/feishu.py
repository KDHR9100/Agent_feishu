from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
import logging

from app.agents.coordinator import coordinator
from app.agent.workflow import agent
from app.tools.feishu_tool import feishu_tool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/feishu",
    tags=["feishu"]
)

class MessageRequest(BaseModel):
    chat_id: str
    content: str
    user_id: Optional[str] = None
    message_type: str = "text"

@router.post("/webhook")
async def feishu_webhook(request: Request):

    try:

        body = await request.json()

        logger.info(
            "Feishu webhook received: %s",
            json.dumps(
                body,
                ensure_ascii=False
            )
        )

        # ==================================
        # 1. 飞书首次验证
        # ==================================

        if body.get("type") == "url_verification":

            return {
                "challenge":
                body.get("challenge")
            }

        # ==================================
        # 2. 判断事件类型
        # ==================================

        header = body.get(
            "header",
            {}
        )

        event_type = header.get(
            "event_type"
        )

        logger.info(
            "event_type=%s",
            event_type
        )

        if event_type != "im.message.receive_v1":

            return {
                "status": "ignored",
                "event_type": event_type
            }

        # ==================================
        # 3. 解析消息
        # ==================================

        event = body.get(
            "event",
            {}
        )

        message = event.get(
            "message",
            {}
        )

        content_raw = message.get(
            "content",
            "{}"
        )

        try:

            content_json = json.loads(
                content_raw
            )

            content = content_json.get(
                "text",
                ""
            )

        except Exception:

            content = ""

        chat_id = message.get(
            "chat_id",
            ""
        )

        sender = event.get(
            "sender",
            {}
        )

        user_id = (
            sender
            .get("sender_id", {})
            .get("user_id", "")
        )

        logger.info(
            "User=%s Chat=%s Message=%s",
            user_id,
            chat_id,
            content
        )

        if not content:

            raise HTTPException(
                status_code=400,
                detail="Empty message"
            )

        # ==================================
        # 4. 调用 Agent
        # ==================================

        result = coordinator.route_and_coordinate(
            content
        )

        answer = result.get(
            "summary",
            str(result)
        )

        logger.info(
            "Agent answer=%s",
            answer
        )

        # ==================================
        # 5. 回复飞书
        # ==================================

        if (
            feishu_tool.app_id
            and feishu_tool.app_secret
            and chat_id
        ):

            send_result = (
                feishu_tool.send_message(
                    chat_id,
                    answer
                )
            )

            logger.info(
                "Feishu send result=%s",
                send_result
            )

        else:

            logger.warning(
                "Feishu credentials missing"
            )

        return {

            "status":
            "success",

            "answer":
            answer

        }

    except Exception as e:

        logger.exception(
            "Feishu webhook failed"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@router.post("/message")
async def send_message(
    request: MessageRequest
):

    try:

        if (
            feishu_tool.app_id
            and feishu_tool.app_secret
        ):

            result = (
                feishu_tool.send_message(
                    request.chat_id,
                    request.content
                )
            )

            return {

                "status":
                "success",

                "response":
                result

            }

        return {

            "status":
            "failed",

            "message":
            "Feishu credentials not configured"

        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@router.post("/chat")
async def chat_with_agent(
    request: Request
):

    try:

        body = await request.json()

        user_input = body.get(
            "message",
            ""
        )

        conversation_id = body.get(
            "conversation_id",
            "default"
        )

        if not user_input:

            raise HTTPException(
                status_code=400,
                detail="Message is required"
            )

        result = agent.invoke(
            {
                "user_input":
                user_input,

                "conversation_id":
                conversation_id
            }
        )

        return {

            "status":
            "success",

            "answer":
            result.get(
                "answer",
                ""
            ),

            "conversation_id":
            conversation_id

        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
