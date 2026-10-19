/** Private Google Apps Script dispatcher. No credentials belong in this file.
 * Script properties: GITHUB_TOKEN; optional HC_PING_URL and HC_API_KEY.
 * The token is repository-scoped: Actions write, Contents read, Issues write.
 * The actual stock checks still run against the official theatre sources in
 * GitHub Actions, including the normal Chrome confirmation for Golden Boy.
 */
const REPOSITORY = 'Scr169/eurotrash-ticket-watch';
const WORKFLOW = 'watch.yml';
const ENDS_AT = '2027-01-10T00:00:00Z';
const MAX_AGE_MS = 15 * 60 * 1000;
const FEEDS = [
  {name:'Young Vic《Eurotrash》', path:'monitor-state.json', end:ENDS_AT},
  {name:'Almeida《Golden Boy》', path:'golden-boy-state.json', end:'2026-11-01T00:00:00Z'}
];

function setup() {
  github_('/actions/workflows/' + WORKFLOW);
  const props = PropertiesService.getScriptProperties();
  props.setProperty('installed_at', new Date().toISOString());
  // Replace only the two triggers owned by this application.
  removeTriggers_();
  ScriptApp.newTrigger('dispatchChecks').timeBased().everyMinutes(5).create();
  ScriptApp.newTrigger('watchdog').timeBased().everyMinutes(5).create();
  dispatchChecks();
  console.log('Installed independent five-minute dispatch and watchdog triggers.');
}

function dispatchChecks() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  const props = PropertiesService.getScriptProperties();
  const now = new Date();
  try {
    if (now >= new Date(ENDS_AT)) { finish_(); return; }
    github_('/actions/workflows/' + WORKFLOW + '/dispatches', 'post', {ref:'main'});
    props.setProperties({last_dispatch_at:now.toISOString(), last_dispatch_error:'none'});
    const history = JSON.parse(props.getProperty('dispatch_history') || '[]');
    history.push(now.toISOString());
    props.setProperty('dispatch_history', JSON.stringify(history.slice(-100)));
    console.log(JSON.stringify({dispatch_accepted_at:now.toISOString(), stock_check_not_yet_confirmed:true}));
  } catch (error) {
    props.setProperty('last_dispatch_error', String(error).slice(0,400));
    // Do not send a success heartbeat. The external dead-man check will alert
    // even if the API credential cannot create a GitHub failure issue.
    throw error;
  } finally {
    lock.releaseLock();
  }
}

function watchdog() {
  const now = new Date();
  if (now >= new Date(ENDS_AT)) { finish_(); return; }
  const props = PropertiesService.getScriptProperties();
  const report = [];
  const stale = [];
  let fullyHealthy = true;
  for (const feed of FEEDS.filter(x => now < new Date(x.end))) {
    const file = github_('/contents/' + feed.path + '?ref=main');
    const state = JSON.parse(Utilities.newBlob(Utilities.base64Decode(file.content)).getDataAsString('UTF-8'));
    const checked = Date.parse(state.last_checked_at || '');
    const attempted = Date.parse(state.last_attempt_at || '');
    report.push({name:feed.name, status:state.status, last_checked_at:state.last_checked_at || null,
      last_attempt_at:state.last_attempt_at || null, run_id:state.last_run_id || null});
    if (!Number.isFinite(attempted) || now.getTime() - attempted > MAX_AGE_MS) stale.push(feed.name);
    if (!Number.isFinite(checked) || now.getTime() - checked > MAX_AGE_MS || !['sold_out','available'].includes(state.status)) fullyHealthy = false;
  }
  props.setProperty('last_watchdog_at', now.toISOString());
  props.setProperty('last_stock_report', JSON.stringify(report));
  console.log(JSON.stringify({watchdog_at:now.toISOString(), fully_healthy:fullyHealthy, feeds:report}));
  const installed = Date.parse(props.getProperty('installed_at') || '');
  if (stale.length && now.getTime() - installed > MAX_AGE_MS && !props.getProperty('stale_notice_sent')) {
    const episode = Number(props.getProperty('stale_episode') || 0) + 1;
    notify_('【监控停跑，不是放票】两场戏查票超过15分钟未执行',
      '以下剧目已超过15分钟没有实际检查记录：' + stale.join('、') + '\n\n这不代表售罄，也不是放票通知。请暂时自行查看官网。\n\nhttps://github.com/' + REPOSITORY + '/actions',
      'scheduler-stale-' + episode);
    props.setProperties({stale_notice_sent:'true',stale_episode:String(episode)});
  } else if (!stale.length && props.getProperty('stale_notice_sent')) {
    notify_('【监控恢复】两场戏云端检查已恢复', '已重新核对两场戏的实际检查时间。\n\nhttps://github.com/' + REPOSITORY + '/actions',
      'scheduler-recovered-' + props.getProperty('stale_episode'));
    props.deleteProperty('stale_notice_sent');
  }
  // Ping only after actual successful stock reads, never after merely queueing
  // a workflow. Missing Google triggers, GitHub runs, or source reads all stop
  // these pings; Healthchecks sends the independent email alert.
  const previous = JSON.parse(props.getProperty('last_health_sources') || '{}');
  // Never keep a stopped checker looking alive by repeatedly pinging the same
  // old successful result. Every active production must have a NEW success.
  if (fullyHealthy && report.every(r=>r.last_checked_at && r.last_checked_at !== previous[r.name])) {
    pingHealth_();
    props.setProperty('last_health_sources',JSON.stringify(Object.fromEntries(report.map(r=>[r.name,r.last_checked_at]))));
  }
}

function showStatus() {
  const props = PropertiesService.getScriptProperties();
  console.log(JSON.stringify({
    installed_at:props.getProperty('installed_at'),
    last_dispatch_at:props.getProperty('last_dispatch_at'),
    last_watchdog_at:props.getProperty('last_watchdog_at'),
    dispatch_history:JSON.parse(props.getProperty('dispatch_history') || '[]'),
    feeds:JSON.parse(props.getProperty('last_stock_report') || '[]'),
    trigger_functions:ScriptApp.getProjectTriggers().map(t=>t.getHandlerFunction()),
    external_deadman_configured:Boolean(props.getProperty('HC_PING_URL')),
    last_health_ping_at:props.getProperty('last_health_ping_at'),
    deadman_test_started_at:props.getProperty('deadman_test_started_at'),
    deadman_test_passed_at:props.getProperty('deadman_test_passed_at')
  }));
}

function github_(path, method, body) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Missing private GITHUB_TOKEN script property');
  const options = {method:method || 'get', muteHttpExceptions:true,
    headers:{Authorization:'Bearer ' + token, Accept:'application/vnd.github+json',
      'X-GitHub-Api-Version':'2022-11-28','Cache-Control':'no-cache'}};
  if (body !== undefined) { options.contentType='application/json'; options.payload=JSON.stringify(body); }
  const response = UrlFetchApp.fetch('https://api.github.com/repos/' + REPOSITORY + path, options);
  const code = response.getResponseCode();
  if (code < 200 || code >= 300) throw new Error('GitHub ' + (method || 'get') + ' ' + path.split('?')[0] + ': HTTP ' + code);
  return response.getContentText() ? JSON.parse(response.getContentText()) : null;
}

function notify_(title, body, marker) {
  const issues = github_('/issues?state=all&per_page=100&sort=created&direction=desc');
  if (issues.some(i=>(i.body || '').includes('<!-- ' + marker + ' -->'))) return;
  const result = github_('/issues','post',{title:title,body:'@Scr169\n\n' + body + '\n\n<!-- ' + marker + ' -->'});
  if (!result || !result.id) throw new Error('GitHub did not acknowledge watchdog alert');
}

function pingHealth_() {
  const ping = PropertiesService.getScriptProperties().getProperty('HC_PING_URL');
  if (!ping) return;
  if (!/^https:\/\/hc-ping\.com\/[a-f0-9-]{36}$/.test(ping)) throw new Error('Invalid private healthcheck URL');
  const response = UrlFetchApp.fetch(ping,{method:'post',payload:'Both active official stock checks are fresh.',muteHttpExceptions:true});
  if (response.getResponseCode() !== 200) throw new Error('External healthcheck heartbeat failed');
  PropertiesService.getScriptProperties().setProperty('last_health_ping_at',new Date().toISOString());
}

function finish_() {
  const props = PropertiesService.getScriptProperties();
  const ping = props.getProperty('HC_PING_URL');
  const key = props.getProperty('HC_API_KEY');
  if (ping && key && !props.getProperty('healthcheck_paused')) {
    const uuid = ping.split('/').pop();
    if (!/^[a-f0-9-]{36}$/.test(uuid)) throw new Error('Invalid healthcheck ID');
    const response = UrlFetchApp.fetch('https://healthchecks.io/api/v3/checks/' + uuid + '/pause',
      {method:'post',headers:{'X-Api-Key':key},muteHttpExceptions:true});
    if (response.getResponseCode() !== 200) throw new Error('Could not pause finished monitor healthcheck');
    props.setProperty('healthcheck_paused','true');
  }
  if (ping && !props.getProperty('healthcheck_paused')) throw new Error('Healthcheck requires pause before monitor retirement');
  removeTriggers_();
  props.setProperty('finished_at',new Date().toISOString());
}

function removeTriggers_() {
  for (const trigger of ScriptApp.getProjectTriggers()) {
    if (['dispatchChecks','watchdog'].includes(trigger.getHandlerFunction())) ScriptApp.deleteTrigger(trigger);
  }
}

function testDeadmanAlarm() {
  const props = PropertiesService.getScriptProperties();
  if (props.getProperty('deadman_test_uuid')) throw new Error('Test already created; inspect its email before finishing it.');
  const check = healthApi_('/checks/', 'post', {
    name:'【测试，不是放票】查票停跑报警演练', slug:'ticket-monitor-deadman-test',
    desc:'这是独立告警链路测试；不代表正式查票停止，也不是放票。测试会主动停止一次心跳，验证超时邮件。',
    timeout:60,grace:60,channels:'*',tags:'ticket-monitor-test'
  });
  if (!check.ping_url || !check.uuid) throw new Error('Healthchecks did not acknowledge test creation');
  const response = UrlFetchApp.fetch(check.ping_url,{method:'post',payload:'Start clearly labelled dead-man notification test.',muteHttpExceptions:true});
  if (response.getResponseCode() !== 200) throw new Error('Could not start dead-man test');
  props.setProperties({deadman_test_uuid:check.uuid,deadman_test_started_at:new Date().toISOString()});
  console.log('Separate test heartbeat started, then intentionally left to expire after two minutes. Production checks continue.');
}

function finishDeadmanTest() {
  const props = PropertiesService.getScriptProperties();
  const uuid = props.getProperty('deadman_test_uuid');
  if (!uuid) throw new Error('No dead-man test exists');
  const check = healthApi_('/checks/' + uuid);
  if (check.status !== 'down') throw new Error('Test is not yet down; do not claim the timeout alarm was verified.');
  healthApi_('/checks/' + uuid + '/pause','post');
  props.setProperty('deadman_test_passed_at',new Date().toISOString());
  console.log('Verified test reached DOWN; test check is now paused. Verify the actual alert email separately.');
}

function healthApi_(path,method,body) {
  const key = PropertiesService.getScriptProperties().getProperty('HC_API_KEY');
  if (!key) throw new Error('Missing private HC_API_KEY');
  const options = {method:method || 'get',headers:{'X-Api-Key':key},muteHttpExceptions:true};
  if (body !== undefined) {options.contentType='application/json';options.payload=JSON.stringify(body);}
  const response=UrlFetchApp.fetch('https://healthchecks.io/api/v3' + path,options);
  if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) throw new Error('Healthcheck management request failed: HTTP ' + response.getResponseCode());
  return JSON.parse(response.getContentText());
}
