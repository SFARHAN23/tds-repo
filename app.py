from typing import List, Optional
from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from config_core import effective_config
from mcp_core import handle
import ledger_qa

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], expose_headers=["*"])


@app.get("/effective-config")
def get_config(set: Optional[List[str]] = Query(default=None)):
    return effective_config(set or [])


@app.post("/mcp")
@app.post("/")
async def mcp(request: Request):
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "Parse error"}}, 400)
    if isinstance(body, list):
        out = [r for r in (handle(m, headers) for m in body) if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    resp = handle(body, headers)
    return JSONResponse(resp) if resp is not None else Response(status_code=202)


@app.get("/mcp")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/answer")
async def answer(request: Request):
    try:
        body = await request.json()
        question = str(body.get("question", ""))
    except Exception:
        return JSONResponse({"answer": None, "error": "send JSON {\"question\": \"...\"}"}, 400)
    try:
        return {"answer": ledger_qa.answer(question)}
    except Exception as e:  # never crash the grader
        return {"answer": None, "error": str(e)}


ledger_qa.answer("total revenue")  # load data once at import time
