from langgraph.graph import StateGraph

from .state import AgentState
from .router import router
from app.memory.local_memory import local_memory


def load_history(state):
    conversation_id = state.get("conversation_id", "default")
    state["history"] = local_memory.get_last_n_messages(conversation_id, n=5)
    return state


def save_history(state):
    conversation_id = state.get("conversation_id", "default")
    local_memory.add_message(conversation_id, "user", state["user_input"])
    local_memory.add_message(conversation_id, "assistant", str(state["answer"]))
    return state


def skill_executor(state):
    tool_result = state["tool_result"]
    skill = tool_result.get("skill")
    user_input = tool_result.get("user_input", "")
    
    if skill == "product_skill":
        from app.skills.product_skill import product_skill
        result = product_skill(user_input)
    elif skill == "ads_skill":
        from app.skills.ads_skill import ads_skill
        result = ads_skill(user_input)
    elif skill == "content_skill":
        from app.skills.content_skill import content_skill
        result = content_skill(user_input)
    else:
        result = {"type": "unknown", "data": "鏃犳硶璇嗗埆浠诲姟"}
    
    state["tool_result"] = result
    return state


def answer_node(state):
    result = state["tool_result"]
    state["answer"] = str(result)
    return state


graph = StateGraph(AgentState)


graph.add_node("load_history", load_history)
graph.add_node("router", router)
graph.add_node("skill_executor", skill_executor)
graph.add_node("answer", answer_node)
graph.add_node("save_history", save_history)


graph.set_entry_point("load_history")


graph.add_edge("load_history", "router")
graph.add_edge("router", "skill_executor")
graph.add_edge("skill_executor", "answer")
graph.add_edge("answer", "save_history")


agent = graph.compile()
