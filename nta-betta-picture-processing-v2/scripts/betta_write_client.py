#!/usr/bin/env python3
"""Pinned client API for the NTA Betta trusted write boundary.

Used by davidlo-owned processes (Fred, watcher, pipelines) to talk to the
root-owned daemon over its UNIX socket. Stdlib only; the client is deliberately
thin — it never decides what is allowed, it only frames requests and returns
full responses so callers can archive receipts.

Contract (pinned in docs/incident/TRUSTED_WRITE_BOUNDARY_BRIEF_2026-10-16.md)::

    class WriteBoundaryClient:
        def __init__(self, socket_path: str, timeout: float = 30.0): ...
        def request(self, payload: dict) -> dict
        def status(self) -> dict
        def verify(self, target: dict, evidence: dict) -> dict
        def build_request(self, *, operation, mode, target, evidence,
                          operations, authorisation, request_id=None) -> dict
"""

from __future__ import annotations

import json
import socket
import uuid
from typing import Any, Optional

REQUEST_SCHEMA = "nta-betta-write-request-v1"
RESPONSE_SCHEMA = "nta-betta-write-response-v1"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class WriteBoundaryClientError(RuntimeError):
    """Transport/protocol failure (never a boundary REFUSED response)."""


class WriteBoundaryClient:
    def __init__(self, socket_path: str, timeout: float = 30.0):
        self.socket_path = str(socket_path)
        self.timeout = float(timeout)

    # -- pinned API --------------------------------------------------------

    def build_request(
        self,
        *,
        operation: str,
        mode: str,
        target: dict,
        evidence: dict,
        operations: list,
        authorisation: dict,
        request_id: Optional[str] = None,
    ) -> dict:
        """Build one schema-valid request payload (including a v4 request_id)."""
        payload = {
            "schema": REQUEST_SCHEMA,
            "request_id": request_id or str(uuid.uuid4()),
            "operation": operation,
            "mode": mode,
            "target": dict(target or {}),
            "operations": list(operations or []),
        }
        if authorisation is not None:
            payload["authorisation"] = dict(authorisation)
        if evidence is not None:
            payload["evidence"] = dict(evidence)
        return payload

    def request(self, payload: dict) -> dict:
        """Send one request and return the full response dict."""
        if not isinstance(payload, dict):
            raise WriteBoundaryClientError("payload must be a dict")
        line = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            conn.settimeout(self.timeout)
            try:
                conn.connect(self.socket_path)
            except OSError as exc:
                raise WriteBoundaryClientError(
                    f"cannot connect to write boundary socket: {exc}") from exc
            try:
                conn.sendall(line)
            except OSError as exc:
                raise WriteBoundaryClientError(
                    f"cannot send to write boundary: {exc}") from exc
            response = self._read_response(conn)
        finally:
            try:
                conn.close()
            except OSError:
                pass
        if not isinstance(response, dict) or response.get("schema") != RESPONSE_SCHEMA:
            raise WriteBoundaryClientError("write boundary returned an invalid response")
        return response

    def status(self) -> dict:
        return self.request(self.build_request(
            operation="status", mode="apply", target={}, evidence=None,
            operations=[], authorisation=None))

    def verify(self, target: dict, evidence: dict) -> dict:
        return self.request(self.build_request(
            operation="verify", mode="apply", target=target,
            evidence=evidence or {}, operations=[], authorisation=None))

    # -- internals ---------------------------------------------------------

    def _read_response(self, conn: socket.socket) -> Any:
        chunks = bytearray()
        while True:
            try:
                chunk = conn.recv(65536)
            except socket.timeout as exc:
                raise WriteBoundaryClientError(
                    "timed out waiting for the write boundary response") from exc
            except OSError as exc:
                raise WriteBoundaryClientError(
                    f"write boundary connection failed: {exc}") from exc
            if not chunk:
                break
            chunks.extend(chunk)
            index = chunks.find(b"\n")
            if index != -1:
                chunks = chunks[:index]
                break
            if len(chunks) > MAX_RESPONSE_BYTES:
                raise WriteBoundaryClientError("write boundary response is too large")
        if not chunks:
            raise WriteBoundaryClientError("write boundary closed without a response")
        try:
            return json.loads(bytes(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WriteBoundaryClientError(
                "write boundary returned invalid JSON") from exc


def _main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="NTA Betta write-boundary client")
    parser.add_argument("--socket", required=True)
    parser.add_argument("command", choices=["status"])
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    client = WriteBoundaryClient(args.socket, timeout=args.timeout)
    response = client.status()
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0 if response.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(_main())
