import re
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.prompts import CONTENT_GENERATION_PROMPT


PLATFORMS = {
    'douyin': {
        'name': 'Douyin',
        'max_length': 1000,
        'style': 'colloquial, rhythmic, use emojis, hashtags',
        'features': ['short video copy', 'live streaming script', 'comment interaction'],
    },
    'taobao': {
        'name': 'Taobao',
        'max_length': 2000,
        'style': 'professional, detailed, highlight selling points, use marketing terms',
        'features': ['detail page copy', 'main image copy', 'promotion copy'],
    },
    'xiaohongshu': {
        'name': 'Xiaohongshu',
        'max_length': 1500,
        'style': '绉嶈崏 style, friendly, natural, use hashtags, emojis',
        'features': ['notes copy', 'review copy', 'tutorial copy'],
    },
    'wechat': {
        'name': 'WeChat',
        'max_length': 3000,
        'style': 'professional, in-depth, suitable for reading',
        'features': ['official account article', 'moments copy', 'community operation copy'],
    },
    'pinduoduo': {
        'name': 'Pinduoduo',
        'max_length': 1000,
        'style': 'concise, highlight price advantage, sense of urgency',
        'features': ['product title', 'promotion copy', 'group buying copy'],
    },
}


CONTENT_TEMPLATES = {
    'product_introduction': {
        'name': 'Product Introduction',
        'description': 'Introduce product features, functions, advantages',
        'structure': ['product highlights', 'core functions', 'usage scenarios', 'pain points solved'],
    },
    'promotion': {
        'name': 'Promotion Campaign',
        'description': 'Promotion activities, discount information',
        'structure': ['campaign theme', 'discount content', 'campaign time', 'participation method'],
    },
    'review': {
        'name': 'Product Review',
        'description': 'Product usage experience sharing',
        'structure': ['unboxing experience', 'usage feeling', 'pros and cons', 'purchase recommendation'],
    },
    'how_to': {
        'name': 'Usage Tutorial',
        'description': 'Product usage guide',
        'structure': ['preparation', 'steps', 'notes', 'common issues'],
    },
    'storytelling': {
        'name': 'Brand Story',
        'description': 'Brand emotional marketing',
        'structure': ['brand origin', 'core values', 'user stories', 'future vision'],
    },
}


def detect_platform(user_input: str) -> str:
    platform_keywords = {
        'douyin': ['douyin', 'short video', 'live'],
        'taobao': ['taobao', 'detail page'],
        'xiaohongshu': ['xiaohongshu', '绉嶈崏', 'notes'],
        'wechat': ['wechat', 'official account', 'moments'],
        'pinduoduo': ['pinduoduo', 'group buy'],
    }
    user_lower = user_input.lower()
    for platform, keywords in platform_keywords.items():
        for keyword in keywords:
            if keyword.lower() in user_lower:
                return platform
    return 'taobao'


def detect_template(user_input: str) -> str:
    template_keywords = {
        'product_introduction': ['introduce', 'function', 'feature', 'advantage'],
        'promotion': ['promotion', 'discount', 'campaign', 'sale'],
        'review': ['review', 'experience', 'evaluation'],
        'how_to': ['tutorial', 'how to', 'usage', 'steps'],
        'storytelling': ['story', 'brand', 'philosophy', 'values'],
    }
    user_lower = user_input.lower()
    for template, keywords in template_keywords.items():
        for keyword in keywords:
            if keyword.lower() in user_lower:
                return template
    return 'product_introduction'


def extract_product_info(user_input: str) -> dict:
    info = {}
    
    price_match = re.search(r'price\s*[:]?\s*([\d.]+)', user_input, re.IGNORECASE)
    if price_match:
        info['price'] = price_match.group(1)

    name_match = re.search(r'product\s*[:]?\s*([^锛屻€傦紒?]+)', user_input, re.IGNORECASE)
    if name_match:
        info['product_name'] = name_match.group(1)

    feature_match = re.search(r'features\s*[:]?\s*([^锛屻€傦紒?]+)', user_input, re.IGNORECASE)
    if feature_match:
        info['features'] = feature_match.group(1)

    return info


def content_skill(user_input: str):
    llm = get_llm()

    platform = detect_platform(user_input)
    template = detect_template(user_input)
    product_info = extract_product_info(user_input)

    platform_config = PLATFORMS.get(platform, PLATFORMS['taobao'])
    template_config = CONTENT_TEMPLATES.get(template, CONTENT_TEMPLATES['product_introduction'])

    features_str = ', '.join(str(f) for f in platform_config['features'])  # type: ignore
    structure_str = ', '.join(str(s) for s in template_config['structure'])  # type: ignore
    
    enhanced_prompt = (
        f"[PLATFORM REQUIREMENTS]\\n"
        f"Platform: {platform_config['name']}\\n"
        f"Style: {platform_config['style']}\\n"
        f"Max Length: {platform_config['max_length']} characters\\n"
        f"Applicable Scenarios: {features_str}\\n\\n"
        f"[CONTENT TEMPLATE]\\n"
        f"Template Type: {template_config['name']}\\n"
        f"Template Description: {template_config['description']}\\n"
        f"Content Structure: {structure_str}\\n\\n"
        f"[PRODUCT INFO]\\n"
        f"{product_info}\\n\\n"
        f"[USER REQUEST]\\n"
        f"{user_input}\\n\\n"
        f"Please generate marketing copy according to the above requirements."
    )

    messages = [
        SystemMessage(content='You are an e-commerce marketing copywriting expert'),
        HumanMessage(content=enhanced_prompt),
    ]

    copy = llm.invoke(messages).content

    return {
        'type': 'marketing_copy',
        'data': {
            'user_input': user_input,
            'copy': copy,
            'platform': platform_config['name'],
            'template': template_config['name'],
            'product_info': product_info,
        }
    }
