#!/usr/bin/env python3
"""Existing-adapter shipment runner. Default is read-only preflight."""
import argparse
import json
import os
from pathlib import Path
from shipment_boundary import execute_shipment
from shipment_ledger import ShipmentLedger
from shipping_fulfilment import build_verifier_request
from verification_route import fulfilment_handoff
from fulfilment_write_plan import build_fulfilment_write_plan
import shopify_fulfilment_api as api

AUTH_ENV_KEYS={'SHOPIFY_STORE','SHOPIFY_STORE_DOMAIN','SHOPIFY_CLIENT_ID','SHOPIFY_CLIENT_SECRET','SHOPIFY_API_KEY','SHOPIFY_API_SECRET','SHOPIFY_API_VERSION'}
def load_auth_environment(path):
    # Read existing auth only. A file cannot implicitly turn on mutation gates.
    for raw in Path(path).read_text().splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        key,value=line.split('=',1);key=key.strip();value=value.strip()
        if key in AUTH_ENV_KEYS:
            if len(value)>=2 and value[0]==value[-1] and value[0]in {'"',"\'"}:value=value[1:-1]
            os.environ.setdefault(key,value)

def fresh_order(order_id):
    response=api.graphql_request(api.SHIPPING_STATE_QUERY,{'id':order_id})
    if not response['ok']:raise ValueError('fresh shipping state unavailable')
    order=(response.get('data')or{}).get('order')
    if not isinstance(order,dict)or order.get('id')!=order_id:raise ValueError('exact order unavailable')
    groups=order.get('fulfillmentOrders',{})
    if groups.get('pageInfo',{}).get('hasNextPage')is not False:raise ValueError('incomplete fulfillment orders')
    for group in groups.get('nodes',[]):
        if group.get('lineItems',{}).get('pageInfo',{}).get('hasNextPage')is not False:raise ValueError('incomplete exact lines')
    return order

def context_from_order(order, capability):
    return {'source':'FRESH_SHOPIFY_READ','order_id':order['id'],'duplicate_completed':False,'prior_result_indeterminate':False,
      'adapter_capability_verified':capability,'fulfilment_orders':{g['id']:{'order_id':order['id'],'status':g['status'],'remaining_lines':{x['id']:x['remainingQuantity']for x in g['lineItems']['nodes']}}for g in order['fulfillmentOrders']['nodes']}}

def normalize_created_fulfilment(before,after,request,writer_result):
    expected=request['expected_result'];groups=request['authorised_changes'][0]['fulfilment_orders']
    match=[f for f in after.get('fulfillments',[])if f['id']==writer_result.get('fulfilment_id')]
    if len(match)!=1:raise ValueError('exact created fulfillment unavailable')
    f=match[0];actual_lines=f.get('fulfillmentLineItems',{}).get('nodes',[])
    if len(actual_lines)>=250:raise ValueError('possibly truncated fulfillment lines')
    before_groups={g['id']:g for g in before['fulfillmentOrders']['nodes']};after_groups={g['id']:g for g in after['fulfillmentOrders']['nodes']}
    order_lines={};fulfilled=[]
    for group in groups:
        b={x['id']:x for x in before_groups[group['fulfilment_order_id']]['lineItems']['nodes']}
        a={x['id']:x for x in after_groups[group['fulfilment_order_id']]['lineItems']['nodes']}
        for line in group['line_items']:
            lid=line['fulfilment_order_line_item_id'];qty=line['quantity'];order_line=b[lid]['lineItem']['id']
            if order_line in order_lines or b[lid]['remainingQuantity']-a[lid]['remainingQuantity']!=qty:raise ValueError('exact fulfillment quantity effect mismatch')
            order_lines[order_line]=(lid,qty)
    seen=set()
    for line in actual_lines:
        order_line=line['lineItem']['id']
        if order_line in seen or order_line not in order_lines or line['quantity']!=order_lines[order_line][1]:raise ValueError('created fulfillment has unexpected lines')
        seen.add(order_line);fulfilled.append({'fulfilment_order_line_item_id':order_lines[order_line][0],'quantity':line['quantity']})
    if seen!=set(order_lines):raise ValueError('created fulfillment missing exact lines')
    tracking=f.get('trackingInfo',[])
    actual_tracking={k:tracking[0].get(k)for k in ['company','number']}if len(tracking)==1 else None
    return {'source':'FRESH_SHOPIFY_READ','order_id':after['id'],'status':f['status'],'fulfilled_lines':fulfilled,'tracking_info':actual_tracking}

def run(event,ledger_path,execute=False):
    built=build_verifier_request(event)
    if built['status']!='READY':return built
    if event['notify_customer']:return {'status':'REVIEW_REQUIRED','problems':['customer notifications require separate explicit authority']}
    request=built['write_request'];ledger=None
    try:
        if execute:
            ledger=ShipmentLedger(ledger_path);prior=ledger.prior_status(request['idempotency_key'])
            if prior:return {'status':prior,'idempotency_key':request['idempotency_key']}
        capability=api.probe_capabilities(live=True)
        before=fresh_order(event['order_id']);context=context_from_order(before,capability['fulfilment_create_adapter_verified'])
        if not execute:
            handoff=fulfilment_handoff(request,context)
            plan=build_fulfilment_write_plan(handoff['writer_input'])if handoff['status']=='READY'else handoff
            return {**plan,'idempotency_key':request['idempotency_key'],'mode':'read-only'}
        return execute_shipment(request,context,ledger,lambda plan:api.create_fulfilment(plan,execute=True),lambda result:normalize_created_fulfilment(before,fresh_order(event['order_id']),request,result))
    except Exception as error:return {'status':'REVIEW_REQUIRED','problems':[type(error).__name__]}
    finally:
        if ledger:ledger.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env-file',required=True,type=Path);p.add_argument('--event',required=True,type=Path);p.add_argument('--ledger',required=True,type=Path);p.add_argument('--execute',action='store_true');a=p.parse_args()
    load_auth_environment(a.env_file)
    result=run(json.loads(a.event.read_text()),a.ledger,a.execute);print(json.dumps(result,indent=2,sort_keys=True))
    raise SystemExit(0 if result['status']in {'READY','VERIFIED','DUPLICATE_NOOP'}else 3)
