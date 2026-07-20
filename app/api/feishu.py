from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json

from app.agents.coordinator import coordinator
from app.agent.workflow import agent
from app.tools.feishu_tool import feishu_tool

router = APIRouter(prefix='/feishu', tags=['feishu'])


class MessageRequest(BaseModel):
    chat_id: str
    content: str
    user_id: Optional[str] = None
    message_type: str = 'text'


@router.post('/webhook')
async def feishu_webhook(request: Request):
    try:
        body = await request.json()
        event = body.get('event', {})
        
        if event.get('type') == 'message':
            message = event.get('message', {})
            content = json.loads(message.get('content', '{}')).get('text', '')
            chat_id = event.get('sender', {}).get('chat_id', '')
            user_id = event.get('sender', {}).get('sender_id', {}).get('user_id', '')
            
            if not content:
                raise HTTPException(status_code=400, detail='Empty message content')
            
            result = coordinator.route_and_coordinate(content)
            
            if feishu_tool.app_id and feishu_tool.app_secret:
                feishu_tool.send_message(chat_id, result.get('summary', str(result)))
            
            return {'status': 'success', 'result': result}
        
        return {'status': 'ignored', 'reason': 'Unknown event type'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/message')
async def send_message(request: MessageRequest):
    try:
        if feishu_tool.app_id and feishu_tool.app_secret:
            result = feishu_tool.send_message(request.chat_id, request.content)
            return {'status': 'success', 'feishu_response': result}
        else:
            return {'status': 'success', 'message': 'Feishu not configured, message would be: ' + request.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/chat')
async def chat_with_agent(request: Request):
    try:
        body = await request.json()
        user_input = body.get('message', '')
        conversation_id = body.get('conversation_id', 'default')
        
        if not user_input:
            raise HTTPException(status_code=400, detail='Message is required')
        
        result = agent.invoke({
            'user_input': user_input,
            'conversation_id': conversation_id
        })
        
        return {
            'status': 'success',
            'answer': result.get('answer', ''),
            'conversation_id': conversation_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
