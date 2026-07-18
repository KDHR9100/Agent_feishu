from app.skills.product_skill import product_skill
from app.skills.ads_skill import ads_skill
from app.skills.content_skill import content_skill


def router(state):

    message = state["user_input"]


    if "销量" in message or "商品" in message:

        result = product_skill(message)


    elif "广告" in message or "ROI" in message:

        result = ads_skill(message)


    elif "文案" in message:

        result = content_skill(message)


    else:

        result = {
            "type":"unknown",
            "data":"无法识别任务"
        }


    state["tool_result"] = result

    return state