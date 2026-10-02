import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from shipment_ledger import ShipmentLedger
from shipment_boundary import execute_shipment
from test_handoff import EVENT, CONTEXT
from shipping_fulfilment import build_verifier_request

class DurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'ledger.sqlite';self.ledger=ShipmentLedger(self.path)
        self.request=build_verifier_request(EVENT)['write_request'];self.calls=0
    def tearDown(self): self.ledger.close();self.tmp.cleanup()
    def writer(self, plan): self.calls+=1;return {'status':'SUCCESS','fulfilment_id':'gid://shopify/Fulfillment/1'}
    def reader(self, result): return {**self.request['expected_result'],'source':'FRESH_SHOPIFY_READ','status':'SUCCESS'}
    def test_verified_redelivery_never_writes_again(self):
        self.assertEqual(execute_shipment(self.request,CONTEXT,self.ledger,self.writer,self.reader)['status'],'VERIFIED')
        self.assertEqual(execute_shipment(self.request,{},self.ledger,self.writer,self.reader)['status'],'DUPLICATE_NOOP');self.assertEqual(self.calls,1)
    def test_timeout_and_restart_require_reconciliation(self):
        def timeout(plan):self.calls+=1;raise TimeoutError('unknown remote result')
        self.assertEqual(execute_shipment(self.request,CONTEXT,self.ledger,timeout,self.reader)['status'],'REVIEW_REQUIRED')
        self.ledger.close();self.ledger=ShipmentLedger(self.path)
        self.assertEqual(execute_shipment(self.request,CONTEXT,self.ledger,self.writer,self.reader)['status'],'REVIEW_REQUIRED');self.assertEqual(self.calls,1)
    def test_second_connection_cannot_claim_inflight_key(self):
        key=self.request['idempotency_key'];self.assertEqual(self.ledger.claim(key,self.request),'CLAIMED')
        other=ShipmentLedger(self.path)
        try:self.assertEqual(other.claim(key,self.request),'REVIEW_REQUIRED')
        finally:other.close()
    def test_failed_fresh_audit_blocks_redelivery(self):
        def wrong(result):return {**self.reader(result),'tracking_info':{'company':'Australia Post','number':'WRONG'}}
        self.assertEqual(execute_shipment(self.request,CONTEXT,self.ledger,self.writer,wrong)['status'],'REVIEW_REQUIRED')
        self.assertEqual(execute_shipment(self.request,CONTEXT,self.ledger,self.writer,self.reader)['status'],'REVIEW_REQUIRED');self.assertEqual(self.calls,1)
if __name__=='__main__':unittest.main()
