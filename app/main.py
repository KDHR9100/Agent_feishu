from fastapi import FastAPI

from app.agent.workflow import agent


app = FastAPI()



@app.post("/chat")
def chat(message:str):

    result = agent.invoke(
        {
            "user_input":message
        }
    )


    return {
        "answer":
        result["answer"]
    }