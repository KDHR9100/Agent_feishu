"""问候语拦截测试: 正则关键词覆盖 + 介绍卡片结构"""
import json

from app.tools.feishu_ws import _build_greeting_card, _is_greeting


def test_common_greetings_hit():
    """常见问候/能力询问应被正则直接拦截"""
    for text in ["hi", "你好", "哈喽", "嗨", "在吗", "在么", "你是谁",
                 "你能做什么", "你会干嘛", "能干什么", "介绍一下你自己",
                 "功能介绍", "hello", "早上好", "你好呀"]:
        assert _is_greeting(text), "未拦截: %r" % text


def test_business_text_not_greeting():
    """正常业务消息不应被误拦截"""
    for text in ["帮我分析一下商品销量", "把爆款价格降 5%", "库存预警",
                 "帮我写一段小红书文案", "广告ROI是多少"]:
        assert not _is_greeting(text), "误拦截: %r" % text


def test_long_text_not_greeting():
    """超长文本(>20字符)即使命中关键词也不视为问候"""
    assert not _is_greeting("你好，我想问一下我们店铺上周的整体销量情况如何，能不能给我一份报告")


def test_greeting_card_structure():
    """介绍卡片是合法飞书交互卡片 JSON"""
    card = json.loads(_build_greeting_card())
    assert card["config"]["wide_screen_mode"] is True
    assert "header" in card and len(card["elements"]) >= 3
