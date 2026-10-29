/* Admin settings UI: authenticated /api/settings and /api/admin/* routes.
 * Runtime JSON in /config is authoritative; edits currently require a restart
 * to affect Python collector globals. Ookla installation requires explicit
 * user acknowledgement; a browser never installs packages on its own.
 * CSRF header is attached to same-origin non-GET requests below.
 */
(()=>{'use strict';const $=id=>document.getElementById(id),csrf=document.querySelector('meta[name="netprobe-csrf"]').content;const oldFetch=window.fetch.bind(window);window.fetch=(url,opts={})=>{if(typeof url==='string'&&url.startsWith('/')&&opts.method&& !['GET','HEAD'].includes(opts.method.toUpperCase())) opts={...opts,headers:{...(opts.headers||{}),'X-NetProbe-CSRF':csrf}};return oldFetch(url,opts)};const ooklaStatus=$('npOoklaInstallStatus');const ooklaButton=$('npOoklaInstall');async function refreshOokla(){try{const r=await fetch('/api/admin/ookla');const d=await r.json();if(!r.ok)throw Error(d.error||'Status unavailable');ooklaStatus.textContent=(d.installed?'CLI installed':'CLI not installed')+' · '+(d.accepted?'Terms acknowledged':'Terms not acknowledged')+(d.running?' · installing…':'')+(d.message?' · '+d.message:'');ooklaButton.disabled=d.running||d.installed;if(d.running)setTimeout(refreshOokla,4000)}catch(e){ooklaStatus.textContent=e.message}}$('npOoklaRefresh').onclick=refreshOokla;ooklaButton.onclick=async()=>{if($('npOoklaConfirmation').value.trim().toUpperCase().replaceAll('_',' ')!=='I ACCEPT'){ooklaStatus.textContent='Enter exactly I ACCEPT to proceed.';return}ooklaButton.disabled=true;try{const r=await fetch('/api/admin/ookla',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:$('npOoklaConfirmation').value.trim().toUpperCase().replaceAll('_',' ')})});const d=await r.json();if(!r.ok)throw Error(d.error||'Install not started');await refreshOokla()}catch(e){ooklaStatus.textContent=e.message;ooklaButton.disabled=false}};async function checkSpeedtestBackend(){const out=$('npSpeedtestCheckResult');out.textContent='Checking local backends…';try{const r=await fetch('/api/admin/speedtest/check');const d=await r.json();if(!r.ok)throw Error(d.error||'Preflight failed');const chosen=d.selected_backend;out.textContent=[
'Configured backend: '+chosen,
'Running backend: '+d.current_runtime_backend,
'Ready: '+(d.ready?'YES':'NO'),
'Python speedtest-cli installed: '+(d.python.installed?'YES':'NO'),
'Python discovery: '+(d.python.secure?'HTTPS / secure':'HTTP / non-secure'),
'Official Ookla installed: '+(d.ookla.installed?'YES':'NO'),
'Official Ookla terms acknowledged: '+(d.ookla.accepted?'YES':'NO'),
'Server ID: '+(d.selection.single_server_id||'auto'),
'CSV pool enabled: '+(d.selection.csv_enabled?'YES':'NO'),
'Excluded IDs: '+(d.selection.excluded_ids||'none'),
...(d.restart_required?['Restart needed to apply selected backend.']:[]),
d.note
].join('\n')}catch(e){out.textContent='Check failed: '+e.message}}$('npSpeedtestCheck').onclick=checkSpeedtestBackend;async function checkPostgres(){const out=$('npPostgresCheckResult');const button=$('npPostgresCheck');button.disabled=true;out.textContent='Testing PostgreSQL connection…';try{const r=await fetch('/api/admin/postgres/check',{cache:'no-store'});const d=await r.json();out.textContent=d.success?['PostgreSQL connection: SUCCESS','Active database backend: '+d.active_backend,'Host: '+d.host+':'+d.port,'Database: '+d.database,'User: '+d.user,'Server: '+d.server_version,d.note].join('\n'):['PostgreSQL connection: FAILED','Active database backend: '+(d.active_backend||'unknown'),d.error||'Connection failed'].join('\n')}catch(e){out.textContent='PostgreSQL check failed: '+e.message}finally{button.disabled=false}}$('npPostgresCheck').onclick=checkPostgres;async function loadDatabaseProfile(){try{const r=await fetch('/api/admin/database');const d=await r.json();if(!r.ok)throw Error(d.error||'Unable to load database');$('npDbEngine').value=d.selected_engine;$('npDbHost').value=d.host;$('npDbPort').value=d.port;$('npDbName').value=d.database;$('npDbUser').value=d.user;$('npDbSaveResult').textContent='Active: '+d.engine+' · Saved: '+d.selected_engine+(d.password_configured?' · Password stored':' · Password not set')}catch(e){$('npDbSaveResult').textContent=e.message}}$('npDbSave').onclick=async()=>{const status=$('npDbSaveResult');status.textContent='Validating configuration…';const body={engine:$('npDbEngine').value,host:$('npDbHost').value,port:$('npDbPort').value,database:$('npDbName').value,user:$('npDbUser').value,password:$('npDbPassword').value};try{const r=await fetch('/api/admin/database',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'Validation failed');$('npDbPassword').value='';status.textContent=d.message}catch(e){status.textContent=e.message}};const modal=$('npSettingsModal'),fields=$('npSettingsFields'),status=$('npSettingsStatus');let values={};$('npSettingsOpen').onclick=async()=>{modal.hidden=false;refreshOokla();checkSpeedtestBackend();checkPostgres();loadDatabaseProfile();status.textContent='Loading…';try{const r=await fetch('/api/settings');if(!r.ok)throw Error('HTTP '+r.status);const data=await r.json();values=data.settings;const mismatch=$('npEnvMismatch');
const differences=data.docker_env_mismatches||[];
mismatch.replaceChildren();
if(differences.length){
 mismatch.hidden=false;
 const intro=document.createElement('p');
 intro.textContent='These Docker variables differ from the saved WebUI values. Saved WebUI settings currently take precedence:';
 mismatch.appendChild(intro);
 const table=document.createElement('table');table.className='np-data-table';
 for(const item of differences){
  const row=table.insertRow();
  for(const value of [item.key,'Docker: '+item.docker,'Saved / applied: '+item.saved]){
   row.insertCell().textContent=value;
  }
 }
 mismatch.appendChild(table);
}else mismatch.hidden=true;
fields.replaceChildren();const groups=[['Monitoring',['PROBE_INTERVAL','PING_COUNT','SITES','ROUTER_IP']],['DNS & resolvers',['DNS_TEST_SITE','DNS_TEST_SITES','DNS_NAMESERVER_1','DNS_NAMESERVER_1_IP','DNS_NAMESERVER_2','DNS_NAMESERVER_2_IP','DNS_NAMESERVER_3','DNS_NAMESERVER_3_IP','DNS_NAMESERVER_4','DNS_NAMESERVER_4_IP']],['Quality scoring',['WEIGHT_LOSS','WEIGHT_LATENCY','WEIGHT_JITTER','WEIGHT_DNS_LATENCY','THRESHOLD_LOSS','THRESHOLD_LATENCY','THRESHOLD_JITTER','THRESHOLD_DNS_LATENCY']],['Speedtest schedule',['SPEEDTEST_ENABLED','SPEEDTEST_INTERVAL','SPEEDTEST_BACKEND','SPEEDTEST_SECURE','SPEEDTEST_SERVER','SPEEDTEST_CSV','SPEEDTEST_CSV_SERVERS','SPEEDTEST_EXCLUDE']]];const seen=new Set();const makeField=(name,value)=>{const label=document.createElement('label');label.textContent=name.replaceAll('_',' ').toLowerCase().replace(/\bdns\b/g,'DNS').replace(/^./,v=>v.toUpperCase());let input;if(name==='SPEEDTEST_BACKEND'||['SPEEDTEST_ENABLED','SPEEDTEST_SECURE','SPEEDTEST_CSV'].includes(name)){input=document.createElement('select');const opts=name==='SPEEDTEST_BACKEND'?['python','ookla']:['true','false'];opts.forEach(v=>input.add(new Option(v==='true'?'Enabled':v==='false'?'Disabled':v,v)));}else{input=document.createElement('input');if(/^(PROBE_INTERVAL|PING_COUNT|SPEEDTEST_INTERVAL)$/.test(name)){input.type='number';input.min='1'}else if(name.startsWith('WEIGHT_')||name.startsWith('THRESHOLD_')){input.type='number';input.step='any'}else input.type='text'}input.dataset.key=name;input.value=String(value);input.autocomplete='off';label.append(input);fields.append(label);seen.add(name)};for(const [title,keys] of groups){const available=keys.filter(k=>Object.hasOwn(values,k));if(!available.length)continue;const heading=document.createElement('h3');heading.className='np-settings-section';heading.textContent=title;fields.append(heading);available.forEach(k=>makeField(k,values[k]))}for(const [name,value] of Object.entries(values)){if(!seen.has(name))makeField(name,value)}status.textContent='Monitoring settings apply immediately. Database switching is separate.'}catch(e){status.textContent=e.message}};$('npSettingsClose').onclick=()=>modal.hidden=true;$('npSettingsSave').onclick=async()=>{try{const body={};fields.querySelectorAll('input,select').forEach(i=>{if(i.value!==String(values[i.dataset.key]))body[i.dataset.key]=i.value});if(!Object.keys(body).length){status.textContent='No changes.';return}const r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'Save failed');Object.assign(values,body);status.textContent='Saved and applied to monitoring. Database changes require a separate restart.'}catch(e){status.textContent=e.message}};$('npRestartWorker').onclick=async()=>{
 const msg=$('npRestartStatus');
 if(!confirm('Restart the NetProbe application worker? The WebUI will briefly disconnect.'))return;
 msg.textContent='Requesting worker restart…';
 try{
  const res=await fetch('/api/admin/restart-worker',{method:'POST'});
  const data=await res.json();
  if(!res.ok)throw Error(data.error||'Worker restart refused');
  msg.textContent=data.message||'Application worker restarting.';
 }catch(e){msg.textContent=e.message;}
};
const minSlider=$('npPasswordMinSlider'),minOutput=$('npPasswordMinValue'),minStatus=$('npPasswordPolicyStatus');
const updateMinimumLabel=()=>{minOutput.textContent=minSlider.value+' characters';$('npNewPassword').minLength=Number(minSlider.value);$('npNewPassword').placeholder='New password (minimum '+minSlider.value+' characters)';};
minSlider.addEventListener('input',updateMinimumLabel);
async function loadPasswordPolicy(){
 try{const res=await fetch('/api/admin/password-policy');const data=await res.json();if(!res.ok)throw Error(data.error||'Policy unavailable');minSlider.value=data.min_password_length;updateMinimumLabel();minStatus.textContent='Source: '+data.source;}
 catch(error){minStatus.textContent=error.message;}
}
$('npSavePasswordPolicy').addEventListener('click',async()=>{
 minStatus.textContent='Saving…';
 try{const res=await fetch('/api/admin/password-policy',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({min_password_length:Number(minSlider.value)})});const data=await res.json();if(!res.ok)throw Error(data.error||'Policy save failed');minStatus.textContent='Saved to /config/security-policy.json';updateMinimumLabel();}
 catch(error){minStatus.textContent=error.message;}
});
loadPasswordPolicy();
$('npChangePassword').onclick=async()=>{const r=await fetch('/api/admin/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current:$('npOldPassword').value,password:$('npNewPassword').value})});const d=await r.json();status.textContent=d.success?'Password updated; sign in again.':(d.error||'Failed');if(d.success)location.href='/login'};$('npLogout').onclick=async()=>{await fetch('/logout',{method:'POST'});location.href='/login'};})();