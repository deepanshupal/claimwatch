import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkDomain, checkProfile, parseName } from './checks.mjs';
const source = (status, data) => async url => url.includes('dns.json') ? ({status:200,json:async()=>({services:[[ ['com'], ['https://registry.example/'] ]]})}) : ({ status, json: async () => data });
for (const status of [404, 403, 429, 500, 503]) {
  test(`domain HTTP ${status} does not prove availability`, async () => assert.equal((await checkDomain('reserved', '.com', source(status, {}))).status, 'unknown'));
}
for (const data of [{}, [], null, { errorCode: 404 }, {objectClassName: 'domain', ldhName: 'other.com'}]) {
  test(`domain invalid payload ${JSON.stringify(data)}`, async () => assert.equal((await checkDomain('example', '.com', source(200, data))).status, 'unknown'));
}
test('domain matching record', async () => assert.equal((await checkDomain('example', '.com', source(200, {objectClassName:'domain',ldhName:'EXAMPLE.COM.'}))).status,'taken'));
test('domain request failure', async () => assert.equal((await checkDomain('example','.com',async()=>{throw Error('blocked')})).status,'unknown'));
test('domain underscore never queries', async () => assert.equal((await checkDomain('a_b','.com',async()=>assert.fail('queried'))).status,'unknown'));
for (const [platform, name] of [['instagram','analoghouse'],['x','agentcommerce']]) {
  test(`${platform} ${name} never infers available from HTML`, async () => assert.equal((await checkProfile(platform,name,async()=>assert.fail('unverifiable HTML queried'))).status,'unknown'));
}
for (const platform of ['github','npm','pypi','dockerhub']) {
  for (const status of [404,429]) test(`${platform} ${status}`,async()=>assert.equal((await checkProfile(platform,'reserved',source(status,{}))).status,'unknown'));
  test(`${platform} empty record`,async()=>assert.equal((await checkProfile(platform,'reserved',source(200,{}))).status,'unknown'));
}
test('github matching record',async()=>assert.equal((await checkProfile('github','octocat',source(200,{id:583231,login:'octocat'}))).status,'taken'));
test('github wrong identity',async()=>assert.equal((await checkProfile('github','octocat',source(200,{id:1,login:'other'}))).status,'unknown'));
for (const value of ['Analog House','agent.com','a/b','', 'x'.repeat(64),'-bad']) test(`no silent input rewriting ${value}`,()=>assert.throws(()=>parseName(value)));
test('name parse',()=>assert.equal(parseName(' @AgentCommerce '),'agentcommerce'));
test('redirect protection and timeout signal',async()=>{
  await checkDomain('example','.com',async(url,options)=>{assert.equal(options.redirect,'error');assert.ok(options.signal instanceof AbortSignal);return url.includes('dns.json') ? {status:200,json:async()=>({services:[[['com'],['https://registry.example/']]]})} : {status:200,json:async()=>({objectClassName:'domain',ldhName:'example.com'})};});
});

test('authoritative no record is not registered, not available',async()=>assert.equal((await checkDomain('reserved','.com',source(404,{errorCode:404}))).status,'not_registered'));
test('authoritative empty 404 is a protocol no-record answer',async()=>assert.equal((await checkDomain('reserved','.com',async url=>url.includes('dns.json') ? {status:200,json:async()=>({services:[[['com'],['https://registry.example/']]]})} : {status:404,text:async()=>''})).status,'not_registered'));
test('response body timeout also settles',async()=>{
  const original=globalThis.setTimeout;
  globalThis.setTimeout=(fn)=>original(fn,10);
  try { assert.equal((await checkProfile('github','octocat',async()=>({status:200,json:()=>new Promise(()=>{})}))).status,'unknown'); }
  finally { globalThis.setTimeout=original; }
});
test('contradictory error is not taken',async()=>assert.equal((await checkProfile('github','octocat',source(200,{id:1,login:'octocat',error:'denied'}))).status,'unknown'));
test('bootstrap malformed endpoints stay unknown',async()=>assert.equal((await checkDomain('example','.com',async()=>({status:200,json:async()=>({services:[[['com'],'https://registry.example/']]})}))).status,'unknown'));
