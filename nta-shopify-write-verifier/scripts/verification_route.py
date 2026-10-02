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


def fulfilment_handoff(request, context):
    """Map an authorized verifier envelope after exact fresh order/line checks.

    This function performs no write. The writer still owns its capability and
    execution gates; a mutation result must then pass the independent auditor.
    """
    route = build_route(request)
    if route['status'] != 'READY' or route['entity'] != 'fulfilment':
        return {'status': 'REVIEW_REQUIRED', 'problems': ['fulfilment route required']}
    changes = request.get('authorised_changes')
    if not isinstance(changes, list) or len(changes) != 1 or not isinstance(context, dict):
        return {'status': 'REVIEW_REQUIRED', 'problems': ['one change and fresh context required']}
    change = changes[0]
    identity = request.get('resolved_identity')
    if not isinstance(change, dict) or not isinstance(identity, dict) or not isinstance(change.get('notify_customer'), bool):
        return {'status': 'REVIEW_REQUIRED', 'problems': ['exact change, identity and notification boolean required']}
    order_id = identity.get('order_id')
    if not isinstance(order_id, str) or not order_id.strip():
        return {'status': 'REVIEW_REQUIRED', 'problems': ['exact order ID required']}
    if context.get('source') != 'FRESH_SHOPIFY_READ' or context.get('order_id') != order_id:
        return {'status': 'REVIEW_REQUIRED', 'problems': ['fresh exact order identity required']}
    groups = change.get('fulfilment_orders')
    if not isinstance(groups, list) or not groups:
        return {'status': 'REVIEW_REQUIRED', 'problems': ['fulfilment groups required']}
    actual = context.get('fulfilment_orders', {})
    if not isinstance(actual, dict):
        return {'status': 'REVIEW_REQUIRED', 'problems': ['fresh fulfilment-order map required']}
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('fulfilment_order_id'), str) or not isinstance(group.get('line_items'), list) or not group['line_items']:
            return {'status': 'REVIEW_REQUIRED', 'problems': ['invalid fulfilment group']}
        current = actual.get(group['fulfilment_order_id'], {})
        if not isinstance(current, dict) or current.get('order_id') != order_id:
            return {'status': 'REVIEW_REQUIRED', 'problems': ['fulfilment order belongs to another order']}
        if not context.get('duplicate_completed'):
            if current.get('status') not in {'OPEN', 'IN_PROGRESS'}:
                return {'status': 'REVIEW_REQUIRED', 'problems': ['fulfilment order is not open']}
            for line in group['line_items']:
                if not isinstance(line, dict) or not isinstance(line.get('quantity'), int) or isinstance(line['quantity'], bool) or line['quantity'] <= 0 or not isinstance(current.get('remaining_lines'), dict):
                    return {'status': 'REVIEW_REQUIRED', 'problems': ['invalid exact line quantity']}
                remaining = current.get('remaining_lines', {}).get(line.get('fulfilment_order_line_item_id'))
                quantity = line['quantity']
                if not isinstance(remaining, int) or isinstance(remaining, bool) or remaining < quantity:
                    return {'status': 'REVIEW_REQUIRED', 'problems': ['insufficient exact remaining quantity']}
    carrier, number = change.get('carrier'), change.get('tracking_number')
    if (carrier is None) != (number is None) or (carrier is not None and (not isinstance(carrier, str) or not isinstance(number, str) or not carrier.strip() or not number.strip())):
        return {'status': 'REVIEW_REQUIRED', 'problems': ['carrier and tracking must be paired']}
    tracking = {'company': carrier.strip(), 'number': number.strip()} if carrier else None
    return {'status': 'READY', 'writer_input': {
        'job_id': request['job_id'], 'idempotency_key': request['idempotency_key'],
        'authorised': True, 'order_id': order_id,
        'notify_customer': change['notify_customer'], 'fulfilment_orders': groups,
        'tracking_info': tracking, 'tracking_source_verified': tracking is not None,
        'duplicate_completed': context.get('duplicate_completed'),
        'prior_result_indeterminate': context.get('prior_result_indeterminate'),
        'retry_authorised': request.get('retry_authorised', False),
        'adapter_capability_verified': context.get('adapter_capability_verified'),
    }}
