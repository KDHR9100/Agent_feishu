import lark_oapi as lark
import logging
import time
import sys
import json
import threading
import queue
import uuid
import os

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("feishu_ws")
message_queue: queue.Queue = queue.Queue()


def do_p2_im_message_receive_v1(data):
    start_time = time.time()
    track_id = str(uuid.uuid4())[:8]

    # ============================================================
    # 无条件打印原始事件（用于调试）
    # ============================================================
    try:
        raw_json = json.dumps(data, ensure_ascii=False, default=str)
        logger.info(
            "[Feishu WS] [%s] RAW EVENT (full): %s" % (track_id, raw_json[:1000])
        )
    except Exception:
        logger.info(
            "[Feishu WS] [%s] RAW EVENT (unserializable): %s"
            % (track_id, str(data)[:500])
        )

    try:
        # 尝试解析事件
        try:
            event_data = lark.JSON.marshal(data, indent=4)
            event_dict = json.loads(event_data)
        except Exception:
            event_dict = data

        message = event_dict.get("event", {}).get("message", {})
        sender = event_dict.get("event", {}).get("sender", {})
        message_id = message.get("message_id", "")
        chat_id = message.get("chat_id", "")
        msg_type = message.get("msg_type", "text")
        content_raw = message.get("content", "{}")
        mentions = message.get("mentions", [])
        sender_id = sender.get("sender_id", {}).get("open_id", "")

        logger.info(
            "[Feishu WS] [%s] Parsed - msg_type=%s, message_id=%s, chat_id=%s"
            % (track_id, msg_type, message_id, chat_id)
        )

        # Check if bot was mentioned in group chat
        bot_name = os.getenv("FEISHU_BOT_NAME", "Ecommerce Agent")
        is_group_chat = chat_id.startswith("oc_")

        if is_group_chat:
            bot_mentioned = False
            if mentions:
                for m in mentions:
                    m_name = m.get("name", "")
                    m_key = m.get("key", "")
                    if m_name == bot_name or bot_name in m_key:
                        bot_mentioned = True
                        break
            if not bot_mentioned:
                logger.info(
                    "[Feishu WS] [%s] Group chat without mention, ignoring" % track_id
                )
                return
        else:
            logger.info("[Feishu WS] [%s] Private chat, proceeding" % track_id)

        text_content = ""
        file_info = None

        # ============================================================
        # 处理文件类型消息（兼容多种 msg_type）
        # ============================================================
        if msg_type == "text":
            try:
                text_content = json.loads(content_raw).get("text", "")
            except Exception:
                text_content = ""
            if mentions:
                for mention in mentions:
                    key = mention.get("key", "")
                    if key:
                        text_content = text_content.replace(key, "").strip()
        elif msg_type in ["file", "media"]:
            # 飞书文件消息可能是 "file" 或 "media"
            try:
                content_json = json.loads(content_raw)
                # 尝试多种可能的字段名
                file_key = (
                    content_json.get("file_key")
                    or content_json.get("file_token")
                    or content_json.get("media_id")
                    or ""
                )
                file_name = content_json.get("file_name", "unknown")
                file_size = content_json.get("file_size", 0)
                if file_key:
                    file_info = {
                        "file_key": file_key,
                        "file_name": file_name,
                        "file_size": file_size,
                    }
                    text_content = f"[文件] {file_name}"
                    logger.info(
                        "[Feishu WS] [%s] File detected - Key: %s, Name: %s, Size: %d"
                        % (track_id, file_key, file_name, file_size)
                    )
                else:
                    logger.warning(
                        "[Feishu WS] [%s] File message but no file_key found: %s"
                        % (track_id, content_json)
                    )
                    text_content = "[文件] 无法获取文件标识"
            except Exception as e:
                text_content = "[文件] 解析失败"
                logger.error(
                    "[Feishu WS] [%s] Failed to parse file content: %s"
                    % (track_id, str(e))
                )
        else:
            # 其他类型（如 image, audio 等），暂不处理
            logger.info(
                "[Feishu WS] [%s] Unhandled msg_type: %s" % (track_id, msg_type)
            )
            return  # 直接返回，不放入队列

        parse_time = time.time() - start_time
        logger.info(
            "[Feishu WS] [%s] Received - Type: %s, SenderID: %s, MessageID: %s, Content: %s"
            % (
                track_id,
                msg_type,
                sender_id,
                message_id,
                text_content[:100] + "..." if len(text_content) > 100 else text_content,
            )
        )
        logger.info("[Feishu WS] [%s] Parsed in %.2fms" % (track_id, parse_time * 1000))

        message_queue.put(
            {
                "track_id": track_id,
                "message_id": message_id,
                "chat_id": chat_id,
                "content": text_content,
                "sender_id": sender_id,
                "receive_time": start_time,
                "msg_type": msg_type,
                "file_info": file_info,
            }
        )
        logger.info(
            "[Feishu WS] [%s] Queued with file_info=%s"
            % (track_id, file_info is not None)
        )
    except Exception as e:
        logger.error(
            "[Feishu WS] [%s] Failed to process message: %s" % (track_id, str(e)),
            exc_info=True,
        )


def process_messages():
    try:
        from app.tools.feishu_tool import feishu_tool
        from app.monitoring import monitoring_stats

        logger.info("[Feishu WS] Processor started")
    except Exception as e:
        logger.error("[Feishu WS] Failed to init feishu_tool: %s" % str(e))
        return
    while True:
        try:
            msg = message_queue.get(timeout=1)
            if msg is None:
                break
            track_id = msg.get("track_id", "unknown")
            queue_wait = time.time() - msg.get("receive_time", time.time())
            logger.info(
                "[Feishu WS] [%s] Dequeued after %.2fms" % (track_id, queue_wait * 1000)
            )

            sender_id = msg.get("sender_id", "")
            user_name = "Unknown"
            if sender_id:
                fs_start = time.time()
                try:
                    user_info = feishu_tool.get_user_info(sender_id)
                    monitoring_stats.record_feishu_api_call(time.time() - fs_start)
                    if user_info.get("code") == 0:
                        user_name = user_info.get("data", {}).get("name", "Unknown")
                        logger.info(
                            "[Feishu WS] [%s] User info retrieved - ID: %s, Name: %s"
                            % (track_id, sender_id, user_name)
                        )
                    else:
                        logger.warning(
                            "[Feishu WS] [%s] Failed to get user info: %s"
                            % (track_id, user_info.get("msg", ""))
                        )
                except Exception as e:
                    monitoring_stats.record_feishu_api_call(
                        time.time() - fs_start, success=False
                    )
                    logger.error(
                        "[Feishu WS] [%s] Error getting user info: %s"
                        % (track_id, str(e))
                    )

            # ============================================================
            # 文件下载逻辑（增加详细日志）
            # ============================================================
            file_path = None
            file_content = None
            file_info = msg.get("file_info")
            logger.info("[Feishu WS] [%s] file_info = %s" % (track_id, file_info))
            if file_info:
                download_start = time.time()
                try:
                    file_key = file_info.get("file_key", "")
                    file_name = file_info.get("file_name", "unknown")
                    save_path = "data/uploads/%s" % file_name
                    logger.info(
                        "[Feishu WS] [%s] Attempting to download file_key=%s to %s"
                        % (track_id, file_key, save_path)
                    )
                    download_result = feishu_tool.download_file(file_key, save_path)
                    monitoring_stats.record_feishu_api_call(
                        time.time() - download_start
                    )
                    if download_result.get("success"):
                        file_path = save_path
                        logger.info(
                            "[Feishu WS] [%s] File downloaded successfully: %s"
                            % (track_id, file_path)
                        )

                        parse_start = time.time()
                        try:
                            from app.tools.file_parser_tool import file_parser_tool

                            parse_result = file_parser_tool.parse_local_file(file_path)
                            if parse_result.get("error"):
                                file_content = (
                                    "File parse failed: " + parse_result["error"]
                                )
                                logger.warning(
                                    "[Feishu WS] [%s] File parsing failed: %s"
                                    % (track_id, parse_result["error"])
                                )
                            else:
                                columns = parse_result.get("columns", [])
                                row_count = parse_result.get("row_count", 0)
                                summary = parse_result.get("summary", {})
                                sample_rows = parse_result.get("sample_rows", [])
                                content_parts = []
                                content_parts.append(
                                    "File: " + os.path.basename(file_path)
                                )
                                content_parts.append("Columns: " + ", ".join(columns))
                                content_parts.append("Rows: " + str(row_count))
                                content_parts.append("")
                                content_parts.append("Summary:")
                                for col, stats in summary.items():
                                    if stats.get("type") == "numeric":
                                        content_parts.append(
                                            "- "
                                            + col
                                            + ": mean="
                                            + str(round(stats["mean"], 2))
                                            + ", max="
                                            + str(stats["max"])
                                            + ", min="
                                            + str(stats["min"])
                                        )
                                    else:
                                        content_parts.append(
                                            "- "
                                            + col
                                            + ": unique="
                                            + str(stats["unique_count"])
                                            + ", sample="
                                            + str(stats["sample_values"])
                                        )
                                if sample_rows:
                                    content_parts.append("")
                                    content_parts.append("First 3 rows:")
                                    for i, row in enumerate(sample_rows):
                                        content_parts.append(
                                            str(i + 1)
                                            + ". "
                                            + json.dumps(row, ensure_ascii=False)
                                        )
                                file_content = "\n".join(content_parts)
                                logger.info(
                                    "[Feishu WS] [%s] File parsed, content length: %d"
                                    % (track_id, len(file_content))
                                )
                        except Exception as e:
                            file_content = "File parse error: " + str(e)
                            logger.error(
                                "[Feishu WS] [%s] Error parsing file: %s"
                                % (track_id, str(e))
                            )
                        monitoring_stats.record_feishu_api_call(
                            time.time() - parse_start
                        )
                    else:
                        logger.warning(
                            "[Feishu WS] [%s] Failed to download file: %s"
                            % (track_id, download_result.get("error", "Unknown error"))
                        )
                except Exception as e:
                    monitoring_stats.record_feishu_api_call(
                        time.time() - download_start, success=False
                    )
                    logger.error(
                        "[Feishu WS] [%s] Error downloading file: %s"
                        % (track_id, str(e))
                    )
            else:
                logger.info("[Feishu WS] [%s] No file_info in message" % track_id)

            agent_start = time.time()
            answer = "Sorry, something went wrong"
            intent = "unknown"
            token_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
            try:
                from app.agent.workflow import agent

                agent_input = {
                    "user_input": msg["content"],
                    "conversation_id": msg["chat_id"],
                }
                if file_path:
                    agent_input["file_path"] = file_path
                    logger.info(
                        "[Feishu WS] [%s] File path added to agent input: %s"
                        % (track_id, file_path)
                    )
                else:
                    logger.info("[Feishu WS] [%s] No file path to add" % track_id)
                if file_content:
                    agent_input["file_content"] = file_content
                    logger.info(
                        "[Feishu WS] [%s] File content added to agent input, length: %d"
                        % (track_id, len(file_content))
                    )
                else:
                    logger.info("[Feishu WS] [%s] No file content to add" % track_id)

                result = agent.invoke(agent_input)
                answer = result.get("answer", "Sorry")
                intent = result.get("intent", "unknown")
                token_usage = result.get(
                    "token_usage",
                    {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                )
                agent_time = time.time() - agent_start
                monitoring_stats.record_skill_call("feishu_workflow", agent_time)
                monitoring_stats.record_intent(intent)
                if token_usage.get("total_tokens", 0) > 0:
                    monitoring_stats.record_llm_call(
                        agent_time, token_usage=token_usage
                    )
                logger.info(
                    "[Feishu WS] [%s] Agent completed - Intent: %s, Answer: %s"
                    % (
                        track_id,
                        intent,
                        answer[:100] + "..." if len(answer) > 100 else answer,
                    )
                )
                logger.info(
                    "[Feishu WS] [%s] Agent processing time: %.2fms"
                    % (track_id, agent_time * 1000)
                )
                logger.info(
                    "[Feishu WS] [%s] Token Usage - Prompt: %d, Completion: %d, Total: %d"
                    % (
                        track_id,
                        token_usage.get("prompt_tokens", 0),
                        token_usage.get("completion_tokens", 0),
                        token_usage.get("total_tokens", 0),
                    )
                )
            except Exception as e:
                answer = "Error: %s" % str(e)
                agent_time = time.time() - agent_start
                monitoring_stats.record_skill_call(
                    "feishu_workflow", agent_time, success=False
                )
                logger.error("[Feishu WS] [%s] Agent error: %s" % (track_id, str(e)))

            reply_start = time.time()
            try:
                feishu_tool.reply_message(msg["message_id"], answer)
                reply_time = time.time() - reply_start
                monitoring_stats.record_feishu_api_call(reply_time)
                logger.info(
                    "[Feishu WS] [%s] Reply sent in %.2fms"
                    % (track_id, reply_time * 1000)
                )
            except Exception as e:
                reply_time = time.time() - reply_start
                monitoring_stats.record_feishu_api_call(reply_time, success=False)
                logger.error("[Feishu WS] [%s] Reply failed: %s" % (track_id, str(e)))

            total_time = time.time() - msg.get("receive_time", time.time())
            logger.info("[Feishu WS] [%s] === TIMING SUMMARY ===" % track_id)
            logger.info(
                "[Feishu WS] [%s] User: %s (%s)" % (track_id, user_name, sender_id)
            )
            logger.info("[Feishu WS] [%s] Intent: %s" % (track_id, intent))
            logger.info(
                "[Feishu WS] [%s] Tokens: Prompt=%d, Completion=%d, Total=%d"
                % (
                    track_id,
                    token_usage.get("prompt_tokens", 0),
                    token_usage.get("completion_tokens", 0),
                    token_usage.get("total_tokens", 0),
                )
            )
            logger.info(
                "[Feishu WS] [%s] Times: Queue=%.2fms, Agent=%.2fms, Reply=%.2fms, Total=%.2fms"
                % (
                    track_id,
                    queue_wait * 1000,
                    agent_time * 1000,
                    reply_time * 1000,
                    total_time * 1000,
                )
            )
            logger.info("[Feishu WS] [%s] =======================" % track_id)

            message_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error("[Feishu WS] Processor error: %s" % str(e))


def start_feishu_ws(app_id, app_secret):
    if not app_id or not app_secret:
        logger.error("[Feishu WS] No credentials provided")
        return
    try:
        threading.Thread(target=process_messages, daemon=True).start()
        logger.info("[Feishu WS] Processor thread started")
        h = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
            .build()
        )
        cli = lark.ws.Client(
            app_id, app_secret, event_handler=h, log_level=lark.LogLevel.INFO
        )
        logger.info("[Feishu WS] Starting WebSocket client...")
        cli.start()
    except Exception as e:
        logger.error("[Feishu WS] Failed to start: %s" % str(e), exc_info=True)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        start_feishu_ws(sys.argv[1], sys.argv[2])
    else:
        logger.error("[Feishu WS] Missing app_id or app_secret arguments")
        sys.exit(1)
