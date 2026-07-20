import lark_oapi as lark
import logging
import time
import sys
import json
import threading
import queue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("feishu_ws")

# Global message queue for communication with FastAPI
message_queue = queue.Queue()


def do_p2_im_message_receive_v1(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    """Handle received message events from Feishu"""
    try:
        event_data = lark.JSON.marshal(data, indent=4)
        logger.info("[Feishu WS] Received message event: im.message.receive_v1")

        # Parse message data
        event_dict = json.loads(event_data)
        header = event_dict.get("header", {})
        event = event_dict.get("event", {})

        message = event.get("message", {})
        sender = event.get("sender", {})

        message_id = message.get("message_id", "")
        chat_id = message.get("chat_id", "")
        chat_type = message.get("chat_type", "")
        message_type = message.get("message_type", "")
        content_raw = message.get("content", "{}")
        mentions = message.get("mentions", [])

        sender_id = sender.get("sender_id", {}).get("open_id", "")
        sender_type = sender.get("sender_type", "")

        # Extract text content
        try:
            content_json = json.loads(content_raw)
            text_content = content_json.get("text", "")
        except Exception:
            text_content = ""

        # Remove @bot mention from text
        if mentions:
            for mention in mentions:
                key = mention.get("key", "")
                if key:
                    text_content = text_content.replace(key, "").strip()

        logger.info("[Feishu WS] Message from %s in chat %s: %s" % (sender_id, chat_id, text_content))

        # Put message in queue for processing
        message_queue.put({
            "message_id": message_id,
            "chat_id": chat_id,
            "chat_type": chat_type,
            "message_type": message_type,
            "content": text_content,
            "sender_id": sender_id,
            "sender_type": sender_type,
            "event_id": header.get("event_id", ""),
            "app_id": header.get("app_id", "")
        })

    except Exception as e:
        logger.error("[Feishu WS] Failed to process message: %s" % str(e), exc_info=True)


def process_messages():
    """Background thread to process messages and call Agent"""
    # Import here to avoid circular imports and loading issues
    try:
        from app.tools.feishu_tool import feishu_tool
        logger.info("[Feishu WS] Message processor started")
    except Exception as e:
        logger.error("[Feishu WS] Failed to initialize feishu_tool: %s" % str(e))
        return

    while True:
        try:
            msg = message_queue.get(timeout=1)
            if msg is None:
                break

            logger.info("[Feishu WS] Processing message: %s" % msg["content"][:100])

            # Call Agent to process the message
            try:
                from app.agent.workflow import agent
                result = agent.invoke({
                    "user_input": msg["content"],
                    "conversation_id": msg["chat_id"]
                })
                answer = result.get("answer", "Sorry, I could not process your request.")
                logger.info("[Feishu WS] Agent response: %s" % answer[:100])
            except Exception as e:
                logger.error("[Feishu WS] Agent error: %s" % str(e), exc_info=True)
                answer = "Sorry, an error occurred while processing your request: %s" % str(e)

            # Reply to the message
            try:
                reply_result = feishu_tool.reply_message(msg["message_id"], answer)
                logger.info("[Feishu WS] Reply result: %s" % json.dumps(reply_result, ensure_ascii=False)[:200])
            except Exception as e:
                logger.error("[Feishu WS] Failed to reply message: %s" % str(e), exc_info=True)

            message_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            logger.error("[Feishu WS] Message processor error: %s" % str(e), exc_info=True)


def start_feishu_ws(app_id, app_secret):
    """Start Feishu WebSocket client"""
    if not app_id or not app_secret:
        logger.error("[Feishu WS] Feishu credentials not configured")
        return

    try:
        # Start message processor thread
        processor_thread = threading.Thread(target=process_messages, daemon=True)
        processor_thread.start()
        logger.info("[Feishu WS] Message processor thread started")

        # Create event handler
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
            .build()

        logger.info("[Feishu WS] Initializing Feishu WS client with App ID: %s" % app_id)

        # Create and start client
        cli = lark.ws.Client(
            app_id,
            app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO
        )

        logger.info("[Feishu WS] Starting Feishu WS client...")
        logger.info("[Feishu WS] Waiting for connection...")
        cli.start()

    except Exception as e:
        logger.error("[Feishu WS] Failed to start Feishu WS client: %s" % str(e), exc_info=True)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        app_id = sys.argv[1]
        app_secret = sys.argv[2]
        start_feishu_ws(app_id, app_secret)
    else:
        logger.error("[Feishu WS] Missing app_id or app_secret arguments")
        logger.error("[Feishu WS] Usage: python3 -m app.tools.feishu_ws <app_id> <app_secret>")
        sys.exit(1)
