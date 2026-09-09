#!/usr/bin/env python3
"""Deterministic routing and child-result gates for nta-shopify-write-verifier."""

SUPPORTED_PRODUCT_ENTITIES = {"product", "variant", "inventory"}
SUPPORTED_ORDER_ENTITIES = {"order"}
SUPPORTED_FULFILMENT_ENTITIES = {"fulfilment"}
DECLARED_BUT_UNIMPLEMENTED = {"media"}
VALID_WRITER_SUCCESS = {"SUCCESS", "DUPLICATE_NOOP"}
VALID_AUDIT_PASS = {"PASS", "PASS_WITH_WARNING"}


def build_route(request):
    problems = []
    if not isinstance(request, dict):
        return _review(["request must be an object"])

    job_id = request.get("job_id")
    idempotency_key = request.get("idempotency_key")
    entity = request.get("entity")
    authorised = request.get("authorised")

    if not isinstance(job_id, str) or not job_id.strip():
        problems.append("stable job_id is required")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        problems.append("stable idempotency_key is required")
    if authorised is not True:
        problems.append("explicit authorisation is required")
    if not isinstance(entity, str) or not entity.strip():
        problems.append("entity is required")

    if problems:
        return _review(problems)

    entity = entity.strip().lower()
    if entity in SUPPORTED_PRODUCT_ENTITIES:
        return {
            "status": "READY",
            "entity": entity,
            "writer": "nta-shopify-product-writer",
            "auditor": "nta-product-qa-auditor",
            "fresh_read_required": True,
            "retry_policy": "ONE_EXPLICITLY_SAFE_RETRY_MAX",
            "notes": [],
        }
    if entity in SUPPORTED_ORDER_ENTITIES:
        return {
            "status": "READY",
            "entity": entity,
            "writer": "nta-shopify-order-writer",
            "auditor": "nta-shopify-order-auditor",
            "fresh_read_required": True,
            "retry_policy": "ONE_EXPLICITLY_SAFE_RETRY_MAX",
            "notes": ["order audit must use fresh read-back, never writer response"],
        }
    if entity in SUPPORTED_FULFILMENT_ENTITIES:
        return {
            "status": "READY",
            "entity": entity,
            "writer": "nta-shopify-fulfilment-writer",
            "auditor": "nta-shopify-fulfilment-auditor",
            "fresh_read_required": True,
            "retry_policy": "ONE_EXPLICITLY_SAFE_RETRY_MAX",
            "notes": ["fulfilment audit must use fresh read-back; live adapter capability remains a child-skill gate"],
        }
    if entity in DECLARED_BUT_UNIMPLEMENTED:
        return {
            "status": "BLOCKED",
            "entity": entity,
            "writer": None,
            "auditor": None,
            "fresh_read_required": True,
            "retry_policy": "NONE",
            "notes": [f"canonical {entity} writer/auditor pair is not implemented"],
        }
    return _review([f"unsupported entity: {entity}"])


def writer_gate(writer_status):
    if writer_status in VALID_WRITER_SUCCESS:
        return {"continue": True, "status": "CONTINUE_TO_FRESH_READ"}
    if writer_status in {"PARTIAL", "FAILED"}:
        return {"continue": False, "status": "FAILED"}
    if writer_status in {"BLOCKED", "REVIEW_REQUIRED", "NONE", None}:
        return {"continue": False, "status": "BLOCKED" if writer_status == "BLOCKED" else "REVIEW_REQUIRED"}
    return {"continue": False, "status": "REVIEW_REQUIRED"}


def auditor_gate(audit_status, retry_count=0, retry_safe=False, retry_authorised=False):
    if audit_status == "PASS":
        return {"status": "VERIFIED", "retry": False}
    if audit_status == "PASS_WITH_WARNING":
        return {"status": "VERIFIED_WITH_WARNING", "retry": False}
    if audit_status == "REVIEW_REQUIRED":
        return {"status": "REVIEW_REQUIRED", "retry": False}
    if audit_status == "FAIL":
        if retry_count < 1 and retry_safe is True and retry_authorised is True:
            return {"status": "RETRY_ONCE", "retry": True}
        return {"status": "FAILED", "retry": False}
    return {"status": "REVIEW_REQUIRED", "retry": False}


def _review(problems):
    return {
        "status": "REVIEW_REQUIRED",
        "entity": None,
        "writer": None,
        "auditor": None,
        "fresh_read_required": True,
        "retry_policy": "NONE",
        "notes": problems,
    }
