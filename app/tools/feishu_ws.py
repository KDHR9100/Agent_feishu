import lark_oapi as lark
import logging
import time
import sys
import json
import threading
import queue
from typing import Optional
from typing import Optional
import typing
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("app.log", encoding="utf-8")]
)
logger = logging.getLogger("feishu_ws")
message_queue: queue.Queue = queue.Queue()


def do_p2_im_message_receive_v1(data):
    start_time = time.time()
    track_id = str(uuid.uuid4())[:8]
    try:
        try:
            event_data = lark.JSON.marshal(data, indent=4)
            event_dict = json.loads(event_data)
        except:
            event_dict = data
        message = event_dict.get("event", {}).get("message", {})
        sender = event_dict.get("event", {}).get("sender", {})
        message_id = message.get("message_id", "")
        chat_id = message.get("chat_id", "")
        content_raw = message.get("content", "{}")
        mentions = message.get("mentions", [])
        sender_id = sender.get("sender_id", {}).get("open_id", "")
        try:
            text_content = json.loads(content_raw).get("text", "")
        except:
            text_content = ""
        if mentions:
            for mention in mentions:
                key = mention.get("key", "")
                if key:
                    text_content = text_content.replace(key, "").strip()
        parse_time = time.time() - start_time
        logger.info("[Feishu WS] [%s] Received - SenderID: %s, MessageID: %s, Content: %s" % (
            track_id, sender_id, message_id, text_content[:100] + "..." if len(text_content) > 100 else text_content))
        logger.info("[Feishu WS] [%s] Parsed in %.2fms" % (track_id, parse_time*1000))
        message_queue.put({
            "track_id": track_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "content": text_content,
            "sender_id": sender_id,
            "receive_time": start_time
        })
        logger.info("[Feishu WS] [%s] Queued" % track_id)
    except Exception as e:
        logger.error("[Feishu WS] [%s] Failed to process message: %s" % (track_id, str(e)), exc_info=True)


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
            logger.info("[Feishu WS] [%s] Dequeued after %.2fms" % (track_id, queue_wait*1000))

            sender_id = msg.get("sender_id", "")
            user_name = "Unknown"
            if sender_id:
                fs_start = time.time()
                try:
                    user_info = feishu_tool.get_user_info(sender_id)
                    monitoring_stats.record_feishu_api_call(time.time() - fs_start)
                    if user_info.get("code") == 0:
                        user_name = user_info.get("data", {}).get("name", "Unknown")
                        logger.info("[Feishu WS] [%s] User info retrieved - ID: %s, Name: %s" % (track_id, sender_id, user_name))
                    else:
                        logger.warning("[Feishu WS] [%s] Failed to get user info: %s" % (track_id, user_info.get("msg", "")))
                except Exception as e:
                    monitoring_stats.record_feishu_api_call(time.time() - fs_start, success=False)
                    logger.error("[Feishu WS] [%s] Error getting user info: %s" % (track_id, str(e)))

            agent_start = time.time()
            answer = "Sorry, something went wrong"
            intent = "unknown"
            token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            try:
                from app.agent.workflow import agent
                result = agent.invoke({
                    "user_input": msg["content"],
                    "conversation_id": msg["chat_id"]
                })
                answer = result.get("answer", "Sorry")
                intent = result.get("intent", "unknown")
                token_usage = result.get("token_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
                agent_time = time.time() - agent_start
                monitoring_stats.record_skill_call("feishu_workflow", agent_time)
                monitoring_stats.record_intent(intent)
                if token_usage.get("total_tokens", 0) > 0:
                    monitoring_stats.record_llm_call(agent_time, token_usage=token_usage)
                logger.info("[Feishu WS] [%s] Agent completed - Intent: %s, Answer: %s" % (
                    track_id, intent, answer[:100] + "..." if len(answer) > 100 else answer))
                logger.info("[Feishu WS] [%s] Agent processing time: %.2fms" % (track_id, agent_time*1000))
                logger.info("[Feishu WS] [%s] Token Usage - Prompt: %d, Completion: %d, Total: %d" % (
                    track_id,
                    token_usage.get("prompt_tokens", 0),
                    token_usage.get("completion_tokens", 0),
                    token_usage.get("total_tokens", 0)
                ))
            except Exception as e:
                answer = "Error: %s" % str(e)
                agent_time = time.time() - agent_start
                monitoring_stats.record_skill_call("feishu_workflow", agent_time, success=False)
                logger.error("[Feishu WS] [%s] Agent error: %s" % (track_id, str(e)))

            reply_start = time.time()
            try:
                feishu_tool.reply_message(msg["message_id"], answer)
                reply_time = time.time() - reply_start
                monitoring_stats.record_feishu_api_call(reply_time)
                logger.info("[Feishu WS] [%s] Reply sent in %.2fms" % (track_id, reply_time*1000))
            except Exception as e:
                reply_time = time.time() - reply_start
                monitoring_stats.record_feishu_api_call(reply_time, success=False)
                logger.error("[Feishu WS] [%s] Reply failed: %s" % (track_id, str(e)))

            total_time = time.time() - msg.get("receive_time", time.time())
            logger.info("[Feishu WS] [%s] === TIMING SUMMARY ===" % track_id)
            logger.info("[Feishu WS] [%s] User: %s (%s)" % (track_id, user_name, sender_id))
            logger.info("[Feishu WS] [%s] Intent: %s" % (track_id, intent))
            logger.info("[Feishu WS] [%s] Tokens: Prompt=%d, Completion=%d, Total=%d" % (
                track_id,
                token_usage.get("prompt_tokens", 0),
                token_usage.get("completion_tokens", 0),
                token_usage.get("total_tokens", 0)
            ))
            logger.info("[Feishu WS] [%s] Times: Queue=%.2fms, Agent=%.2fms, Reply=%.2fms, Total=%.2fms" % (
                track_id, queue_wait*1000, agent_time*1000, reply_time*1000, total_time*1000))
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
        h = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(do_p2_im_message_receive_v1).build()
        cli = lark.ws.Client(app_id, app_secret, event_handler=h, log_level=lark.LogLevel.INFO)
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