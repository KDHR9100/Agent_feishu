import asyncio
import json
import logging
import sys
import time
import uuid
import websockets
import requests
import os
import queue
import threading
import traceback

# 强制写入错误日志文件
ERROR_LOG = "/tmp/feishu_ws_error.log"

def log_error(msg):
    with open(ERROR_LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
        f.flush()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("app.log", encoding="utf-8")],
)
logger = logging.getLogger("feishu_ws")

# 消息队列
message_queue: queue.Queue = queue.Queue()


def get_wss_token(app_id: str, app_secret: str) -> str:
    """获取飞书 WebSocket 连接用的 wss_token"""
    url = "https://open.feishu.cn/open-apis/ws/v1/token"
    payload = {"app_id": app_id, "app_secret": app_secret}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("token", "")
            else:
                log_error(f"Failed to get wss_token: {data.get('msg')}")
        else:
            log_error(f"HTTP error: {response.status_code}")
    except Exception as e:
        log_error(f"Error getting wss_token: {str(e)}")
    return ""


def do_p2_im_message_receive_v1(data):
    logger.info("[Feishu WS] ===== EVENT RECEIVED in do_p2_im_message_receive_v1 =====")
    start_time = time.time()
    track_id = str(uuid.uuid4())[:8]

    try:
        # 打印原始事件
        try:
            raw_json = json.dumps(data, ensure_ascii=False, default=str)
            logger.info("[Feishu WS] [%s] RAW EVENT: %s", track_id, raw_json[:1000])
        except Exception:
            logger.info("[Feishu WS] [%s] RAW EVENT (unserializable): %s", track_id, str(data)[:500])

        event = data.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})
        message_id = message.get("message_id", "")
        chat_id = message.get("chat_id", "")
        msg_type = message.get("msg_type", "text")
        content_raw = message.get("content", "{}")
        mentions = message.get("mentions", [])
        sender_id = sender.get("sender_id", {}).get("open_id", "")

        logger.info("[Feishu WS] [%s] msg_type=%s, chat_id=%s", track_id, msg_type, chat_id)

        bot_name = os.getenv("FEISHU_BOT_NAME", "Ecommerce Agent")
        is_group_chat = chat_id.startswith("oc_")

        if is_group_chat:
            bot_mentioned = False
            for m in mentions:
                m_name = m.get("name", "")
                m_key = m.get("key", "")
                if m_name == bot_name or bot_name in m_key:
                    bot_mentioned = True
                    break
            if not bot_mentioned:
                logger.info("[Feishu WS] [%s] Group chat without mention, ignoring", track_id)
                return
        else:
            logger.info("[Feishu WS] [%s] Private chat, proceeding", track_id)

        text_content = ""
        file_info = None

        if msg_type == "text":
            try:
                text_content = json.loads(content_raw).get("text", "")
            except Exception:
                text_content = ""
            for mention in mentions:
                key = mention.get("key", "")
                if key:
                    text_content = text_content.replace(key, "").strip()

        elif msg_type in ["file", "media"]:
            try:
                content_json = json.loads(content_raw)
                file_key = content_json.get("file_key") or content_json.get("file_token") or content_json.get("media_id") or ""
                file_name = content_json.get("file_name", "unknown")
                file_size = content_json.get("file_size", 0)
                if file_key:
                    file_info = {"file_key": file_key, "file_name": file_name, "file_size": file_size}
                    text_content = f"[文件] {file_name}"
                    logger.info("[Feishu WS] [%s] File detected - key=%s, name=%s", track_id, file_key, file_name)
                else:
                    logger.warning("[Feishu WS] [%s] File message but no key found: %s", track_id, content_json)
                    text_content = "[文件] 无法获取文件标识"
            except Exception as e:
                text_content = "[文件] 解析失败"
                logger.error("[Feishu WS] [%s] Failed to parse file: %s", track_id, str(e))
        else:
            logger.info("[Feishu WS] [%s] Unhandled msg_type: %s", track_id, msg_type)
            return

        logger.info("[Feishu WS] [%s] Content: %s", track_id, text_content[:100])

        message_queue.put({
            "track_id": track_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "content": text_content,
            "sender_id": sender_id,
            "receive_time": start_time,
            "msg_type": msg_type,
            "file_info": file_info
        })
        logger.info("[Feishu WS] [%s] Queued (file_info=%s)", track_id, file_info is not None)

    except Exception as e:
        logger.error("[Feishu WS] [%s] Failed to process event: %s", track_id, str(e), exc_info=True)


async def feishu_ws_client(app_id: str, app_secret: str):
    log_error("feishu_ws_client called")
    token = get_wss_token(app_id, app_secret)   # 改为获取 wss_token
    if not token:
        log_error("Failed to get wss_token, aborting")
        return

    ws_url = f"wss://ws.feishu.cn/ws?token={token}"
    log_error(f"Connecting to {ws_url[:80]}...")
    logger.info("[Feishu WS] Connecting to: %s", ws_url[:80] + "...")


    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as websocket:
                logger.info("[Feishu WS] WebSocket connected successfully!")
                log_error("WebSocket connected")
                await websocket.send(json.dumps({
                    "type": "auth",
                    "app_id": app_id,
                    "app_secret": app_secret
                }))
                logger.info("[Feishu WS] Auth message sent, waiting for response...")

                async for message in websocket:
                    try:
                        data = json.loads(message)
                        event_type = data.get("type", "")
                        log_error(f"Received event type: {event_type}")

                        if event_type == "auth_success":
                            logger.info("[Feishu WS] Authentication successful!")
                        elif event_type == "auth_fail":
                            logger.error("[Feishu WS] Authentication failed: %s", data)
                            return
                        elif event_type == "event":
                            logger.info("[Feishu WS] Event received, calling handler...")
                            do_p2_im_message_receive_v1(data)
                        elif event_type == "ping":
                            await websocket.send(json.dumps({"type": "pong"}))
                            logger.debug("[Feishu WS] Pong sent")
                        else:
                            logger.debug("[Feishu WS] Unhandled message type: %s", event_type)
                    except json.JSONDecodeError:
                        logger.warning("[Feishu WS] Failed to parse message: %s", message[:200])
                    except Exception as e:
                        logger.error("[Feishu WS] Error processing message: %s", str(e))

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("[Feishu WS] Connection closed: %s, reconnecting in 5s...", str(e))
            log_error(f"Connection closed: {e}")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error("[Feishu WS] Connection error: %s, reconnecting in 5s...", str(e))
            log_error(f"Connection error: {e}")
            await asyncio.sleep(5)


def process_messages():
    """消息处理线程"""
    try:
        from app.tools.feishu_tool import feishu_tool
        from app.tools.file_parser_tool import file_parser_tool
        from app.agent.workflow import agent
        from app.monitoring import monitoring_stats
        logger.info("[Feishu WS] Processor started")
    except Exception as e:
        logger.error("[Feishu WS] Failed to init processor: %s", str(e))
        return

    while True:
        try:
            msg = message_queue.get(timeout=1)
            if msg is None:
                break

            track_id = msg.get("track_id", "unknown")
            logger.info("[Feishu WS] [%s] Processing message", track_id)

            file_path = None
            file_content = None
            file_info = msg.get("file_info")

            if file_info:
                try:
                    file_key = file_info.get("file_key", "")
                    file_name = file_info.get("file_name", "unknown")
                    save_path = f"data/uploads/{file_name}"

                    logger.info("[Feishu WS] [%s] Downloading file: %s", track_id, file_key)
                    download_result = feishu_tool.download_file(file_key, save_path)

                    if download_result.get("success"):
                        file_path = save_path
                        logger.info("[Feishu WS] [%s] File downloaded: %s", track_id, file_path)

                        parse_result = file_parser_tool.parse_local_file(file_path)
                        if parse_result.get("error"):
                            logger.error("[Feishu WS] [%s] Parse error: %s", track_id, parse_result.get("error"))
                        else:
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
                            logger.info("[Feishu WS] [%s] File parsed: %d rows", track_id, row_count)
                    else:
                        logger.warning("[Feishu WS] [%s] Download failed: %s", track_id, download_result.get("error"))
                except Exception as e:
                    logger.error("[Feishu WS] [%s] File error: %s", track_id, str(e))

            try:
                agent_input = {
                    "user_input": msg["content"],
                    "conversation_id": msg["chat_id"]
                }
                if file_path:
                    agent_input["file_path"] = file_path
                if file_content:
                    agent_input["file_content"] = file_content

                result = agent.invoke(agent_input)
                answer = result.get("answer", "抱歉，我无法处理您的请求。")
                logger.info("[Feishu WS] [%s] Agent done, answer length=%d", track_id, len(answer))

            except Exception as e:
                logger.error("[Feishu WS] [%s] Agent error: %s", track_id, str(e))
                answer = f"处理时出错：{str(e)}"

            try:
                feishu_tool.reply_message(msg["message_id"], answer)
                logger.info("[Feishu WS] [%s] Reply sent", track_id)
            except Exception as e:
                logger.error("[Feishu WS] [%s] Reply failed: %s", track_id, str(e))

        except queue.Empty:
            continue
        except Exception as e:
            logger.error("[Feishu WS] Processor error: %s", str(e))


def start_feishu_ws(app_id: str, app_secret: str):
    """启动飞书 WebSocket 客户端"""
    log_error(f"start_feishu_ws called with app_id={app_id[:8]}...")
    if not app_id or not app_secret:
        logger.error("[Feishu WS] No credentials provided")
        return

    threading.Thread(target=process_messages, daemon=True).start()
    logger.info("[Feishu WS] Processor thread started")

    try:
        asyncio.run(feishu_ws_client(app_id, app_secret))
    except Exception as e:
        error_msg = f"Fatal error in asyncio.run: {str(e)}\n{traceback.format_exc()}"
        logger.error("[Feishu WS] %s", error_msg)
        log_error(error_msg)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        app_id = sys.argv[1]
        app_secret = sys.argv[2]
        start_feishu_ws(app_id, app_secret)
    else:
        logger.error("[Feishu WS] Missing app_id or app_secret arguments")
        sys.exit(1)