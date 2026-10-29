/* NetProbe dashboard navigation and panel layout only.
 * main.js owns charts and data refresh; changing DOM IDs here requires
 * checking the matching elements in probe/templates/index.html.
 * Layout preferences are browser-local and do not alter probe settings.
 */
document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const $ = id => document.getElementById(id);
  const ids = ['panelScore','panelLoss','panelLatency','panelJitter','panelDns','panelSpeed'];
  const sources = {panelScore:['gScoreText','npValueScore'],panelLoss:['gLossText','npValueLoss'],panelLatency:['gLatencyText','npValueLatency'],panelJitter:['gJitterText','npValueJitter'],panelDns:['gDnsText','npValueDns'],panelSpeed:['gSpeedText','npValueSpeed']};
  const titles = {overview:['Quality overview','Internet quality history and current measurements.'],metrics:['Network diagnostics','Latency, jitter, packet loss and DNS measurements.'],speedtest:['Bandwidth tests','Latest Speedtest measurements and historical bandwidth.'],history:['Historical monitoring','All monitoring charts together, with linked time-range controls.'],customize:['Customize display','Choose the visible summary cards and historical chart panels.']};
  const host = $('npPanelHost');
  let prefs;
  try { prefs = JSON.parse(localStorage.getItem('netprobe_ui_v2') || '{}'); } catch { prefs = {}; }
  if (!prefs || typeof prefs !== 'object') prefs={};
  const density=['balanced','compact','detailed'].includes(prefs.density)?prefs.density:'balanced';
  $('npDensity').value=density;
  function save(){try{const panels={};document.querySelectorAll('.panel-toggle').forEach(el=>panels[el.dataset.target]=el.checked);localStorage.setItem('netprobe_ui_v2',JSON.stringify({density:$('npDensity').value,view:currentView,panels}));}catch{}}
  function rescale(){requestAnimationFrame(()=>setTimeout(()=>{
    for (const canvas of host.querySelectorAll('canvas')) {
      if (window.Chart && typeof window.Chart.getChart==='function') {
        const chart=window.Chart.getChart(canvas); if(chart){try{chart.resize();chart.update('none');}catch{}}
      }
    }
  },70));}
  const all={}; for(const id of ids) all[id]=$(id);
  let currentView='overview'; // Always land on live status; no stale History selection after reload.
  // One owner for the four monitoring pages, customization, and History panels.
  // Browser-local panel selection only changes cards/charts, never the page.
  const pageIds={overview:'npOverviewPage',metrics:'npMetricsPage',
    speedtest:'npSpeedPage',customize:'npCustomizePage'};
  function renderView(view){
    if(!['overview','metrics','speedtest','history','customize'].includes(view))view='overview';
    currentView=view;
    document.body.dataset.currentView=view;
    for(const [name,id] of Object.entries(pageIds)){
      const page=$(id);
      if(!page){console.error('[NetProbe navigation] Missing page:',id);continue}
      const active=name===view;
      page.hidden=!active;
      page.style.removeProperty('display');
      page.setAttribute('aria-hidden',String(!active));
    }
    const targetPanels=view==='history'?ids:(view==='speedtest'?['panelSpeed']:[]);
    const inactive=$('npInactivePanels');
    for(const id of ids){
      const panel=all[id];if(!panel)continue;
      const checkbox=document.querySelector('.panel-toggle[data-target="'+id+'"]');
      const enabled=!checkbox||checkbox.checked;
      const destination=targetPanels.includes(id)&&enabled?host:inactive;
      if(destination&&panel.parentElement!==destination)destination.appendChild(panel);
    }
    const workspace=$('npWorkspace');
    if(workspace)workspace.hidden=!(view==='history'||view==='speedtest');
    const cards=$('npCards');
    if(cards)cards.hidden=view!=='overview';
    const status=document.querySelector('.np-status');
    if(status)status.hidden=view!=='overview';
    const heading=document.querySelector('.np-view-heading');
    if(heading)heading.hidden=!(view==='history'||view==='speedtest');
    const title=$('npViewTitle'),description=$('npViewDesc');
    if(title)title.textContent=titles[view][0];
    if(description)description.textContent=titles[view][1];
    const shown=targetPanels.some(id=>{
      const cb=document.querySelector('.panel-toggle[data-target="'+id+'"]');
      return !cb||cb.checked;
    });
    if($('npEmpty'))$('npEmpty').hidden=(view!=='history'||shown);
    document.querySelectorAll('[data-view]').forEach(el=>{
      const active=el.dataset.view===view;
      el.classList.toggle('active',active);
      if(active)el.setAttribute('aria-current','page');
      else el.removeAttribute('aria-current');
    });
    save();rescale();
    refreshFeaturePages();
  }
  // Pages consume existing read-only APIs, not additional probe processes.
  const escapeText=value=>String(value??'—');
  function rows(target,items){target.replaceChildren();if(!items.length){target.textContent='No configured targets';return}const table=document.createElement('table');table.className='np-data-table';for(const [a,b] of items){const tr=table.insertRow();tr.insertCell().textContent=escapeText(a);tr.insertCell().textContent=escapeText(b)}target.appendChild(table)}
  // Each page fetches its data independently. Failure of one API must not
  // blank the other views or discard the last good measurement.
  async function refreshFeaturePages(){
    if(currentView==='history')return;
    const read=async url=>{try{const r=await fetch(url);return r.ok?await r.json():null}catch{return null}};
    const [conf,latest,speed,snapshot]=await Promise.all([
      read('/api/config'),read('/api/score/latest'),read('/api/speedtest/latest'),
      currentView==='metrics'?read('/api/metrics/targets'):Promise.resolve(null)
    ]);
    const d=latest?.data;
    if(d){
      const fmt=(n,digits=1)=>Number.isFinite(Number(n))?Number(n).toFixed(digits):'—';
      $('npOverviewScore').textContent=fmt(d.score)+'%';
      $('npOverviewTime').textContent=d.ts?new Date(d.ts*1000).toLocaleString():'—';
      $('npOverviewSummary').textContent='Packet loss '+fmt(d.avg_loss_pct)+'% · Latency '+fmt(d.avg_latency_ms)+' ms · DNS '+fmt(d.avg_dns_latency_ms)+' ms';
      rows($('npMetricLatest'),[['Quality score',fmt(d.score)+'%'],['Loss',fmt(d.avg_loss_pct,2)+'%'],['Latency',fmt(d.avg_latency_ms)+' ms'],['Jitter',fmt(d.avg_jitter_ms)+' ms'],['DNS',fmt(d.avg_dns_latency_ms)+' ms'],['Timestamp',d.ts?new Date(d.ts*1000).toLocaleString():'—']]);
    }
    if(conf){
      const targets=[...(conf.gateway_ip?[['Docker gateway',conf.gateway_ip]]:[]),
        ...(conf.router_ip?[['LAN router',conf.router_ip]]:[]),
        ...(conf.sites||[]).map(x=>['Ping target',x])];
      $('npOverviewTargets').textContent=targets.length+' configured';
      rows($('npMetricTargets'),targets);
      rows($('npMetricResolvers'),(conf.dns_servers_detail||[]).map(x=>[x.name||'DNS resolver',x.ip]));
    }
    if(snapshot?.ping?.length){
      rows($('npMetricTargets'),snapshot.ping.map(x=>[x.target,
        (x.latency_ms==null?'Timeout':Number(x.latency_ms).toFixed(1)+' ms')+
        ' · '+Number(x.loss_pct??100).toFixed(1)+'% loss'+
        (x.jitter_ms==null?'':' · '+Number(x.jitter_ms).toFixed(1)+' ms jitter')]));
    }
    if(snapshot?.dns?.length){
      rows($('npMetricResolvers'),snapshot.dns.map(x=>[x.resolver,
        x.latency_ms==null?'No response':Number(x.latency_ms).toFixed(1)+' ms']));
    }
    if(speed){
      const r=speed.result;
      if(r){
        rows($('npSpeedDetails'),[
          ['Download',Number(r.download_mbps).toFixed(2)+' Mbps'],
          ['Upload',Number(r.upload_mbps).toFixed(2)+' Mbps'],
          ['Ping',Number(r.ping_ms).toFixed(2)+' ms'],
          ['Server',r.server?.name||'Automatic'],
          ['Backend',r.backend||'python'],
          ['Timestamp',r.ts?new Date(r.ts*1000).toLocaleString():'—']
        ]);
      }else $('npSpeedDetails').textContent='No completed Speedtest yet.';
    }
  }
  setInterval(()=>{if(currentView!=='history')refreshFeaturePages()},15000);
  for(const b of document.querySelectorAll('[data-view]')) b.addEventListener('click',()=>renderView(b.dataset.view));
  $('npDensity').addEventListener('change',()=>{$('body');document.querySelector('.np-app').dataset.density=$('npDensity').value;save();rescale();});
  document.querySelector('.np-app').dataset.density=density;
  function updateValues(){for(const [id,pair] of Object.entries(sources)){
    const source=$(pair[0]), dest=$(pair[1]); if(!source||!dest)continue;
    let txt=(source.textContent||'').trim();
    if(id==='panelSpeed')txt=txt.replace(/\n/g,' · ');
    if(txt)dest.textContent=txt.replace(/^(Score|Loss|Latency|Jitter|DNS|Down):\s*/i,'');
    // Chart preferences are local display choices for both summary cards and History.
    const cb=document.querySelector('.panel-toggle[data-target="'+id+'"]');
    const card=document.querySelector('.np-card[data-metric="'+id+'"]');if(card&&cb)card.hidden=!cb.checked;
  }}
  // Only saved browser-local display preferences affect which cards/charts show.
  if(prefs.panels && typeof prefs.panels==='object'){
    document.querySelectorAll('.panel-toggle').forEach(el=>{
      if(typeof prefs.panels[el.dataset.target]==='boolean')el.checked=prefs.panels[el.dataset.target];
    });
  }
  const obs=new MutationObserver(updateValues);
  for(const [source] of Object.values(sources)){const el=$(source); if(el)obs.observe(el,{characterData:true,childList:true,subtree:true});}
  document.querySelectorAll('.panel-toggle').forEach(cb=>cb.addEventListener('change',()=>{updateValues();renderView(currentView);}));
  const drawer=$('npDrawer'),scrim=$('npScrim');let previousFocus=null;
  function open(tool='tests') {previousFocus=document.activeElement;drawer.classList.add('open');drawer.setAttribute('aria-hidden','false');scrim.hidden=false;document.body.style.overflow='hidden';switchTool(tool);{const btn=$('btnToggleLogs');if(btn){if(tool==='logs'&&btn.textContent.includes('Follow'))btn.click();if(tool!=='logs'&&btn.textContent.includes('Hide'))btn.click();}}$('npCloseTools').focus();}
  function close(){drawer.classList.remove('open');drawer.setAttribute('aria-hidden','true');scrim.hidden=true;document.body.style.overflow='';{const btn=$('btnToggleLogs');if(btn&&btn.textContent.includes('Hide'))btn.click();}if(previousFocus&&previousFocus.focus)previousFocus.focus();rescale();}
  function switchTool(tool){
    for(const t of ['tests','config','logs']){
      const el=$('npTool'+t[0].toUpperCase()+t.slice(1));
      if(el){el.hidden=t!==tool;el.style.removeProperty('display');}
    }
    const heading=drawer.querySelector('.np-drawer-top h2');
    if(heading)heading.textContent=({tests:'Manual tests',config:'Current configuration',logs:'Logs & diagnostics'})[tool]||'Diagnostics';
  }
  $('npOpenTools')?.addEventListener('click',()=>open('tests'));
  $('npCustomize')?.addEventListener('click',()=>renderView('customize'));$('npCloseTools').addEventListener('click',close);scrim.addEventListener('click',close);
  document.querySelectorAll('[data-tool]').forEach(b=>b.addEventListener('click',()=>switchTool(b.dataset.tool)));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&drawer.classList.contains('open'))close();if(e.key==='Tab'&&drawer.classList.contains('open')){let f=[...drawer.querySelectorAll('button:not([disabled]),select:not([disabled]),input:not([disabled]),a[href]')].filter(el=>el.getClientRects().length);if(!f.length)return;let first=f[0],last=f[f.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
  // Manual Speedtest belongs on the Speedtest page, not in a second tools
  // dialog. Move the SAME controls so main.js retains its event listeners.
  if(document.body.dataset.admin==='true'){
    const speedActions=$('npSpeedActions');
    const speedRun=$('btnRunSpeedtest');
    if(speedActions && speedRun){
      const controls=document.createElement('div');
      controls.className='np-speed-controls';
      for(const id of ['speedtestBackendSelect','speedtestServerInput','speedtestSecureCheckbox','speedtestForceAutoCheckbox','btnRunSpeedtest']){
        const el=$(id);if(!el)continue;
        const parent=el.closest('label.compact-checkbox');
        controls.appendChild(parent||el);
      }
      speedActions.appendChild(controls);
      const output=document.createElement('pre');
      output.id='npSpeedRunOutput';output.className='np-speed-output';
      output.textContent='Run a manual Speedtest to see output here. Completed runs appear in history.';
      speedActions.appendChild(output);
    }
  }
  $('npGoSpeedtest')?.addEventListener('click',()=>{close();renderView('speedtest');markSidebar('speedtest',null)});
  // Guest-safe chart visibility belongs to History, not administrator Settings.
  $('npResetDisplay')?.addEventListener('click',()=>{document.querySelectorAll('.panel-toggle').forEach(el=>el.checked=true);updateValues();renderView(currentView);});
  // Dedicated left navigation reuses the existing chart/page controller.
  // Admin tools retain their API bindings but occupy a full workspace view.
  const sidebar=$('npSidebar');
  const mobile=$('npMobileMenu');
  function markSidebar(view,tool){
    document.querySelectorAll('.np-side-link').forEach(b=>{
      const yes=(view&&b.dataset.sidebarView===view)||(tool&&b.dataset.sidebarTool===tool);
      b.classList.toggle('active',!!yes);
      if(yes)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
    });
    sidebar.classList.remove('mobile-open');
  }
  document.querySelectorAll('[data-sidebar-view]').forEach(b=>b.addEventListener('click',()=>{
    close();if($('npSettingsModal'))$('npSettingsModal').hidden=true;renderView(b.dataset.sidebarView);
    markSidebar(b.dataset.sidebarView,null);
  }));
  document.querySelectorAll('[data-sidebar-tool]').forEach(b=>b.addEventListener('click',()=>{
    if($('npSettingsModal'))$('npSettingsModal').hidden=true;open(b.dataset.sidebarTool);
    markSidebar(null,b.dataset.sidebarTool);
  }));
  document.querySelector('[data-sidebar-settings]')?.addEventListener('click',()=>{
    close();$('npSettingsOpen')?.click();markSidebar(null,null);
    document.querySelector('[data-sidebar-settings]').classList.add('active');
  });
  mobile?.addEventListener('click',()=>sidebar.classList.toggle('mobile-open'));
  markSidebar(currentView,null);
  // Once a tool is closed, return to the last monitoring view.
  $('npCloseTools').addEventListener('click',()=>markSidebar(currentView,null));
  // main.js expects these original controls and panels; all are retained, moved rather than cloned.
  renderView(currentView);updateValues();window.addEventListener('resize',rescale);
});
