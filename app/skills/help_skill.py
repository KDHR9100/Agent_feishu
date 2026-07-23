from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.prompts import HELP_PROMPT


def help_skill(user_input: str):
    llm = get_llm()

    prompt = HELP_PROMPT.format(user_input=user_input)

    messages = [
        SystemMessage(content="You are an e-commerce operation expert assistant"),
        HumanMessage(content=prompt),
    ]

    response = llm.invoke(messages).content

    return {
        "type": "help_response",
        "data": {"user_input": user_input, "response": response},
    }
