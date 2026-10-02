#!/usr/bin/env python3
"""Read-only catalogue integrity audit. Never proposes guessed stock quantities."""
import argparse
from collections import defaultdict
import json
import re
from pathlib import Path

PREORDER = re.compile(r'\bpre[ -]?order\b', re.I)
TANK = re.compile(r'^[1-9]\d*BT[1-9]\d*\b', re.I)
PLANT_TYPES = {'aquatic plants', 'bunch plants', 'house plants', 'plants'}

def exception(v):
    p=v['product'];category=(p.get('category') or {}).get('fullName','').lower()
    # Fertilizers are dry goods, not living-plant exceptions.
    if 'live animals' in category or 'live food' in category:return 'LIVESTOCK'
    if p.get('productType','').lower() in PLANT_TYPES or any(part.strip() == 'plants' for part in category.split('>')):return 'PLANTS'
    if any(PREORDER.search(str(x)) for x in [p['title'],v.get('title',''),*p.get('tags',[])]):return 'PREORDER'
    if not v.get('inventoryItem',{}).get('tracked') or not v.get('inventoryItem',{}).get('requiresShipping'):return 'UNTRACKED_OR_NONPHYSICAL'
    return None

def audit(snapshot, shipping_labels=None):
    variants=snapshot['variants'];ids=[v['id'] for v in variants]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate snapshot variant IDs')
    findings={'BLOCKING':[],'IMPORTANT':[],'COSMETIC_SEO':[]};active=[v for v in variants if v['product']['status']=='ACTIVE']
    def add(group,kind,v,**extra):findings[group].append({'kind':kind,'variant_id':v['id'],'product_id':v['product']['id'],'product':v['product']['title'],'variant':v.get('title'),**extra})
    for v in active:
        levels=v['inventoryItem']['inventoryLevels']
        if levels.get('pageInfo',{}).get('hasNextPage'):raise ValueError('truncated inventory levels')
        why=exception(v)
        if v['inventoryPolicy']=='CONTINUE' and why is None:add('BLOCKING','UNAUTHORISED_OVERSELL_POLICY',v,action='Verify exact variant then set DENY only; preserve stock.')
        negative=[{'location_id':l['location']['id'],'on_hand':q['quantity']}for l in levels['nodes'] for q in l['quantities'] if q['name']=='on_hand' and q['quantity']<0]
        if negative:
            group='IMPORTANT' if why in {'PREORDER','UNTRACKED_OR_NONPHYSICAL'} else 'BLOCKING'
            add(group,'NEGATIVE_PHYSICAL_BALANCE',v,balances=negative,exception=why,action='Reconcile physical count, committed orders and ledger; never reset to zero.')
        if TANK.match(v['product']['title']) and v['inventoryQuantity']==0:add('IMPORTANT','ZERO_STOCK_BETTA_STATUS_REVIEW',v,action='Confirm sold/current fish identity before separately authorized archiving. DENY protects checkout.')
        # A title's net weight is a lower bound, never an invented packed weight.
        kg=re.search(r'\b(\d+(?:\.\d+)?)\s*kg\b',v['product']['title']+' '+v.get('title',''),re.I)
        weight=v['inventoryItem'].get('measurement',{}).get('weight',{})
        if kg and float(kg.group(1))>5 and weight.get('value')==0 and 'pickup' not in (v.get('title') or '').lower():
            add('BLOCKING','HEAVY_SHIPMENT_WITH_ZERO_WEIGHT',v,net_kg=float(kg.group(1)),shipping_label=(shipping_labels or {}).get(v['id'].split('/')[-1]),action='Measure packed weight and verify ShipWeave heavy routing; do not guess stock or postage.')
    for field in ['sku','barcode']:
        groups=defaultdict(list)
        for v in active:
            key=(v.get(field) or '').strip()
            if key:groups[key].append(v)
        for value,group in groups.items():
            if len(group)>1:
                findings['IMPORTANT'].append({'kind':'DUPLICATE_'+field.upper(),'value':value,'variant_ids':[v['id']for v in group],'products':[v['product']['title']for v in group], 'action':'Supplier/operator identity review; do not merge or invent a code.'})
    return {'checked_at':snapshot.get('checkedAt'),'products':len({v['product']['id']for v in variants}),'variants':len(variants),'active_variants':len(active),'policy_exceptions':{v['id']:exception(v)for v in active if v['inventoryPolicy']=='CONTINUE'},'counts':{k:len(v)for k,v in findings.items()},'findings':findings,'limitations':['No quantity changes or inferred physical counts.','Empty SKUs/barcodes need a documented operating requirement before blocking closure.','Negative preorder/nonphysical balances require accounting review, not automatic stock correction.','Zero-stock active Bettas are review candidates, not proof of a sold fish.','Shipping rule snapshot is not a live ShipWeave connection.']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('snapshot',type=Path);p.add_argument('--shipping-rules',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    rules=json.loads(a.shipping_rules.read_text()).get('labelsByVariant',{}) if a.shipping_rules else {}
    report=audit(json.loads(a.snapshot.read_text()),rules)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n');a.output.chmod(0o600)
    print(json.dumps({k:report[k]for k in ['products','variants','active_variants','counts']}))
