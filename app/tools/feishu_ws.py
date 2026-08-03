import logging
import json
import time
import uuid
import queue
import threading
import os
import sys
from concurrent.futures import ThreadPoolExecutor

# 日志配置（必须在导入项目模块之前）
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("app.log", encoding="utf-8")],
)
logger = logging.getLogger("feishu_ws_official")

# ============================================================
# 问候语检测 + 飞书卡片
# ============================================================
GREETING_KEYWORDS = [
    "你好", "您好", "hello", "hi", "hey", "嗨", "哈喽",
    "早上好", "下午好", "晚上好", "在吗",
    "你是谁", "介绍一下", "帮助", "你能做什么",
    "你会什么", "功能", "你好呀", "在不在",
]


def _is_greeting(text: str) -> bool:
    """检测是否为问候/自我介绍请求"""
    text_lower = text.strip().lower()
    # 短文本 + 关键词命中
    if len(text_lower) <= 20:
        for kw in GREETING_KEYWORDS:
            if kw in text_lower:
                return True
    return False


def _build_greeting_card() -> str:
    """构建自我介绍飞书卡片"""
    import json
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "\U0001f44b 你好，我是电商运营 Agent"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "我是你的 **AI 电商运营助手**，基于 LangGraph + DeepSeek 构建。"
                        "我可以帮你处理以下工作："
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "\U0001f4ca **数据分析类**\n"
                        "\u2022 商品销售分析 \u2014 \u201c分析商品销量\u201d\n"
                        "\u2022 广告效果分析 \u2014 \u201c广告ROI是多少\u201d\n"
                        "\u2022 库存预警查询 \u2014 \u201c库存预警\u201d\n"
                        "\u2022 数据趋势/异常 \u2014 \u201c转化率趋势\u201d"
                    ),
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "\u270d\ufe0f **内容生成类**\n"
                        "\u2022 营销文案撰写 \u2014 \u201c写一段小红书文案\u201d\n"
                        "\u2022 SEO 标题优化 \u2014 \u201c优化商品标题SEO\u201d\n"
                        "\u2022 竞品情报分析 \u2014 \u201c分析竞品动态\u201d"
                    ),
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "\U0001f4c1 **文件与报告类**\n"
                        "\u2022 上传文件解析 \u2014 直接发 xlsx/csv/pdf/图片\n"
                        "\u2022 运营报告生成 \u2014 \u201c生成本周运营报告\u201d\n"
                        "\u2022 客服/售后处理 \u2014 \u201c查询订单状态\u201d"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "\U0001f4a1 **快速开始**：直接发送你的问题，或上传文件让我分析。\n"
                        "复杂任务也可以一句话搞定，例如：\n"
                        "\u201c查库存，低于100件就生成补货报告，再看看广告费要不要追加\u201d"
                    ),
                },
            },
        ],
    }
    return json.dumps(card, ensure_ascii=False)

# 确保 Lark SDK 日志也输出到 app.log
_lark_logger = logging.getLogger("Lark")
_lark_logger.setLevel(logging.INFO)
_lark_logger.propagate = True

import lark_oapi as lark

# 导入项目内部模块
from app.tools.feishu_tool import feishu_tool
from app.tools.file_parser_tool import file_parser_tool
from app.tools.guardrails import check_input
from app.agent.workflow import agent

# 消息队列
message_queue = queue.Queue()

# 消息处理线程池（并发消费队列）
MAX_WORKERS = int(os.getenv("WS_MAX_WORKERS", "3"))


def do_p2_im_message_receive_v1(data):
    """处理接收到的消息事件 - 使用官方SDK对象"""
    start_time = time.time()
    track_id = str(uuid.uuid4())[:8]

    try:
        # 提取事件信息
        event = data.event
        message = event.message
        sender = event.sender

        # ---- 兼容多种属性名 ----
        message_id = getattr(message, "message_id", None) or getattr(message, "id", "")
        chat_id = getattr(message, "chat_id", None) or getattr(message, "group_id", "")
        msg_type = (
            getattr(message, "msg_type", None)
            or getattr(message, "message_type", None)
            or getattr(message, "type", "")
        )
        content_raw = getattr(message, "content", "") or getattr(message, "raw_content", "")
        mentions = getattr(message, "mentions", []) or getattr(event, "mentions", [])

        # 打印消息ID用于调试
        logger.info("[Feishu WS] [%s] message_id=%s", track_id, message_id)

        # 打印 mentions 详细信息用于调试
        logger.info("[Feishu WS] [%s] mentions count: %d", track_id, len(mentions))
        for idx, m in enumerate(mentions):
            logger.info("[Feishu WS] [%s] mention[%d] vars: %s", track_id, idx, vars(m))

        sender_id = getattr(sender, "sender_id", None)
        if sender_id:
            sender_id = getattr(sender_id, "open_id", "") or getattr(sender_id, "user_id", "")
        else:
            sender_id = ""

        # ---------- 判断群聊/私聊 ----------
        chat_type = getattr(message, "chat_type", None)
        if not chat_type:
            chat_obj = getattr(event, "chat", None)
            if chat_obj:
                chat_type = getattr(chat_obj, "type", None)
        if not chat_type:
            chat_type = "group" if chat_id.startswith("oc_") else "p2p"

        logger.info("[Feishu WS] [%s] msg_type=%s, chat_id=%s, chat_type=%s", track_id, msg_type, chat_id, chat_type)

        # ---------- @ 过滤 ----------
        bot_name = os.getenv("FEISHU_BOT_NAME", "Feishu Agent")
        is_group_chat = (chat_type == "group")
        is_private_chat = (chat_type == "p2p")

        if is_group_chat:
            bot_mentioned = False
            bot_name_lower = bot_name.lower()
            for m in mentions:
                m_name = getattr(m, "name", "")
                m_key = getattr(m, "key", "")
                # m_open_id = getattr(m, "open_id", "")
                # m_tenant_key = getattr(m, "tenant_key", "")
                if (m_name and (m_name.lower() == bot_name_lower or bot_name_lower in m_name.lower())) or \
                   (m_key and (m_key == bot_name or bot_name in m_key)):
                    bot_mentioned = True
                    break
                if hasattr(m, "mention_name"):
                    if getattr(m, "mention_name", "").lower() == bot_name_lower:
                        bot_mentioned = True
                        break
            if not bot_mentioned:
                logger.info("[Feishu WS] [%s] Group chat without mention, ignoring", track_id)
                return
        elif is_private_chat:
            logger.info("[Feishu WS] [%s] Private chat, proceeding", track_id)
        else:
            if chat_id.startswith("oc_") and not mentions:
                logger.info("[Feishu WS] [%s] Unknown chat type, treating as group without mention, ignoring", track_id)
                return
            logger.info("[Feishu WS] [%s] Unknown chat type, proceeding anyway", track_id)

        text_content = ""
        file_info = None

        # ---------- 解析消息内容 ----------
        if msg_type == "text":
            try:
                if isinstance(content_raw, str):
                    content_json = json.loads(content_raw)
                else:
                    content_json = content_raw
                text_content = content_json.get("text", "")
            except Exception:
                text_content = ""
            for mention in mentions:
                key = getattr(mention, "key", "")
                if key:
                    text_content = text_content.replace(key, "").strip()

        elif msg_type in ["file", "media", "image"]:
            try:
                if isinstance(content_raw, str):
                    content_json = json.loads(content_raw)
                else:
                    content_json = content_raw
                file_key = (
                    content_json.get("file_key")
                    or content_json.get("image_key")
                    or content_json.get("file_token")
                    or content_json.get("media_id")
                    or ""
                )
                file_name = content_json.get("file_name", "")
                if not file_name and msg_type == "image":
                    file_name = "image.jpg"
                file_size = content_json.get("file_size", 0)
                if file_key:
                    file_info = {"file_key": file_key, "file_name": file_name, "file_size": file_size, "msg_type": msg_type}
                    text_content = f"[文件] {file_name}"
                    logger.info("[Feishu WS] [%s] File detected - key=%s, name=%s", track_id, file_key, file_name)
                else:
                    logger.warning("[Feishu WS] [%s] File message but no key found: %s", track_id, content_json)
                    text_content = "[文件] 无法获取文件标识"
            except Exception as e:
                text_content = "[文件] 解析失败"
                logger.error("[Feishu WS] [%s] Failed to parse file: %s", track_id, str(e))
        elif msg_type == "post":
            # 富文本消息: 提取所有文本段落
            try:
                if isinstance(content_raw, str):
                    post_data = json.loads(content_raw)
                else:
                    post_data = content_raw
                # 飞书 post 格式: {"zh_cn": {"title": "", "content": [[{"tag":"text","text":"..."}]]}}
                texts = []
                for lang_key in ["zh_cn", "en_us", "ja_jp"]:
                    if lang_key in post_data:
                        paragraphs = post_data[lang_key].get("content", [])
                        for para in paragraphs:
                            for elem in para:
                                if elem.get("tag") == "text":
                                    texts.append(elem.get("text", ""))
                        break
                text_content = "".join(texts) if texts else "[富文本消息]"
                logger.info("[Feishu WS] [%s] post parsed, len=%d", track_id, len(text_content))
            except Exception as e:
                text_content = "[富文本消息]"
                logger.warning("[Feishu WS] [%s] post parse failed: %s", track_id, str(e))
        else:
            logger.info("[Feishu WS] [%s] Unhandled msg_type: %s", track_id, msg_type)
            return

        logger.info("[Feishu WS] [%s] Content: %s", track_id, text_content[:100])

        # ---------- 放入队列 ----------
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


def _handle_single_message(msg):
    """处理单条消息（在工作线程中执行）"""
    track_id = msg.get("track_id", "unknown")
    try:
        logger.info("[Feishu WS] [%s] Processing message (thread=%s)", track_id, threading.current_thread().name)

        # ---------- 文件下载与解析 ----------
        file_path = None
        file_content = None
        file_info = msg.get("file_info")

        if file_info:
            try:
                file_key = file_info.get("file_key", "")
                raw_file_name = file_info.get("file_name", "unknown")
                file_name = os.path.basename(raw_file_name)
                allowed_extensions = {".xlsx", ".xls", ".csv", ".pdf", ".docx", ".jpg", ".jpeg", ".png", ".webp"}
                _, file_ext = os.path.splitext(file_name)
                if file_ext.lower() not in allowed_extensions:
                    logger.warning("[Feishu WS] [%s] Rejected file type: %s", track_id, file_ext)
                    feishu_tool.reply_message(msg["message_id"], f"不支持的文件类型：{file_ext}，请上传 Excel/CSV/PDF/Word 文件。")
                    return
                # uuid 前缀避免同名文件相互覆盖
                save_path = f"data/uploads/{uuid.uuid4().hex[:8]}_{file_name}"

                try:
                    feishu_tool.reply_message(msg["message_id"], "\U0001f504 正在解析文件，请稍候...")
                except Exception:
                    pass

                logger.info("[Feishu WS] [%s] Downloading file: %s", track_id, file_key)
                # 图片用 type=image, 文件用 type=file
                _res_type = "image" if file_info.get("msg_type") == "image" else "file"
                download_result = feishu_tool.download_file(
                    file_key, save_path, message_id=msg["message_id"],
                    resource_type=_res_type,
                )

                if download_result.get("success"):
                    file_path = save_path
                    logger.info("[Feishu WS] [%s] File downloaded: %s", track_id, file_path)
                    parse_result = file_parser_tool.parse_local_file(file_path)
                    if parse_result.get("error"):
                        logger.error("[Feishu WS] [%s] Parse error: %s", track_id, parse_result.get("error"))
                        # 图片解析失败时直接告知用户，不走 Agent
                        if file_info.get("msg_type") == "image":
                            _err = parse_result.get("error", "")
                            if "403" in _err or "quota" in _err.lower() or "Free" in _err:
                                _tip = "❌ 图片解析失败：VLM 视觉模型免费额度已用尽。请到 DashScope 控制台充值或关闭“仅使用免费额度”开关。"
                            else:
                                _tip = f"❌ 图片解析失败：{_err[:100]}。请尝试重新上传或换用 .xlsx/.csv 格式。"
                            feishu_tool.reply_message(msg["message_id"], _tip)
                            return
                    else:
                        file_content = file_parser_tool.format_file_summary(parse_result, file_name)
                        logger.info(
                            "[Feishu WS] [%s] File parsed: %d rows",
                            track_id, parse_result.get("row_count", 0))
                else:
                    logger.warning("[Feishu WS] [%s] Download failed: %s", track_id, download_result.get("error"))
            except Exception as e:
                logger.error("[Feishu WS] [%s] File error: %s", track_id, str(e))

        # ---------- 调用 Agent ----------
        # Guardrails: input safety check
        guardrails_result = check_input(msg["content"])
        if guardrails_result["action"] in ("block", "redirect"):
            answer = guardrails_result["message"]
            logger.info("[Feishu WS] [%s] Guardrails: %s", track_id, guardrails_result["action"])
        else:
            # 问候语拦截: 直接返回飞书卡片, 不走 Agent
            if _is_greeting(msg["content"]):
                logger.info("[Feishu WS] [%s] greeting detected, sending card", track_id)
                card_json = _build_greeting_card()
                feishu_tool.reply_message(msg["message_id"], card_json, msg_type="interactive")
                return

            try:
                agent_input = {
                    "user_input": msg["content"],
                    "conversation_id": msg["chat_id"]
                    }
                if file_path:
                    agent_input["file_path"] = file_path
                if file_content:
                    agent_input["file_content"] = file_content

                # 流式执行: 分阶段推送进度消息
                # 技能名中文映射（运营人员可读）
                _SKILL_CN = {
                    "inventory_skill": "库存管理",
                    "ads_skill": "广告分析",
                    "product_skill": "商品管理",
                    "content_skill": "内容创作",
                    "seo_skill": "SEO优化",
                    "competitor_skill": "竞品分析",
                    "trend_skill": "趋势分析",
                    "report_skill": "报告生成",
                    "support_skill": "客服助手",
                    "file_analysis_skill": "文件解析",
                    "help_skill": "帮助中心",
                    "order_skill": "订单管理",
                }
                progress_sent = set()
                _cached_skills = []
                result = None
                try:
                    for chunk in agent.stream(agent_input):
                        for node_name, node_state in chunk.items():
                            # 进入 router 时推送思考状态
                            if node_name == "router" and "router" not in progress_sent:
                                try:
                                    feishu_tool.reply_message(msg["message_id"], "🤔 正在分析意图...")
                                except Exception:
                                    pass
                                _cached_skills = node_state.get("skills_to_execute", [])
                                progress_sent.add("router")
                            # 进入 skill_executor 时推送技能调用状态
                            elif node_name == "skill_executor" and "skill" not in progress_sent:
                                skills = node_state.get("skills_to_execute") or _cached_skills
                                _raw = skills[0] if skills else ""
                                skill_label = _SKILL_CN.get(_raw, _raw) if _raw else "处理"
                                try:
                                    feishu_tool.reply_message(msg["message_id"], f"📊 正在调用 [{skill_label}]...")
                                except Exception:
                                    pass
                                progress_sent.add("skill")
                            result = node_state
                except Exception as stream_err:
                    logger.warning("[Feishu WS] [%s] stream failed, fallback to invoke: %s", track_id, stream_err)
                    result = agent.invoke(agent_input)

                if result:
                    answer = result.get("answer", "抱歉，我无法处理您的请求。")
                else:
                    answer = "抱歉，我无法处理您的请求。"
                logger.info("[Feishu WS] [%s] Agent done, answer length=%d", track_id, len(answer))

            except Exception as e:
                logger.error("[Feishu WS] [%s] Agent error: %s", track_id, str(e))
                answer = "处理您的问题时出现内部错误，请稍后重试。"

        # ---------- 回复消息 ----------
        try:
            feishu_tool.reply_message(msg["message_id"], answer)
            logger.info("[Feishu WS] [%s] Reply sent", track_id)
        except Exception as e:
            logger.error("[Feishu WS] [%s] Reply failed: %s", track_id, str(e))

    except Exception as e:
        logger.error("[Feishu WS] [%s] Worker error: %s", track_id, str(e), exc_info=True)


def process_messages():
    """消息分发线程：从队列取消息，提交到线程池并发处理"""
    logger.info("[Feishu WS] Processor started (workers=%d)", MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="msg-worker") as pool:
        while True:
            try:
                msg = message_queue.get(timeout=1)
                if msg is None:
                    logger.info("[Feishu WS] Received shutdown signal, waiting for workers to finish...")
                    pool.shutdown(wait=True)
                    break
                # 提交到线程池并发处理
                pool.submit(_handle_single_message, msg)
                logger.debug("[Feishu WS] Submitted message %s to pool (queue_size=%d)",
                             msg.get("track_id", "?"), message_queue.qsize())
            except queue.Empty:
                continue
            except Exception as e:
                logger.error("[Feishu WS] Dispatcher error: %s", str(e))


def start_feishu_ws(app_id: str, app_secret: str):
    """启动飞书 WebSocket 客户端（官方SDK版本）"""
    if not app_id or not app_secret:
        logger.error("[Feishu WS] No credentials provided")
        return

    # 启动消息处理线程（分发器）
    threading.Thread(target=process_messages, daemon=True).start()
    logger.info("[Feishu WS] Processor thread started (pool workers=%d)", MAX_WORKERS)

    # Read encrypt key and verification token from env
    encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", "")
    verification_token = os.getenv("FEISHU_WEBHOOK_SECRET", "")
    logger.info("[Feishu WS] encrypt_key set: %s, verification_token set: %s", bool(encrypt_key), bool(verification_token))

    # Create event handler with encrypt key and verification token
    event_handler = lark.EventDispatcherHandler.builder(encrypt_key, verification_token) \
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(lambda x: None) \
        .register_p2_im_message_message_read_v1(lambda x: None) \
        .build()

    # 创建 WebSocket 客户端
    client = lark.ws.Client(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO
    )

    logger.info("[Feishu WS] Starting official WebSocket client...")
    try:
        client.start()
    except KeyboardInterrupt:
        logger.info("[Feishu WS] Stopped by user")
    except Exception as e:
        logger.error("[Feishu WS] Failed to start: %s", str(e), exc_info=True)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        app_id = sys.argv[1]
        app_secret = sys.argv[2]
        start_feishu_ws(app_id, app_secret)
    else:
        logger.error("[Feishu WS] Missing app_id or app_secret arguments")
        sys.exit(1)
