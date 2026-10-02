import copy,sys,unittest,os,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from run_shipment import normalize_created_fulfilment,load_auth_environment
from test_handoff import EVENT
from shipping_fulfilment import build_verifier_request
class LiveNormalizationTests(unittest.TestCase):
 def setUp(self):
  self.req=build_verifier_request(EVENT)['write_request'];g=EVENT['fulfilment_orders'][0];lid=g['line_items'][0]['fulfilment_order_line_item_id'];self.before={'id':EVENT['order_id'],'fulfillmentOrders':{'nodes':[{'id':g['fulfilment_order_id'],'lineItems':{'nodes':[{'id':lid,'remainingQuantity':2,'lineItem':{'id':'order-line'}}]}}]}};self.after=copy.deepcopy(self.before);self.after['fulfillmentOrders']['nodes'][0]['lineItems']['nodes'][0]['remainingQuantity']=0;self.after['fulfillments']=[{'id':'fulfillment','status':'SUCCESS','trackingInfo':[{'company':'Australia Post','number':'ABC123'}],'fulfillmentLineItems':{'nodes':[{'quantity':2,'lineItem':{'id':'order-line'}}]}}]
 def test_exact_created_id_and_effect_normalize(self):
  a=normalize_created_fulfilment(self.before,self.after,self.req,{'fulfilment_id':'fulfillment'});self.assertEqual(a['tracking_info'],{'company':'Australia Post','number':'ABC123'});self.assertEqual(a['fulfilled_lines'],self.req['expected_result']['fulfilled_lines'])
 def test_other_fulfillment_and_extra_lines_cannot_prove_success(self):
  with self.assertRaises(ValueError):normalize_created_fulfilment(self.before,self.after,self.req,{'fulfilment_id':'OTHER'})
  self.after['fulfillments'][0]['fulfillmentLineItems']['nodes'].append({'quantity':1,'lineItem':{'id':'extra'}})
  with self.assertRaises(ValueError):normalize_created_fulfilment(self.before,self.after,self.req,{'fulfilment_id':'fulfillment'})
 def test_wrong_remaining_effect_holds_result(self):
  self.after['fulfillmentOrders']['nodes'][0]['lineItems']['nodes'][0]['remainingQuantity']=1
  with self.assertRaises(ValueError):normalize_created_fulfilment(self.before,self.after,self.req,{'fulfilment_id':'fulfillment'})
 def test_auth_file_cannot_turn_on_write_gate(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory()as tmp,patch.dict(os.environ,{},clear=True):
   p=Path(tmp)/'env';p.write_text('SHOPIFY_CLIENT_ID=dummy\nNTA_SHOPIFY_FULFILMENT_WRITE_ENABLED=true\n')
   load_auth_environment(p);self.assertEqual(os.environ.get('SHOPIFY_CLIENT_ID'),'dummy');self.assertNotIn('NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED',os.environ)
if __name__=='__main__':unittest.main()
