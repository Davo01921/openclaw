import copy
import sys
import unittest
from pathlib import Path
root = Path(__file__).resolve().parents[2]
for module in ['nta-shipping-fulfilment', 'nta-shopify-write-verifier', 'nta-shopify-fulfilment-writer', 'nta-shopify-fulfilment-auditor']:
    sys.path.insert(0, str(root / module / 'scripts'))
from shipping_fulfilment import build_verifier_request, idempotency_key
from verification_route import fulfilment_handoff
from fulfilment_write_plan import build_fulfilment_write_plan
from shopify_fulfilment_api import build_create_payload
from fulfilment_audit import audit_fulfilment

EVENT = {'job_id':'shipment-1','authorised':True,'order_id':'gid://shopify/Order/1',
    'carrier':'Australia Post','tracking_number':'ABC123','shipped_at':'2026-10-02T10:00:00+10:00','notify_customer':False,
    'fulfilment_orders':[{'fulfilment_order_id':'gid://shopify/FulfillmentOrder/2','line_items':[{'fulfilment_order_line_item_id':'gid://shopify/FulfillmentOrderLineItem/3','quantity':2}]}]}
CONTEXT = {'source':'FRESH_SHOPIFY_READ','order_id':EVENT['order_id'],'duplicate_completed':False,
    'prior_result_indeterminate':False,'adapter_capability_verified':True,
    'fulfilment_orders':{'gid://shopify/FulfillmentOrder/2':{'order_id':EVENT['order_id'],'status':'OPEN','remaining_lines':{'gid://shopify/FulfillmentOrderLineItem/3':2}}}}

class HandoffTests(unittest.TestCase):
    def request(self): return build_verifier_request(copy.deepcopy(EVENT))['write_request']
    def plan(self, context=None):
        handoff=fulfilment_handoff(self.request(),context or copy.deepcopy(CONTEXT))
        return build_fulfilment_write_plan(handoff['writer_input'])
    def test_tracking_survives_every_boundary_and_fresh_audit(self):
        plan=self.plan();self.assertEqual(plan['status'],'READY')
        payload=build_create_payload(plan['write_plan'])['variables']['fulfillment']
        self.assertEqual(payload['trackingInfo'],{'company':'Australia Post','number':'ABC123'})
        self.assertFalse(payload['notifyCustomer'])
        expected=self.request()['expected_result'];actual={**expected,'source':'FRESH_SHOPIFY_READ','status':'SUCCESS'}
        self.assertEqual(audit_fulfilment(expected,actual)['status'],'PASS')
        actual['tracking_info']={'company':'Australia Post','number':'WRONG'}
        self.assertEqual(audit_fulfilment(expected,actual)['status'],'FAIL')
    def test_wrong_order_and_exhausted_lines_stop_before_write(self):
        for key,value in [('source','WRITER_RESPONSE'),('order_id','gid://shopify/Order/9')]:
            c=copy.deepcopy(CONTEXT);c[key]=value
            self.assertEqual(fulfilment_handoff(self.request(),c)['status'],'REVIEW_REQUIRED')
        c=copy.deepcopy(CONTEXT);c['fulfilment_orders']['gid://shopify/FulfillmentOrder/2']['remaining_lines']['gid://shopify/FulfillmentOrderLineItem/3']=0
        self.assertEqual(fulfilment_handoff(self.request(),c)['status'],'REVIEW_REQUIRED')
    def test_duplicate_completed_never_builds_a_mutation(self):
        c=copy.deepcopy(CONTEXT);c['duplicate_completed']=True
        self.assertEqual(self.plan(c)['status'],'DUPLICATE_NOOP')
    def test_indeterminate_attempt_requires_reconciliation(self):
        c=copy.deepcopy(CONTEXT);c['prior_result_indeterminate']=True
        self.assertEqual(self.plan(c)['status'],'REVIEW_REQUIRED')
    def test_timestamp_reformat_and_redelivery_keep_identity(self):
        self.assertEqual(idempotency_key(EVENT),idempotency_key({**EVENT,'job_id':'redelivery','shipped_at':'2026-10-02T00:00:00Z'}))
    def test_exact_ids_bool_notification_and_pairing(self):
        for change in [{'order_id':'#17407'},{'notify_customer':0},{'tracking_number':None}]:
            self.assertEqual(build_verifier_request({**EVENT,**change})['status'],'REVIEW_REQUIRED')
    def test_writer_cannot_invent_tracking_and_open_is_not_success(self):
        plan=self.plan()['write_plan'];plan['tracking_source_verified']=False
        self.assertEqual(build_create_payload(plan)['status'],'REVIEW_REQUIRED')
        expected=self.request()['expected_result']
        self.assertEqual(audit_fulfilment(expected,{**expected,'source':'FRESH_SHOPIFY_READ','status':'OPEN'})['status'],'FAIL')

    def test_malformed_handoff_is_review_not_an_exception(self):
        for key, value in [('authorised_changes',[None]),('resolved_identity',None)]:
            r=self.request();r[key]=value
            self.assertEqual(fulfilment_handoff(r,CONTEXT)['status'],'REVIEW_REQUIRED')
        r=self.request();r['authorised_changes'][0]['fulfilment_orders'][0]['line_items'][0].pop('fulfilment_order_line_item_id')
        self.assertEqual(fulfilment_handoff(r,CONTEXT)['status'],'REVIEW_REQUIRED')
    def test_duplicate_fulfilment_order_groups_are_rejected(self):
        e=copy.deepcopy(EVENT);other=copy.deepcopy(e['fulfilment_orders'][0]);other['line_items'][0]['fulfilment_order_line_item_id']='gid://shopify/FulfillmentOrderLineItem/4';e['fulfilment_orders'].append(other)
        self.assertEqual(build_verifier_request(e)['status'],'REVIEW_REQUIRED')

if __name__ == '__main__': unittest.main()
