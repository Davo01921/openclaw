import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from catalogue_audit import audit,exception
V={'id':'gid://shopify/ProductVariant/1','title':'Default Title','sku':None,'barcode':None,'inventoryPolicy':'CONTINUE','inventoryQuantity':-1,'inventoryItem':{'tracked':True,'requiresShipping':True,'measurement':{'weight':{'value':1,'unit':'KILOGRAMS'}},'inventoryLevels':{'pageInfo':{'hasNextPage':False},'nodes':[{'location':{'id':'location'},'quantities':[{'name':'on_hand','quantity':-1}]}]}},'product':{'id':'gid://shopify/Product/1','title':'Dry food','status':'ACTIVE','productType':'Fish Food','tags':[],'category':{'fullName':'Animals & Pet Supplies > Fish Food'}}}
class AuditTests(unittest.TestCase):
 def test_retail_oversell_is_blocking_and_stock_never_guessed(self):
  r=audit({'variants':[copy.deepcopy(V)]});self.assertEqual(r['counts']['BLOCKING'],2);self.assertNotIn('new_quantity',str(r))
 def test_live_and_plants_are_excluded_from_bulk_policy_changes(self):
  for cat in ['Animals & Pet Supplies > Live Animals','Home & Garden > Plants']:
   v=copy.deepcopy(V);v['product']['category']['fullName']=cat;self.assertNotEqual(exception(v),None);self.assertFalse(any(x['kind']=='UNAUTHORISED_OVERSELL_POLICY'for x in audit({'variants':[v]})['findings']['BLOCKING']))
 def test_fertilizer_is_not_a_plant_exception(self):
  v=copy.deepcopy(V);v['product'].update(productType='Aquatic Plant Fertilizers',category={'fullName':'Fish Supplies > Aquatic Plant Fertilizers'});self.assertIsNone(exception(v))
 def test_variant_and_tag_preorder_exceptions_are_preserved(self):
  for title,tags in [('1L - Preorder',[]),('Default Title',['Preorder'])]:
   v=copy.deepcopy(V);v['title']=title;v['product']['tags']=tags;self.assertEqual(exception(v),'PREORDER');self.assertEqual(audit({'variants':[v]})['counts']['BLOCKING'],0)
 def test_truncated_and_duplicate_snapshot_fail(self):
  with self.assertRaises(ValueError):audit({'variants':[V,V]})
  v=copy.deepcopy(V);v['inventoryItem']['inventoryLevels']['pageInfo']['hasNextPage']=True
  with self.assertRaises(ValueError):audit({'variants':[v]})
 def test_sold_status_is_review_not_automatic_archive(self):
  v=copy.deepcopy(V);v['inventoryPolicy']='DENY';v['inventoryQuantity']=0;v['inventoryItem']['inventoryLevels']['nodes'][0]['quantities'][0]['quantity']=0;v['product']['title']='2BT14 - Betta';r=audit({'variants':[v]});self.assertEqual(r['counts']['BLOCKING'],0);self.assertEqual(r['findings']['IMPORTANT'][0]['kind'],'ZERO_STOCK_BETTA_STATUS_REVIEW')
 def test_net_heavy_weight_flags_zero_measurement_without_inventing_packed_weight(self):
  v=copy.deepcopy(V);v['product']['title']='Koi food 8kg';v['inventoryItem']['measurement']['weight']['value']=0;r=audit({'variants':[v]});self.assertTrue(any(x['kind']=='HEAVY_SHIPMENT_WITH_ZERO_WEIGHT'for x in r['findings']['BLOCKING']))
if __name__=='__main__':unittest.main()
