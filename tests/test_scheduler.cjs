const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync(require('node:path').join(__dirname,'../cloud-scheduler.gs'),'utf8');
const NOW = '2026-10-19T14:00:00Z';

function fixture(states, dispatchCode=204) {
  const data = {GITHUB_TOKEN:'fixture',HC_PING_URL:'https://hc-ping.com/00000000-0000-0000-0000-000000000000',installed_at:'2026-10-19T13:00:00Z'};
  const calls = [];
  const response = (value,status=200)=>({getResponseCode:()=>status,getContentText:()=>value === null ? '' : JSON.stringify(value)});
  class Clock extends Date {constructor(...args){super(...(args.length?args:[NOW]));}}
  const context = vm.createContext({Date:Clock,console:{log:()=>{}},
    PropertiesService:{getScriptProperties:()=>({getProperty:k=>data[k] ?? null,setProperty:(k,v)=>{data[k]=v;},setProperties:o=>Object.assign(data,o),deleteProperty:k=>delete data[k]})},
    LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})},
    Utilities:{base64Decode:s=>Buffer.from(s,'base64'),newBlob:b=>({getDataAsString:()=>b.toString()})},
    UrlFetchApp:{fetch:(url,options)=>{
      calls.push({url,options});
      if(url.includes('/dispatches')) return response(null,dispatchCode);
      if(url.includes('/contents/')){
        const name=url.split('/contents/')[1].split('?')[0];
        return response({content:Buffer.from(JSON.stringify(states[name])).toString('base64')});
      }
      if(url.includes('/issues?')) return response([]);
      if(url.endsWith('/issues')) return response({id:1});
      if(url.startsWith('https://hc-ping.com/')) return response('OK');
      throw new Error('Unexpected fixture URL');
    }}
  });
  vm.runInContext(code,context);
  return {data,calls,run:name=>vm.runInContext(name+'()',context)};
}
const fresh = {status:'sold_out',last_attempt_at:'2026-10-19T13:59:00Z',last_checked_at:'2026-10-19T13:59:02Z'};
const feeds = golden=>({'monitor-state.json':fresh,'golden-boy-state.json':golden});

test('only actual fresh source reads for both productions produce a healthy heartbeat',()=>{
  const f=fixture(feeds(fresh)); f.run('watchdog'); f.run('watchdog');
  assert.equal(f.calls.filter(c=>c.url.startsWith('https://hc-ping.com/')).length,1);
});
test('one advancing checker cannot keep a stopped second production looking healthy',()=>{
  const states=feeds({...fresh});
  const f=fixture(states); f.run('watchdog');
  states['monitor-state.json']={...fresh,last_checked_at:'2026-10-19T14:00:00Z'};
  f.run('watchdog');
  assert.equal(f.calls.filter(c=>c.url.startsWith('https://hc-ping.com/')).length,1);
  states['golden-boy-state.json']={...fresh,last_checked_at:'2026-10-19T14:00:00Z'};
  f.run('watchdog');
  assert.equal(f.calls.filter(c=>c.url.startsWith('https://hc-ping.com/')).length,2);
});
test('accepting a queued workflow is never treated as a successful stock read',()=>{
  const f=fixture(feeds(fresh)); f.run('dispatchChecks');
  assert.ok(f.data.last_dispatch_at);
  assert.equal(f.calls.filter(c=>c.url.startsWith('https://hc-ping.com/')).length,0);
});
test('unknown source status suppresses heartbeat even with a recent older success',()=>{
  const f=fixture(feeds({...fresh,status:'unknown'})); f.run('watchdog');
  assert.equal(f.calls.filter(c=>c.url.startsWith('https://hc-ping.com/')).length,0);
});
test('a stopped checker suppresses heartbeat and alerts once until actual checks recover',()=>{
  const f=fixture(feeds({...fresh,last_attempt_at:'2026-10-19T13:00:00Z',last_checked_at:'2026-10-19T13:00:00Z'}));
  f.run('watchdog'); f.run('watchdog');
  assert.equal(f.calls.filter(c=>c.url.endsWith('/issues')).length,1);
  assert.equal(f.calls.filter(c=>c.url.startsWith('https://hc-ping.com/')).length,0);
  assert.equal(f.data.stale_notice_sent,'true');
});
test('dispatch failure remains a failure and never refreshes a healthy heartbeat',()=>{
  const f=fixture(feeds(fresh),403);
  assert.throws(()=>f.run('dispatchChecks'),/HTTP 403/);
  assert.equal(f.data.last_dispatch_at,undefined);
  assert.match(f.data.last_dispatch_error,/HTTP 403/);
  assert.equal(f.calls.filter(c=>c.url.startsWith('https://hc-ping.com/')).length,0);
});
