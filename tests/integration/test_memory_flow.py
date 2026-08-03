"""集成测试1: 记忆扩容 - 模拟25轮真实对话数据流"""
import os
import sys
import uuid
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.memory.local_memory import LocalMemory, SUMMARIZE_THRESHOLD, RECENT_KEEP_COUNT


class TestMemory25RoundFlow:
    """模拟真实用户: 前20条聊天气, 后5条聊业务, 第25条问记忆"""

    def setup_method(self):
        self.memory = LocalMemory(max_history=60, max_conversations=100)
        self.cid = str(uuid.uuid4())

    def test_25_rounds_recall_first_business_msg(self):
        """第25轮提问时, 必须能取回第21轮(第一个业务需求)的内容"""
        # 前20条: 聊天气
        weather_msgs = [
            "今天天气怎么样", "明天会下雨吗", "后天呢", "这周末适合出游吗",
            "北京天气如何", "上海呢", "广州热不热", "深圳台风来了吗",
            "成都雾霾严重吗", "杭州适合跑步吗", "南京梧桐絮烦死了",
            "武汉夏天太热了", "重庆火锅配冰粉", "西安今天多少度",
            "哈尔滨下雪了吗", "三亚能游泳吗", "拉萨紫外线强吗",
            "昆明四季如春对吧", "厦门海风舒服", "青岛啤酒节快到了",
        ]
        for i, msg in enumerate(weather_msgs):
            self.memory.add_message(self.cid, "user", msg)
            self.memory.add_message(self.cid, "assistant", f"天气回复{i+1}")

        # 后5条: 聊业务(第21-25条user消息)
        business_msgs = [
            "帮我查一下SKU-A123的库存",  # 第21条 = 第一个业务需求
            "库存低于100要预警",
            "顺便看看广告ROI",
            "ROI低于2就暂停投放",
            "还记得我最开始说的第一个业务需求吗？",  # 第25条
        ]
        for i, msg in enumerate(business_msgs):
            self.memory.add_message(self.cid, "user", msg)
            self.memory.add_message(self.cid, "assistant", f"业务回复{i+1}")

        # 验证: get_context 返回最近30条
        summary, recent = self.memory.get_context(self.cid, n=30)
        assert len(recent) == 30

        # 验证: 最近30条中必须包含第一个业务需求
        all_contents = [m["content"] for m in recent]
        assert "帮我查一下SKU-A123的库存" in all_contents, \
            "第一个业务需求必须在最近30条中"

        # 验证: 第25条提问也在其中
        assert "还记得我最开始说的第一个业务需求吗？" in all_contents

    def test_50_plus_messages_triggers_summary(self):
        """超过50条消息时, 摘要机制必须触发"""
        with patch("app.config.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "用户先聊了天气，然后询问了SKU-A123库存和广告ROI"
            mock_llm.invoke.return_value = mock_response
            mock_get_llm.return_value = mock_llm

            # 写入52条消息(26轮对话)
            for i in range(26):
                self.memory.add_message(self.cid, "user", f"消息{i}")
                self.memory.add_message(self.cid, "assistant", f"回复{i}")

            # 摘要必须被触发
            assert mock_llm.invoke.called
            summary, recent = self.memory.get_context(self.cid)
            assert summary is not None
            assert "SKU-A123" in summary or "库存" in summary

    def test_load_history_node_integration(self):
        """验证 workflow.load_history 正确调用 get_context(n=30)"""
        from app.agent.workflow import load_history

        # 预填充数据
        for i in range(35):
            self.memory.add_message(self.cid, "user", f"msg_{i}")

        with patch("app.agent.workflow.local_memory", self.memory):
            state = {"conversation_id": self.cid}
            result = load_history(state)

        assert len(result["history"]) == 30
        assert result["history"][-1]["content"] == "msg_34"
        assert result["history"][0]["content"] == "msg_5"

    def test_conversation_isolation(self):
        """不同 conversation_id 的记忆必须隔离"""
        cid_a = str(uuid.uuid4())
        cid_b = str(uuid.uuid4())

        self.memory.add_message(cid_a, "user", "A的秘密")
        self.memory.add_message(cid_b, "user", "B的秘密")

        _, recent_a = self.memory.get_context(cid_a)
        _, recent_b = self.memory.get_context(cid_b)

        contents_a = [m["content"] for m in recent_a]
        contents_b = [m["content"] for m in recent_b]

        assert "A的秘密" in contents_a
        assert "B的秘密" not in contents_a
        assert "B的秘密" in contents_b
        assert "A的秘密" not in contents_b