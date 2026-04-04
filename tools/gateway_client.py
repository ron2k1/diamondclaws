"""OpenClaw gateway WebSocket client.

THE core communication layer. All LLM calls go through here.
Connects via Ed25519 device identity auth (v3 protocol).
"""

import asyncio
import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "ws://127.0.0.1:18789")
IDENTITY_PATH = Path.home() / ".openclaw" / "identity" / "device.json"
OPENCLAW_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"

# Cache gateway availability to avoid repeated probes
_gateway_cache = {"available": None, "checked_at": 0}
_CACHE_TTL = 30  # seconds


def _load_device_identity() -> Optional[dict]:
    if not IDENTITY_PATH.exists():
        return None
    try:
        return json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_gateway_auth_token() -> str:
    """Resolve the gateway auth token from openclaw.json config."""
    try:
        config = json.loads(OPENCLAW_CONFIG_PATH.read_text(encoding="utf-8"))
        token_val = config.get("gateway", {}).get("auth", {}).get("token", "")
        if token_val.startswith("env:"):
            return os.getenv(token_val[4:], "")
        return token_val
    except Exception:
        return os.getenv("OPENCLAW_GATEWAY_TOKEN", "")


def _get_auth_mode() -> str:
    """Get the gateway auth mode from openclaw.json."""
    try:
        config = json.loads(OPENCLAW_CONFIG_PATH.read_text(encoding="utf-8"))
        return config.get("gateway", {}).get("auth", {}).get("mode", "none")
    except Exception:
        return "none"


def _build_device_auth(device: dict, nonce: str, scopes: str = "", token: str = "") -> dict:
    """Build signed device auth payload for connect handshake."""
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key,
        load_pem_public_key,
        Encoding,
        PublicFormat,
    )

    pk = load_pem_private_key(device["privateKeyPem"].encode(), password=None)
    pub = load_pem_public_key(device["publicKeyPem"].encode())
    pub_raw = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    pub_b64url = base64.urlsafe_b64encode(pub_raw).decode().rstrip("=")

    signed_at = int(time.time() * 1000)
    # v3 payload: version|deviceId|clientId|clientMode|role|scopes|signedAt|token|nonce|platform|deviceFamily
    payload_str = "|".join([
        "v3",
        device["deviceId"],
        "cli",          # client ID (must be "cli")
        "cli",          # client mode (must be "cli")
        "operator",     # role
        scopes,         # comma-separated scopes
        str(signed_at),
        token,          # gateway token (empty if auth mode is "none")
        nonce,
        "win32",
        "",             # deviceFamily
    ])
    signature = pk.sign(payload_str.encode())
    sig_b64url = base64.urlsafe_b64encode(signature).decode().rstrip("=")

    return {
        "id": device["deviceId"],
        "publicKey": pub_b64url,
        "signature": sig_b64url,
        "signedAt": signed_at,
        "nonce": nonce,
    }


async def _connect_ws(scopes: list[str] | None = None):
    """Connect and authenticate to the OpenClaw gateway.

    Tries with requested scopes first, falls back to empty scopes
    if pairing is required.
    """
    import websockets

    device = _load_device_identity()
    if not device:
        return None

    try:
        ws = await websockets.connect(GATEWAY_URL, open_timeout=10)
    except Exception:
        return None

    try:
        # Receive challenge
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        ch = json.loads(raw)
        nonce = ch["payload"]["nonce"]

        # Determine auth config
        auth_mode = _get_auth_mode()
        token = _load_gateway_auth_token() if auth_mode == "token" else ""
        requested_scopes = scopes if scopes is not None else []
        scopes_str = ",".join(requested_scopes)

        # Build connect message
        device_auth = _build_device_auth(device, nonce, scopes=scopes_str, token=token)
        connect_params = {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": "cli",
                "version": "2026.4.2",
                "platform": "win32",
                "mode": "cli",
            },
            "role": "operator",
            "scopes": requested_scopes,
            "device": device_auth,
        }
        # Add auth.token only when gateway auth mode is "token"
        if auth_mode == "token" and token:
            connect_params["auth"] = {"token": token}

        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": connect_params,
        }
        await ws.send(json.dumps(connect_msg))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))

        if resp.get("ok"):
            return ws

        # If scope upgrade needs pairing, retry with empty scopes
        error_code = resp.get("error", {}).get("details", {}).get("code", "")
        if error_code == "PAIRING_REQUIRED" and requested_scopes:
            await ws.close()
            return await _connect_ws(scopes=[])

        await ws.close()
        return None

    except Exception:
        try:
            await ws.close()
        except Exception:
            pass
        return None


async def _request(ws, method: str, params: dict, timeout: float = 10) -> dict:
    """Send a request and wait for the matching response."""
    rid = str(uuid.uuid4())
    await ws.send(json.dumps({"type": "req", "id": rid, "method": method, "params": params}))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("type") == "res" and msg.get("id") == rid:
            return msg


def is_gateway_available() -> bool:
    """Fast cached check if gateway is reachable."""
    now = time.time()
    if (now - _gateway_cache["checked_at"]) < _CACHE_TTL and _gateway_cache["available"] is not None:
        return _gateway_cache["available"]
    # Can't run async from sync — return cached or assume unknown
    return _gateway_cache.get("available", False)


async def probe_gateway() -> dict:
    """Probe the OpenClaw gateway. Returns status dict."""
    global _gateway_cache
    try:
        ws = await _connect_ws(scopes=["operator.admin"])
        if not ws:
            # Try with no scopes — at least confirm gateway is running
            ws = await _connect_ws(scopes=[])
            if not ws:
                _gateway_cache = {"available": False, "checked_at": time.time()}
                return {"running": False, "reason": "connection failed"}

        async with ws:
            _gateway_cache = {"available": True, "checked_at": time.time()}

            # Try health check
            try:
                health = await _request(ws, "health", {}, timeout=5)
                health_payload = health.get("result", health.get("payload", {}))
            except Exception:
                health_payload = {}

            # Try agents list
            agents = []
            try:
                agents_resp = await _request(ws, "gateway.agents", {}, timeout=5)
                if agents_resp.get("ok"):
                    agents_data = agents_resp.get("result", agents_resp.get("payload", {}))
                    agents = agents_data.get("agents", [])
            except Exception:
                pass

            diamond_agents = [
                a for a in agents if (a.get("id") or a.get("agentId") or "").startswith("diamond-")
            ]

            return {
                "running": True,
                "version": health_payload.get("version", "unknown"),
                "uptime_ms": health_payload.get("uptimeMs", 0),
                "agents": [a.get("id") or a.get("agentId") or "?" for a in agents],
                "diamond_agents": [a.get("id") or a.get("agentId") or "?" for a in diamond_agents],
                "agent_count": len(agents),
                "diamond_count": len(diamond_agents),
                "default_agent": health_payload.get("defaultAgentId", "main"),
                "channels": list(health_payload.get("channels", {}).keys()),
            }
    except Exception as e:
        _gateway_cache = {"available": False, "checked_at": time.time()}
        return {"running": False, "reason": str(e)}


async def send_agent_message(agent_id: str, message: str, timeout_ms: int = 90000) -> dict:
    """Send a message to an agent and collect the full response."""
    full_text = ""
    last_event = None
    async for event in stream_agent_message(agent_id, message, timeout_ms=timeout_ms):
        if event["type"] == "token":
            full_text += event["text"]
        elif event["type"] == "error":
            return {"ok": False, "error": event["error"], "text": full_text, "agent_id": agent_id}
        last_event = event

    if last_event and last_event["type"] == "done":
        return {
            "ok": True,
            "text": last_event.get("text", full_text),
            "agent_id": agent_id,
            "run_id": last_event.get("run_id"),
            "session_key": last_event.get("session_key"),
        }
    return {"ok": bool(full_text), "text": full_text, "agent_id": agent_id}


async def stream_agent_message(
    agent_id: str,
    message: str,
    session_key: str | None = None,
    timeout_ms: int = 60000,
):
    """Stream events from an agent via the gateway.

    Yields:
      {"type": "token", "text": "..."}
      {"type": "tool_use", "name": "..."}
      {"type": "tool_result", "name": "...", ...}
      {"type": "tool_output", "name": "...", "text": "..."}
      {"type": "approval_request", ...}
      {"type": "done", "text": "...", "agent_id": "...", "run_id": "...", "session_key": "..."}
      {"type": "error", "error": "..."}
    """
    try:
        ws = await _connect_ws(scopes=["operator.admin"])
        if not ws:
            ws = await _connect_ws(scopes=[])
        if not ws:
            yield {"type": "error", "error": "Cannot connect to OpenClaw gateway"}
            return

        async with ws:
            if not session_key:
                session_key = f"agent:{agent_id}:webchat-{uuid.uuid4().hex[:8]}"
            idem = str(uuid.uuid4())

            resp = await _request(ws, "agent", {
                "message": message,
                "sessionKey": session_key,
                "idempotencyKey": idem,
                "deliver": False,
                "channel": "webchat",
            }, timeout=15)

            if not resp.get("ok"):
                err = resp.get("error", {}).get("message", "agent request failed")
                yield {"type": "error", "error": err}
                return

            run_id = resp.get("payload", resp.get("result", {})).get("runId")
            if not run_id:
                yield {"type": "error", "error": "no run ID returned"}
                return

            response_text = ""
            deadline = time.time() + (timeout_ms / 1000)
            using_agent_stream = False

            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=min(5, deadline - time.time())
                    )
                    msg = json.loads(raw)

                    if msg.get("type") == "event":
                        evt = msg.get("event", "")
                        payload = msg.get("payload", {})

                        if evt == "agent":
                            stream = payload.get("stream", "")
                            data = payload.get("data", {})

                            if stream == "assistant":
                                delta = data.get("delta", "")
                                if delta:
                                    using_agent_stream = True
                                    response_text += delta
                                    yield {"type": "token", "text": delta}

                            elif stream == "tool":
                                tool_name = data.get("name", data.get("toolName", ""))
                                phase = data.get("phase", data.get("status", ""))
                                if phase in ("start", "running"):
                                    yield {"type": "tool_use", "name": tool_name}
                                elif phase in ("end", "done", "ok", "complete"):
                                    yield {
                                        "type": "tool_result",
                                        "name": tool_name,
                                        "stdout": data.get("stdout", ""),
                                        "stderr": data.get("stderr", ""),
                                        "exit_code": data.get("exitCode"),
                                        "output": data.get("output", ""),
                                    }
                                if data.get("stdout") and phase not in ("end", "done", "ok", "complete"):
                                    yield {"type": "tool_output", "name": tool_name, "text": data.get("stdout", "")}

                            elif stream == "lifecycle":
                                if data.get("phase") == "end":
                                    break

                            else:
                                if payload.get("status") in ("ok", "done", "complete"):
                                    break

                        elif evt == "chat":
                            state = payload.get("state", "")
                            if state == "error":
                                yield {"type": "error", "error": payload.get("errorMessage", "agent error")}
                                return

                            if not using_agent_stream:
                                message_obj = payload.get("message", {})
                                content_blocks = message_obj.get("content", [])
                                if isinstance(content_blocks, list):
                                    content = " ".join(c.get("text", "") for c in content_blocks if c.get("type") == "text")
                                elif isinstance(content_blocks, str):
                                    content = content_blocks
                                else:
                                    content = ""
                                if content and content != response_text:
                                    delta = content[len(response_text):] if content.startswith(response_text) else content
                                    if delta:
                                        yield {"type": "token", "text": delta}
                                    response_text = content

                            if state == "final":
                                message_obj = payload.get("message", {})
                                content_blocks = message_obj.get("content", [])
                                if isinstance(content_blocks, list):
                                    response_text = " ".join(c.get("text", "") for c in content_blocks if c.get("type") == "text")
                                elif isinstance(content_blocks, str):
                                    response_text = content_blocks

                        elif evt == "tool":
                            name = payload.get("name", payload.get("toolName", ""))
                            status = payload.get("status", "")
                            if status in ("running", "start"):
                                yield {"type": "tool_use", "name": name}
                            elif status in ("done", "ok", "complete"):
                                yield {"type": "tool_result", "name": name}

                    elif msg.get("type") == "req" and msg.get("method") == "exec.approval.request":
                        approval_params = msg.get("params", {})
                        yield {
                            "type": "approval_request",
                            "approval_id": msg.get("id", ""),
                            "agent_id": agent_id,
                            "command": approval_params.get("command", ""),
                            "cwd": approval_params.get("cwd", ""),
                            "description": approval_params.get("description", ""),
                        }

                    elif msg.get("type") == "res":
                        p = msg.get("payload", msg.get("result", {}))
                        if p.get("status") == "ok":
                            break

                except asyncio.TimeoutError:
                    continue

            # Fallback: fetch from session history
            if not response_text:
                try:
                    hist = await _request(ws, "chat.history", {"sessionKey": session_key}, timeout=5)
                    messages = hist.get("payload", hist.get("result", {})).get("messages", [])
                    for m in reversed(messages):
                        if m.get("role") == "assistant":
                            content = m.get("content", "")
                            if isinstance(content, list):
                                response_text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
                            elif isinstance(content, str):
                                response_text = content
                            if response_text:
                                yield {"type": "token", "text": response_text}
                                break
                except Exception:
                    pass

            yield {
                "type": "done",
                "text": response_text,
                "agent_id": agent_id,
                "run_id": run_id,
                "session_key": session_key,
            }

    except Exception as e:
        yield {"type": "error", "error": str(e)}


async def resolve_approval(approval_id: str, decision: str) -> dict:
    """Send an exec approval decision back to the gateway."""
    try:
        ws = await _connect_ws(scopes=[])
        if not ws:
            return {"ok": False, "error": "Gateway unreachable"}

        async with ws:
            resp = await _request(ws, "exec.approval.resolve", {
                "id": approval_id,
                "decision": decision,
            }, timeout=10)
            return {"ok": resp.get("ok", False)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
