"""Compose the canonical verifier, writer and independent auditor with durable intent.

Writer and fresh-reader callbacks are supplied by the existing authenticated runtime.
No credentials, customer messages or network retries are owned here.
"""
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
for module in ['nta-shopify-write-verifier', 'nta-shopify-fulfilment-writer', 'nta-shopify-fulfilment-auditor']:
    sys.path.insert(0, str(root / module / 'scripts'))
from verification_route import fulfilment_handoff, build_route
from fulfilment_write_plan import build_fulfilment_write_plan
from fulfilment_audit import audit_fulfilment

def execute_shipment(request, context, ledger, writer, fresh_reader):
    # Completed receipts survive redelivery even after fulfillment orders close.
    route = build_route(request)
    if route['status'] != 'READY' or route['entity'] != 'fulfilment': return route
    prior = ledger.prior_status(request['idempotency_key'])
    if prior: return {'status': prior}
    handoff = fulfilment_handoff(request, context)
    if handoff['status'] != 'READY': return handoff
    plan = build_fulfilment_write_plan(handoff['writer_input'])
    if plan['status'] != 'READY': return plan
    key = request['idempotency_key']
    claimed = ledger.claim(key, request)
    if claimed != 'CLAIMED': return {'status': claimed}
    receipt = {}
    try:
        receipt['writer'] = writer(plan['write_plan'])
        ledger.receipt(key, receipt)
        if receipt['writer'].get('status') != 'SUCCESS':
            return {'status': 'REVIEW_REQUIRED', 'receipt': receipt}
        receipt['audit'] = audit_fulfilment(request['expected_result'], fresh_reader(receipt['writer']))
        ledger.receipt(key, receipt, verified=receipt['audit']['status'] == 'PASS')
        return {'status': 'VERIFIED' if receipt['audit']['status'] == 'PASS' else 'REVIEW_REQUIRED', 'receipt': receipt}
    except Exception as error:
        # Persist diagnostic type only; transport exceptions can contain secrets.
        receipt['failure'] = type(error).__name__
        ledger.receipt(key, receipt)
        return {'status': 'REVIEW_REQUIRED', 'receipt': receipt}
