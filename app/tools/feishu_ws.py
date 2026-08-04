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


def _safe_reply(message_id, text, msg_type="text"):
    """安全回复: 发送失败不影响主流程"""
    try:
        feishu_tool.reply_message(message_id, text, msg_type=msg_type)
    except Exception as e:
        logger.warning("[Feishu WS] reply failed: %s", e)


def _build_approval_card(info: dict) -> str:
    """构建人工审批交互卡片 (1.0 JSON; 按钮 value 携带 approval_id 供回调)"""
    approval_id = info.get("approval_id", "")
    skill = info.get("skill", "")
    desc = info.get("description", "")
    card = {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "\u26a0\ufe0f 高危操作审批请求"},
            "template": "red",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "**操作内容**：%s" % (desc or skill)},
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**关联技能**：%s\n**审批单号**：%s" % (skill, approval_id),
                },
            },
            {"tag": "note", "elements": [{"tag": "plain_text", "content": "点击按钮后 Agent 才会执行/放弃该操作"}]},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "\u2705 批准并执行"},
                        "type": "danger",
                        "value": {"approval_id": approval_id, "action": "approve"},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "\u274c 拒绝"},
                        "type": "default",
                        "value": {"approval_id": approval_id, "action": "reject"},
                    },
                ],
            },
        ],
    }
    return json.dumps(card, ensure_ascii=False)


def _build_approval_resolved_card(approval_id, skill, desc, approved):
    """构建审批结果卡片 (回调响应中用于更新原卡片, 1.0 JSON)"""
    status = "\u2705 已批准，操作已执行" if approved else "\u274c 已拒绝，操作未执行"
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "\u26a0\ufe0f 高危操作审批请求"},
            "template": "green" if approved else "grey",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "**操作内容**：%s" % (desc or skill)},
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "**审批结果**：%s\n**审批单号**：%s" % (status, approval_id)},
            },
        ],
    }


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

        # 生产流控: 按用户滑动窗口限流 (限流器自身异常时 fail-open, 不阻断消息)
        try:
            from app.utils.rate_limiter import rate_limiter
            _rl_key = "feishu:%s" % (msg.get("sender_id") or msg.get("chat_id") or "anon")
            if not rate_limiter.allow(_rl_key):
                logger.warning("[Feishu WS] [%s] rate limited, user=%s", track_id, msg.get("sender_id"))
                _safe_reply(msg["message_id"], "您的请求过于频繁，请稍后再试。")
                return
        except Exception as _rl_err:
            logger.warning("[Feishu WS] [%s] rate limiter error (fail-open): %s", track_id, _rl_err)

        # 即时回执: 保证 3 秒内送达首片消息 (流式体验 P2 要求)
        _safe_reply(msg["message_id"], "\U0001f914 已收到，正在思考...")

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
                _cached_skills = []
                result = None
                try:
                    for chunk in agent.stream(agent_input):
                        for node_name, node_state in chunk.items():
                            # router 完成: 推送思考过程 (意图识别结果)
                            if node_name == "router":
                                skills = node_state.get("skills_to_execute", [])
                                _cached_skills = skills
                                _raw = skills[0] if skills else ""
                                skill_label = _SKILL_CN.get(_raw, _raw) if _raw else "处理"
                                _safe_reply(msg["message_id"], "\U0001f4ad 思考：已识别意图，将调用 [%s]" % skill_label)
                            # planner 完成: 多步计划时推送执行计划思考
                            elif node_name == "planner":
                                plan = node_state.get("execution_plan")
                                if plan:
                                    steps = "\n".join(
                                        "%d. %s" % (i, _SKILL_CN.get(s.get("skill", ""), s.get("skill", "")))
                                        for i, s in enumerate(plan, 1)
                                    )
                                    _safe_reply(msg["message_id"], "\U0001f4ad 思考过程（执行计划）：\n" + steps)
                            # skill_executor 完成: 正在组织最终答案
                            elif node_name == "skill_executor":
                                _safe_reply(msg["message_id"], "\U0001f4ca 技能执行完成，正在整理答案...")
                            result = node_state
                except Exception as stream_err:
                    logger.warning("[Feishu WS] [%s] stream failed, fallback to invoke: %s", track_id, stream_err)
                    result = agent.invoke(agent_input)

                if result:
                    answer = result.get("answer", "抱歉，我无法处理您的请求。")
                    # 高危操作审批流: 发送交互审批卡片 (点击按钮后才执行)
                    _tool_res = result.get("tool_result") or {}
                    if _tool_res.get("type") == "approval_required":
                        try:
                            card_json = _build_approval_card(_tool_res.get("data", {}))
                            _safe_reply(msg["message_id"], card_json, msg_type="interactive")
                            logger.info("[Feishu WS] [%s] approval card sent", track_id)
                        except Exception as e:
                            logger.error("[Feishu WS] [%s] approval card failed: %s", track_id, e)
                    # L4 任务12: 多目标冲突仲裁 -> 发送帕累托决策看板卡片 (A/B 点选)
                    elif _tool_res.get("type") == "conflict_decision":
                        try:
                            card_obj = _tool_res.get("data", {}).get("card")
                            _safe_reply(msg["message_id"], json.dumps(card_obj, ensure_ascii=False),
                                        msg_type="interactive")
                            logger.info(
                                "[Feishu WS] [%s] conflict decision card sent, resolver_id=%s",
                                track_id, _tool_res.get("data", {}).get("resolver_id"),
                            )
                        except Exception as e:
                            logger.error("[Feishu WS] [%s] conflict card failed: %s", track_id, e)
                else:
                    answer = "抱歉，我无法处理您的请求。"
                logger.info("[Feishu WS] [%s] Agent done, answer length=%d", track_id, len(answer))

            except Exception as e:
                logger.error("[Feishu WS] [%s] Agent error: %s", track_id, str(e))
                answer = "处理您的问题时出现内部错误，请稍后重试。"

        # ---------- 业务度量: 每次完成的任务记一条使用记录 (商业价值量化) ----------
        try:
            if guardrails_result.get("action") == "allow" and "answer" in locals():
                from app.monitoring.business import business_metrics
                _biz_skills = locals().get("_cached_skills") or []
                business_metrics.record_task(
                    user_id=msg.get("sender_id") or "unknown",
                    skill_name=_biz_skills[0] if _biz_skills else "general",
                    success=isinstance(answer, str) and "内部错误" not in answer,
                    duration_seconds=time.time() - msg.get("receive_time", time.time()),
                    conversation_id=msg.get("chat_id", ""),
                    channel="feishu",
                )
        except Exception as _biz_err:
            logger.warning("[Feishu WS] [%s] business metrics record failed: %s", track_id, _biz_err)

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


def do_p2_card_action_trigger(data):
    """卡片回传交互回调: 审批按钮点击。
    新版回调 card.action.trigger 支持长连接订阅; 必须 3 秒内返回,
    因此耗时的技能执行放到后台线程, 回调只负责决策+响应。"""
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,
    )
    from app.utils.approval import approval_manager
    from app.utils.action_log import log_action

    try:
        event = data.event
        action = event.action
        value = (action.value if action else None) or {}
        approval_id = value.get("approval_id", "")
        act = value.get("action", "")
        operator = event.operator.open_id if (event and event.operator) else ""
        logger.info(
            "[Feishu WS] card action received: approval_id=%s act=%s operator=%s",
            approval_id, act, operator,
        )

        # 审批权限校验: 仅白名单操作者可批准/拒绝/点选决策方案 (未配置时默认拒绝)
        from app.utils.approval import is_authorized_approver

        if not is_authorized_approver(operator):
            logger.warning(
                "[Feishu WS] unauthorized card action blocked: operator=%s act=%s approval_id=%s",
                operator, act, approval_id,
            )
            return P2CardActionTriggerResponse({
                "toast": {"type": "warning", "content": "您没有审批权限"},
            })

        # L4 任务12: 决策看板点选回调 (choose_option) — 后台走仲裁执行链路, 3 秒内返回 toast
        if act == "choose_option":
            resolver_id = value.get("resolver_id", "")
            choice = value.get("choice", "")
            logger.info(
                "[Feishu WS] conflict choice received: resolver_id=%s choice=%s operator=%s",
                resolver_id, choice, operator,
            )
            threading.Thread(
                target=_run_conflict_choice_async, args=(resolver_id, choice), daemon=True
            ).start()
            return P2CardActionTriggerResponse({
                "toast": {"type": "success",
                          "content": "已收到选择（方案 %s），正在进入执行审批..." % choice},
            })

        entry = approval_manager.get_pending(approval_id)
        if entry is None:
            return P2CardActionTriggerResponse({
                "toast": {"type": "warning", "content": "审批单已过期或不存在"},
            })

        skill = entry.get("action_name", "")
        desc = entry.get("description", "")
        conversation_id = entry.get("conversation_id", "")

        if act == "approve":
            approval_manager.resolve(approval_id, True)
            log_action(approval_id=approval_id, skill_name=skill, description=desc,
                       decision="approved", operator=operator, conversation_id=conversation_id)
            # 后台线程执行已批准的操作 (技能调用+结果推送), 保证回调 3 秒内返回
            threading.Thread(
                target=_run_approved_async, args=(approval_id,), daemon=True
            ).start()
            toast = {"type": "success", "content": "已批准，正在执行操作..."}
            card_data = _build_approval_resolved_card(approval_id, skill, desc, True)
        elif act == "reject":
            approval_manager.resolve(approval_id, False)
            approval_manager.reject(approval_id)  # 弹出 entry, 防止重复处理
            log_action(approval_id=approval_id, skill_name=skill, description=desc,
                       decision="rejected", operator=operator, conversation_id=conversation_id)
            toast = {"type": "info", "content": "已拒绝，该操作不会执行"}
            card_data = _build_approval_resolved_card(approval_id, skill, desc, False)
        else:
            logger.warning("[Feishu WS] unknown card action: %s", act)
            return None

        return P2CardActionTriggerResponse({
            "toast": toast,
            "card": {"type": "raw", "data": card_data},
        })
    except Exception as e:
        logger.error("[Feishu WS] card action error: %s", e, exc_info=True)
        return None


def _run_approved_async(approval_id):
    """后台线程: 弹出已批准的审批条目并执行其 action (技能调用+结果推送)"""
    from app.utils.approval import approval_manager
    try:
        approval_manager.take_and_execute(approval_id)
    except Exception as e:
        logger.error("[Feishu WS] approved action failed: %s", e, exc_info=True)


def _run_conflict_choice_async(resolver_id, choice):
    """后台线程: 用户在决策看板点选方案后, 走仲裁执行链路。
    执行器会创建新的审批单, 这里负责把执行审批卡片推回会话。"""
    from app.optimizer.conflict_resolver import get_conflict_resolver
    try:
        result = get_conflict_resolver().apply_choice(resolver_id, choice)
        if not isinstance(result, dict):
            return
        if result.get("type") == "approval_required":
            data = result.get("data", {})
            # conversation_id 存于审批条目中 (verifier 创建审批时写入)
            conversation_id = ""
            try:
                from app.utils.approval import approval_manager
                entry = approval_manager.get_pending(data.get("approval_id", ""))
                if entry:
                    conversation_id = entry.get("conversation_id", "")
            except Exception:
                pass
            try:
                card_json = _build_approval_card(data)
                if conversation_id:
                    feishu_tool.send_message(conversation_id, card_json, msg_type="interactive")
                    logger.info(
                        "[Feishu WS] conflict->approval card sent: resolver=%s approval=%s",
                        resolver_id, data.get("approval_id"),
                    )
            except Exception as e:
                logger.error("[Feishu WS] conflict->approval card failed: %s", e)
        elif result.get("type") == "error":
            logger.warning("[Feishu WS] conflict choice failed: %s", result.get("data"))
    except Exception as e:
        logger.error("[Feishu WS] conflict choice error: %s", e, exc_info=True)


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
        .register_p2_card_action_trigger(do_p2_card_action_trigger) \
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
    # 凭据从环境变量读取 (父进程经 env 传递), 避免通过 argv 暴露密钥给本机进程列表
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if app_id and app_secret:
        start_feishu_ws(app_id, app_secret)
    else:
        logger.error("[Feishu WS] Missing FEISHU_APP_ID/FEISHU_APP_SECRET in environment")
        sys.exit(1)
