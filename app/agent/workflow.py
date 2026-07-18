from langgraph.graph import StateGraph

from .state import AgentState

from .router import router



def answer_node(state):

    result = state["tool_result"]

    state["answer"] = str(result)

    return state



graph = StateGraph(
    AgentState
)


graph.add_node(
    "router",
    router
)


graph.add_node(
    "answer",
    answer_node
)


graph.set_entry_point(
    "router"
)


graph.add_edge(
    "router",
    "answer"
)


agent = graph.compile()