import re
from typing import Any, Dict, List
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm, logger


class SupportSkill:
    def __init__(self):
        self.support_topics = [
            '订单问题', '物流查询', '退换货', '售后', '产品咨询',
            '价格', '库存', '优惠券', '会员', '支付',
        ]
    
    def classify_intent(self, user_input: str) -> str:
        topic_keywords = {
            '订单问题': ['订单', '下单', '购买', '订单号'],
            '物流查询': ['物流', '快递', '运输', '配送', '单号'],
            '退换货': ['退货', '退款', '换货', '售后'],
            '产品咨询': ['产品', '功能', '使用', '说明', '怎么用'],
            '价格': ['价格', '多少钱', '优惠', '折扣'],
            '库存': ['库存', '有货', '缺货'],
            '优惠券': ['优惠券', '满减', '折扣码'],
            '会员': ['会员', 'VIP', '积分'],
            '支付': ['支付', '付款', '余额'],
        }
        
        for topic, keywords in topic_keywords.items():
            for keyword in keywords:
                if keyword in user_input:
                    return topic
        
        return '其他'
    
    def extract_ticket_info(self, user_input: str) -> Dict[str, str]:
        order_id_match = re.search(r'订单号[:\s]*([a-zA-Z0-9]+)', user_input)
        phone_match = re.search(r'手机号[:\s]*([1][3-9]\d{9})', user_input)
        email_match = re.search(r'邮箱[:\s]*([^\s@]+@[^\s@]+\.[^\s@]+)', user_input)
        
        return {
            'order_id': order_id_match.group(1) if order_id_match else '',
            'phone': phone_match.group(1) if phone_match else '',
            'email': email_match.group(1) if email_match else '',
        }
    
    def handle_support(self, user_input: str) -> Dict[str, Any]:
        llm = get_llm()
        intent = self.classify_intent(user_input)
        ticket_info = self.extract_ticket_info(user_input)
        
        ticket_result = self._query_ticket_system(ticket_info)
        
        if 'error' in ticket_result:
            prompt = f"""
You are a professional e-commerce customer service agent.

[USER INTENT]
{intent}

[USER INPUT]
{user_input}

[EXTRACTED INFO]
{ticket_info}

The ticket system is currently unavailable.

Please provide a friendly, helpful response to the customer.
If the user mentions an order number, ask them to provide it so we can look up their order.
If the user has a specific question, answer it based on general knowledge.
"""
            messages = [
                SystemMessage(content='You are a friendly e-commerce customer service representative'),
                HumanMessage(content=prompt),
            ]
            response = llm.invoke(messages).content
            
            return {
                'type': 'support',
                'data': {
                    'user_input': user_input,
                    'intent': intent,
                    'ticket_info': ticket_info,
                    'response': response,
                    'note': 'Using fallback response (ticket system unavailable)',
                }
            }
        
        prompt = f"""
You are a professional e-commerce customer service agent.

[USER INTENT]
{intent}

[USER INPUT]
{user_input}

[EXTRACTED INFO]
{ticket_info}

[TICKET DATA]
{ticket_result}

Please provide a friendly, helpful response to the customer based on the ticket data.
Address the customer's concern directly and provide specific solutions.
"""
        
        messages = [
            SystemMessage(content='You are a friendly e-commerce customer service representative'),
            HumanMessage(content=prompt),
        ]
        
        response = llm.invoke(messages).content
        
        return {
            'type': 'support',
            'data': {
                'user_input': user_input,
                'intent': intent,
                'ticket_info': ticket_info,
                'ticket_result': ticket_result,
                'response': response,
            }
        }
    
    def _query_ticket_system(self, ticket_info: Dict[str, str]) -> Dict[str, Any]:
        try:
            from app.tools.ticket_tool import ticket_tool
            
            if ticket_info['order_id']:
                return ticket_tool.query_order(ticket_info['order_id'])
            elif ticket_info['phone']:
                return ticket_tool.query_by_phone(ticket_info['phone'])
            else:
                return {"error": "No order ID or phone number provided"}
        
        except ImportError:
            return {"error": "Ticket tool not available"}
        except Exception as e:
            logger.error(f"[SupportSkill] Ticket system error: {e}")
            return {"error": f"Ticket system failed: {str(e)}"}


def support_skill(user_input: str) -> Dict[str, Any]:
    skill = SupportSkill()
    return skill.handle_support(user_input)
