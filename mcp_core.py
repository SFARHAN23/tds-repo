import hashlib, json

EMAIL = "24f2001684@ds.study.iitm.ac.in".strip().lower()
PROTOCOL = "2025-03-26"

TOOL = {
    "name": "solve_challenge",
    "description": "Returns the exam response for the challenge sent in the X-Exam-Challenge header.",
    "inputSchema": {"type": "object", "properties": {}},
}


def solve(challenge: str) -> str:
    return hashlib.sha256(f"{challenge}:{EMAIL}".encode()).hexdigest()[:16]


def handle(msg: dict, headers: dict):
    """Return a JSON-RPC response dict, or None for notifications."""
    method = msg.get("method")
    mid = msg.get("id")
    if mid is None:  # notification
        return None
    if method == "initialize":
        client_v = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": client_v,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "exam-solver", "version": "1.0.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        name = (msg.get("params") or {}).get("name")
        if name != "solve_challenge":
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        challenge = headers.get("x-exam-challenge", "").strip()
        if not challenge:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "missing X-Exam-Challenge header"}],
                "isError": True}}
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": solve(challenge)}]}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}
