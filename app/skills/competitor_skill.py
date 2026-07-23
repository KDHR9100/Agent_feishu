from app.config import get_llm, logger


def competitor_skill(user_input):
    try:
        llm = get_llm()
        prompt = "分析竞品信息: " + user_input
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return {
            "type": "competitor_analysis",
            "data": {
                "user_input": user_input,
                "analysis": content[:500],
            },
        }
    except Exception as e:
        logger.error("competitor_skill error: %s", e)
        return {
            "type": "competitor_analysis",
            "data": {
                "user_input": user_input,
                "analysis": "",
                "error": str(e),
            },
        }
