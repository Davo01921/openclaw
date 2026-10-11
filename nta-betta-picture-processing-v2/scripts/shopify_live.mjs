#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const API_VERSION = process.env.BETTA_SHOPIFY_API_VERSION || '2026-07';
const ENV_FILE = process.env.BETTA_SHOPIFY_ENV || path.join(process.env.HOME || '',
  '.openclaw/workspace/nta-betta-picture-processor/.env');
function fail(message, code=2) {
  process.stderr.write(JSON.stringify({ok:false,error:message})+'\n'); process.exit(code);
}
function loadEnv(file) {
  if (!fs.existsSync(file)) fail('Shopify credential file unavailable');
  for (const raw of fs.readFileSync(file,'utf8').split(/\r?\n/)) {
    const line=raw.trim(); if (!line || line.startsWith('#')) continue;
    const i=line.indexOf('='); if (i<1) continue;
    const key=line.slice(0,i).trim(), value=line.slice(i+1).trim().replace(/^['"]|['"]$/g,'');
    if (!process.env[key]) process.env[key]=value;
  }
}
async function client() {
  loadEnv(ENV_FILE);
  const {SHOPIFY_STORE,SHOPIFY_CLIENT_ID,SHOPIFY_CLIENT_SECRET}=process.env;
  if (!SHOPIFY_STORE||!SHOPIFY_CLIENT_ID||!SHOPIFY_CLIENT_SECRET) fail('Shopify credentials incomplete');
  const auth=await fetch(`https://${SHOPIFY_STORE}/admin/oauth/access_token`,{
    method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({grant_type:'client_credentials',client_id:SHOPIFY_CLIENT_ID,
      client_secret:SHOPIFY_CLIENT_SECRET})});
  const body=await auth.json().catch(()=>({}));
  if (!auth.ok||!body.access_token) fail(`Shopify authentication failed (${auth.status})`);
  return async(query,variables={})=>{
    const response=await fetch(`https://${SHOPIFY_STORE}/admin/api/${API_VERSION}/graphql.json`,{
      method:'POST',headers:{'content-type':'application/json','x-shopify-access-token':body.access_token},
      body:JSON.stringify({query,variables})});
    const envelope=await response.json().catch(()=>({}));
    if (!response.ok) fail(`Shopify transport failed (${response.status})`);
    if (envelope.errors?.length) fail(`Shopify GraphQL error: ${JSON.stringify(envelope.errors)}`);
    if (!envelope.data) fail('Shopify response missing data');
    return envelope.data;
  };
}
const RESOLVE=`query BettaResolve($query:String!){products(first:10,query:$query){pageInfo{hasNextPage} nodes{
 id title descriptionHtml handle status vendor productType
 media(first:50){pageInfo{hasNextPage} nodes{id alt mediaContentType status ... on MediaImage{image{url width height}}}}
 variants(first:10){pageInfo{hasNextPage} nodes{id title price inventoryPolicy inventoryQuantity inventoryItem{
  id tracked unitCost{amount currencyCode} inventoryLevels(first:20){pageInfo{hasNextPage} nodes{
   id location{id name} quantities(names:["available","on_hand","committed"]){name quantity}}}}}}
 arrival:metafield(namespace:"custom",key:"arrival_date"){id value type}}}}`;
function exactTank(product,tank) {
  const escaped=tank.replace(/[.*+?^{}()|[\]\\]/g,'\\$&');
  return new RegExp(`(^|[^A-Z0-9])${escaped}([^A-Z0-9]|$)`,'i').test(product.title||'')||
    (product.handle||'').toLowerCase()===tank.toLowerCase();
}
function snapshot(product,tank) {
  if(product.status!=='ACTIVE') fail('Resolved Betta product is not ACTIVE');
  if(product.variants.pageInfo?.hasNextPage!==false || product.variants.nodes.length!==1) fail('Resolved product must have exactly one variant');
  const variant=product.variants.nodes[0], levels=variant.inventoryItem?.inventoryLevels?.nodes||[];
  if(variant.inventoryItem.inventoryLevels.pageInfo?.hasNextPage!==false || levels.length!==1) fail('Resolved variant must have exactly one inventory location');
  const level=levels[0], available=level.quantities?.find(x=>x.name==='available')?.quantity;
  const onHand=level.quantities?.find(x=>x.name==='on_hand')?.quantity;
  const committed=level.quantities?.find(x=>x.name==='committed')?.quantity;
  if(product.media.pageInfo?.hasNextPage!==false) fail('Resolved media truncated');
  if(![available,onHand,committed].every(Number.isInteger)) fail('Resolved inventory quantities unavailable');
  return {id:product.id,variant_id:variant.id,inventory_item_id:variant.inventoryItem.id,
    raw_product:product,location:level.location,location_id:level.location.id,source:'FRESH_SHOPIFY_READ',tank_id:tank,
    fetched_at:new Date().toISOString(),fetch_id:crypto.randomUUID(),query:tank,before:{
      title:product.title,description:product.descriptionHtml,price:variant.price,
      cost:variant.inventoryItem.unitCost?.amount??null,vendor:product.vendor,
      product_type:product.productType,handle:product.handle,status:product.status,
      inventory:available,on_hand:onHand,committed,inventory_policy:variant.inventoryPolicy,tracked:variant.inventoryItem.tracked,
      arrival_date:product.arrival?.value??null,media:(product.media?.nodes||[]).map(m=>({
        id:m.id,alt:m.alt,status:m.status,url:m.image?.url,width:m.image?.width,height:m.image?.height}))}};
}
async function main(){
  const [command,tank]=process.argv.slice(2);
  if(!['preflight','resolve'].includes(command)) fail('usage: shopify_live.mjs preflight|resolve [TANK]');
  const gql=await client();
  if(command==='preflight'){
    const data=await gql('query BettaPreflight{shop{id name myshopifyDomain currencyCode}}');
    const expected=process.env.BETTA_EXPECTED_SHOP || process.env.SHOPIFY_STORE;
    if(!expected || data.shop?.myshopifyDomain!==expected) fail('Shopify shop identity mismatch');
    console.log(JSON.stringify({ok:true,shop:data.shop,api_version:API_VERSION,capabilities:['authenticate','fresh_resolve']}));
    return;
  }
  if(!/^\d+BT\d+$/.test(tank||'')) fail('canonical tank ID required');
  const data=await gql(RESOLVE,{query:tank});
  if(data.products?.pageInfo?.hasNextPage!==false) fail('Product resolution truncated');
  const matches=(data.products?.nodes||[]).filter(p=>exactTank(p,tank));
  if(matches.length!==1) fail(`Expected exactly one product for ${tank}; found ${matches.length}`);
  console.log(JSON.stringify({ok:true,status:'RESOLVED',snapshot:snapshot(matches[0],tank)}));
}
main().catch(error=>fail(error?.message||String(error)));
