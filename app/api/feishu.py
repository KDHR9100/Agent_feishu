from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
import logging
import os
import time
import uuid

from app.agents.coordinator import coordinator
from app.agent.workflow import agent
from app.tools.feishu_tool import feishu_tool
from app.tools.file_parser_tool import file_parser_tool

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
    track_id = str(uuid.uuid4())[:8]
    try:
        body = await request.json()
        logger.info("[Feishu] [%s] Webhook received: %s", track_id, json.dumps(body, ensure_ascii=False)[:500])

        # ============================================================
        # 1. 飞书首次验证（url_verification）
        # ============================================================
        if body.get("type") == "url_verification":
            logger.info("[Feishu] [%s] URL verification request", track_id)
            return {"challenge": body.get("challenge")}

        # ============================================================
        # 2. 判断事件类型
        # ============================================================
        header = body.get("header", {})
        event_type = header.get("event_type")
        logger.info("[Feishu] [%s] event_type=%s", track_id, event_type)

        if event_type != "im.message.receive_v1":
            return {"status": "ignored", "event_type": event_type}

        # ============================================================
        # 3. 解析消息（支持文本和文件）
        # ============================================================
        event = body.get("event", {})
        message = event.get("message", {})
        message_id = message.get("message_id", "")
        chat_id = message.get("chat_id", "")
        msg_type = message.get("msg_type", "text")
        content_raw = message.get("content", "{}")

        sender = event.get("sender", {})
        user_id = sender.get("sender_id", {}).get("user_id", "")

        logger.info("[Feishu] [%s] msg_type=%s, chat_id=%s, message_id=%s", track_id, msg_type, chat_id, message_id)

        # ============================================================
        # 3a. 文本消息
        # ============================================================
        text_content = ""
        file_path = None
        file_content = None

        if msg_type == "text":
            try:
                content_json = json.loads(content_raw)
                text_content = content_json.get("text", "")
            except Exception as e:
                logger.error("[Feishu] [%s] Failed to parse text content: %s", track_id, str(e))
                text_content = ""

            # 去除 @机器人 的提及
            mentions = message.get("mentions", [])
            if mentions:
                for mention in mentions:
                    key = mention.get("key", "")
                    if key:
                        text_content = text_content.replace(key, "").strip()

        # ============================================================
        # 3b. 文件消息（新增！）
        # ============================================================
        elif msg_type in ["file", "media"]:
            try:
                content_json = json.loads(content_raw)
                # 兼容多种字段名
                file_key = content_json.get("file_key") or content_json.get("file_token") or content_json.get("media_id") or ""
                file_name = content_json.get("file_name", "unknown")
                file_size = content_json.get("file_size", 0)

                logger.info("[Feishu] [%s] File detected - key=%s, name=%s, size=%d", track_id, file_key, file_name, file_size)

                if file_key:
                    # 下载文件
                    save_path = f"data/uploads/{file_name}"
                    download_result = feishu_tool.download_file(file_key, save_path)

                    if download_result.get("success"):
                        file_path = save_path
                        logger.info("[Feishu] [%s] File downloaded: %s", track_id, file_path)

                        # 解析文件
                        parse_result = file_parser_tool.parse_local_file(file_path)
                        if parse_result.get("error"):
                            logger.error("[Feishu] [%s] File parse error: %s", track_id, parse_result.get("error"))
                            file_content = None
                        else:
                            # 构建文件内容摘要
                            summary = parse_result.get("summary", {})
                            columns = parse_result.get("columns", [])
                            row_count = parse_result.get("row_count", 0)
                            sample_rows = parse_result.get("sample_rows", [])

                            content_parts = [
                                f"文件信息: {file_name}",
                                f"列: {', '.join(columns)}",
                                f"行数: {row_count}",
                                "数据摘要:"
                            ]
                            for col, info in summary.items():
                                if info.get("type") == "numeric":
                                    content_parts.append(f"  - {col}: 均值={info.get('mean', 'N/A'):.2f}, 最大={info.get('max', 'N/A')}, 最小={info.get('min', 'N/A')}")
                                else:
                                    content_parts.append(f"  - {col}: 去重数={info.get('unique_count', 'N/A')}, 样例={info.get('sample_values', [])}")

                            if sample_rows:
                                content_parts.append("数据样例 (前3行):")
                                for i, row in enumerate(sample_rows):
                                    content_parts.append(f"  第{i+1}行: {row}")

                            file_content = "\n".join(content_parts)
                            logger.info("[Feishu] [%s] File parsed: %d rows, %d columns", track_id, row_count, len(columns))
                    else:
                        logger.warning("[Feishu] [%s] File download failed: %s", track_id, download_result.get("error"))
                        text_content = f"[文件] {file_name} (下载失败)"
                else:
                    text_content = "[文件] 无法获取文件标识"

            except Exception as e:
                logger.error("[Feishu] [%s] Failed to parse file message: %s", track_id, str(e))
                text_content = "[文件] 解析失败"

        else:
            logger.info("[Feishu] [%s] Unhandled msg_type: %s", track_id, msg_type)
            return {"status": "ignored", "msg_type": msg_type}

        # ============================================================
        # 3c. 确定最终用户输入
        # ============================================================
        if not text_content and not file_content:
            logger.warning("[Feishu] [%s] Empty message", track_id)
            return {"status": "ignored", "reason": "empty content"}

        user_input = text_content if text_content else f"请分析我上传的文件"

        logger.info("[Feishu] [%s] User=%s, Chat=%s, Input=%s", track_id, user_id, chat_id, user_input[:100])

        # ============================================================
        # 4. 调用 Agent Workflow（支持文件参数）
        # ============================================================
        try:
            agent_input = {
                "user_input": user_input,
                "conversation_id": chat_id  # 使用 chat_id 作为会话 ID
            }

            if file_path:
                agent_input["file_path"] = file_path
                logger.info("[Feishu] [%s] File path added to agent input", track_id)

            if file_content:
                agent_input["file_content"] = file_content
                logger.info("[Feishu] [%s] File content added to agent input (length=%d)", track_id, len(file_content))

            result = agent.invoke(agent_input)
            answer = result.get("answer", "抱歉，我无法处理您的请求。")

            logger.info("[Feishu] [%s] Agent completed, answer length=%d", track_id, len(answer))

        except Exception as e:
            logger.error("[Feishu] [%s] Agent error: %s", track_id, str(e))
            answer = f"处理您的问题时出错：{str(e)}"

        # ============================================================
        # 5. 回复飞书
        # ============================================================
        if feishu_tool.app_id and feishu_tool.app_secret and chat_id and answer:
            # 如果回复太长，飞书消息有长度限制（大约 8000 字符），可截断
            if len(answer) > 7500:
                answer = answer[:7500] + "\n\n...(回复内容过长，已截断)"

            send_result = feishu_tool.send_message(chat_id, answer)
            logger.info("[Feishu] [%s] Reply sent: %s", track_id, send_result.get("code") == 0)
        else:
            logger.warning("[Feishu] [%s] Missing credentials or chat_id", track_id)

        return {"status": "success", "answer": answer[:200]}

    except Exception as e:
        logger.exception("[Feishu] [%s] Webhook failed: %s", track_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/message")
async def send_message(request: MessageRequest):
    try:
        if feishu_tool.app_id and feishu_tool.app_secret:
            result = feishu_tool.send_message(request.chat_id, request.content)
            return {"status": "success", "response": result}
        return {"status": "failed", "message": "Feishu credentials not configured"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def chat_with_agent(request: Request):
    try:
        body = await request.json()
        user_input = body.get("message", "")
        conversation_id = body.get("conversation_id", "default")

        if not user_input:
            raise HTTPException(status_code=400, detail="Message is required")

        result = agent.invoke({
            "user_input": user_input,
            "conversation_id": conversation_id
        })

        return {
            "status": "success",
            "answer": result.get("answer", ""),
            "conversation_id": conversation_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))