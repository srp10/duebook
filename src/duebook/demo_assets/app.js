'use strict';
const $ = id => document.getElementById(id);
let session = sessionStorage.getItem('duebook-session');
let busy = false;
let documentActionActive=false;
let latestState;
let selectedFilter = "all";
let toastTimer;
let previewReturnKey;
let restorePreviewFocus=false;
function node(tag, cls, text) { const e = document.createElement(tag); if(cls)e.className=cls; if(text!==undefined)e.textContent=text; return e; }
async function request(path, payload) {
  const options = payload === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)};
  const response = await fetch(path, options);
  const data = await response.json();
  if(!response.ok) throw new Error(data.error || 'Could not complete the request.');
  return data;
}
function error(message) { if(documentActionActive){$('document-error').textContent=message;$('document-error').hidden=!message;return;} $('error').textContent = message; $('error').hidden = !message; $('preview-error').textContent=message; $('preview-error').hidden=!message; }
function notify(message) { clearTimeout(toastTimer); $('toast').textContent=message; $('toast').hidden=false; toastTimer=setTimeout(()=>$('toast').hidden=true,5000); }
function setBusy(value, message='Checking your deadlines…') {
  busy=value;
  document.querySelectorAll('button,input,textarea').forEach(e=>e.disabled=value || e.dataset.unavailable === "true");
  $('activity').textContent=value && !documentActionActive ? message : 'Saved deadlines stay when you start a new conversation.';
  $('messages').setAttribute('aria-busy',String(value && !documentActionActive));
  $('document-panel').setAttribute('aria-busy',String(value && documentActionActive));
  if(documentActionActive){$('document-status').hidden=!value;$('document-status').textContent=message;if(value)$('document-status').scrollIntoView({block:'nearest'});}
}
async function perform(action, message) {
  if(busy)return;
  error('');setBusy(true,message);
  try { return await action(); } catch(e) { error(e.message); } finally { setBusy(false); }
}
function render(data) {
  latestState=data;
  const expanded=new Set([...document.querySelectorAll(".deadline .evidence[open]")].map(e=>e.closest(".deadline").dataset.key));
  renderBriefing(data);
  error(data.warning || '');
  $('connection').textContent=data.warning ? 'Vault connection unavailable' : 'Demo vault connected';
  $('connection-dot').classList.toggle('ready',!data.warning);
  if(data.messages.length) {
    $('messages').replaceChildren();
    for(const item of data.messages) {
      const bubble=node('div',`bubble ${item.role}`);
      if(item.role==='assistant')bubble.append(node('span','bubble-label','DUEBOOK'));
      bubble.append(node('span','',item.text));$('messages').append(bubble);
    }
  } else {
    const welcome=node('div','welcome');welcome.append(node('span','welcome-icon','✦'),node('h3','','What’s coming up?'),node('p','','I can help you see what’s due, spot dates that collide, and turn a document into a deadline.'));$('messages').replaceChildren(welcome);
  }
  $('messages').scrollTop=$('messages').scrollHeight;
  renderDocument(data);
  if(documentActionActive)requestAnimationFrame(()=>$(data.pending?'pending':'document-result').scrollIntoView({block:'nearest'}));
  $('pending').hidden=!data.pending;
  $('save-overdue').hidden=data.pending?.confirmation_type!=='past_due';
  $('confirm-form').querySelector('button').textContent=data.pending?.confirmation_type==='past_due'?'Correct date':'Confirm';
  if(data.pending){$('question').textContent=data.pending.question;$('candidate').textContent=`${data.pending.candidate.title} · ${data.pending.filename}`;}
  renderReminders(data);
  $('count').textContent=`${data.deadlines.length} open deadlines · synthetic household`;
  $('deadlines').replaceChildren();
  let visibleCount=0;
  for(const item of data.deadlines) {
    if(selectedFilter==="hard" && item.kind!=="hard")continue;
    if(selectedFilter==="reminders" && data.reminders?.items[item.key]?.status!=="active")continue;
    visibleCount++;
    const card=node('article','deadline'),main=node('div','deadline-main'),tile=node('div','date-tile');
    card.dataset.key=item.key || item.title+item.due;
    const d=new Date(`${item.due}T12:00:00`);
    tile.append(node('span','',d.toLocaleString('en',{month:'short'})),node('strong','',String(d.getDate())));
    const info=node('div','deadline-info');info.append(node('h3','',item.title),node('p','',`${d.toLocaleDateString("en-GB",{weekday:"short",day:"numeric",month:"long"})} · ${relativeDate(item.due)}`));
    main.append(tile,info,node('span',`pill ${item.kind}`,item.kind==='hard'?'Hard deadline':'Flexible'));
    card.classList.toggle('urgent',relativeDays(item.due)<=1);
    const evidence=node('details','evidence');evidence.append(node('summary','','Source & calculation'),node('blockquote','',item.source));
    if(item.notes)evidence.append(node('p','',item.notes));
    if(item.window_start)evidence.append(node('p','',`Window opens: ${item.window_start}`));
    evidence.append(node('p','',`Recorded confidence: ${item.confidence}. ${item.confidence_note || 'Confidence does not independently verify supplied facts.'}`));
    evidence.open=expanded.has(card.dataset.key);
    card.append(main,evidence);
    if(data.reminders && item.key) {
      const info=data.reminders.items[item.key] || {status:'off'};
      const controls=node('div','reminder-controls');
      controls.append(node('p','subtle',`${info.status==='off'?'No reminder set':info.status==='active'?'● Reminders on':'Reminders '+info.status}${info.next?' · '+new Date(info.next).toLocaleString('en-GB',{timeZone:'Asia/Hong_Kong',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})+' HKT':''}`));
      if(info.error)controls.append(node('p','reminder-error',info.error));
      if(info.last)controls.append(node('p','subtle',`Last email attempt: ${info.last.status === 'accepted' ? 'accepted by SES (inbox delivery not confirmed)' : info.last.status}${info.last.error?' · '+info.last.error:''}`));
      const preview=reminderButton(info.status==='active'?'Review email':'Remind me','preview',item.key);
      preview.classList.add('remind-button');
      if(!data.reminders.configured){preview.textContent='Set up reminders';preview.dataset.setup='true';}
      controls.append(preview);
      if(info.status==='active') {
        if(info.next)controls.append(reminderButton('Snooze 24 hours','snooze',item.key));
        controls.append(reminderButton('Cancel reminders','cancel',item.key));
      }
      controls.append(reminderButton('Mark done','done',item.key));card.append(controls);
    }
    $('deadlines').append(card);
  }
  if(!visibleCount){const empty=node('div','empty-state');empty.append(node('span','','✓'),node('h3','',selectedFilter==='reminders'?'No reminders enabled yet':selectedFilter==='hard'?'No hard deadlines in this window':'A little breathing room.'),node('p','',selectedFilter==='reminders'?'Choose a deadline and preview its email to get started.':'Your saved records stay in the vault.'));$('deadlines').append(empty);}
  $('count').textContent=selectedFilter==='all'?`${data.deadlines.length} open deadlines · synthetic household`:`${visibleCount} of ${data.deadlines.length} open deadlines · synthetic household`;
  $('conflicts').hidden=selectedFilter!=='all';
  $('conflicts').replaceChildren();
  for(const c of data.conflicts) {
    const card=node('div','conflict');card.append(node('strong','',`${c.days_apart} days apart · worth planning together`),node('p','',c.explanation));$('conflicts').append(card);
  }
  $('trace-panel').hidden=!data.trace.length;$('trace').replaceChildren();
  const names={list_due:'Read saved deadlines',find_conflicts:'Checked date collisions',ingest_document:'Reviewed the document'};
  for(const check of data.trace){$('trace').append(node('li','',`${names[check.tool]||check.tool} · ${check.status}`));}
  if(restorePreviewFocus){requestAnimationFrame(()=>document.querySelector(`[data-action="preview"][data-key="${previewReturnKey}"]`)?.focus());restorePreviewFocus=false;}
}
async function refresh(){render(await request(`/api/state?session=${encodeURIComponent(session)}`));}
async function newSession(){
  const data=await request('/api/session',{});session=data.session;sessionStorage.setItem('duebook-session',session);$('hint').value='';$('message').value='';await refresh();
}
async function send(message){await perform(async()=>{const data=await request('/api/chat',{session,message});$('message').value='';render(data);},'Thinking and checking the saved evidence…');}
$('chat-form').addEventListener('submit',e=>{e.preventDefault();send($('message').value);});
$('message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();if($('message').value.trim())send($('message').value);}});
document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>send(b.dataset.prompt)));
$('new-session').addEventListener('click',()=>perform(async()=>{
  await newSession();
  $('messages').querySelector('.welcome h3').textContent='Your fresh conversation is ready.';
  $('messages').querySelector('.welcome p').textContent='Ask a new question. Your saved deadlines and reminders are still here.';
  notify('New conversation started. Saved deadlines and reminders are unchanged.');
  requestAnimationFrame(()=>$('message').focus({preventScroll:true}));
},'Starting a fresh conversation…'));
$('refresh').addEventListener('click',()=>perform(refresh,'Reading saved deadlines…'));
$('confirm-form').addEventListener('submit',e=>{e.preventDefault();performDocument(async()=>{render(await request('/api/confirm',{session,hint:$('hint').value}));$('hint').value='';},'Checking your clarification and saving if the date is clear…');});
$('save-overdue').addEventListener('click',()=>performDocument(async()=>{render(await request('/api/confirm-overdue',{session}));$('hint').value='';},'Confirming the overdue date…'));
$('cancel').addEventListener('click',()=>performDocument(async()=>render(await request('/api/cancel',{session})))) ;
document.querySelectorAll('[data-sample]').forEach(b=>b.addEventListener('click',()=>performDocument(async()=>render(await request('/api/sample',{session,name:b.dataset.sample})),'Reading the synthetic sample through Bedrock…')));
async function upload(file){
  if(!file)return;
  await performDocument(async()=>{
    if(file.size>2*1024*1024)throw new Error('Choose a file smaller than 2 MiB.');
    const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Could not read this file.'));reader.readAsDataURL(file);});
    render(await request('/api/upload',{session,filename:file.name,data:encoded}));
  },'Reading the document through Bedrock…');
  $('file').value='';
}
$('file').addEventListener('change',()=>upload($('file').files[0]));
$('dropzone').addEventListener('dragover',e=>{e.preventDefault();$('dropzone').classList.add('drag');});
$('dropzone').addEventListener('dragleave',()=>$('dropzone').classList.remove('drag'));
$('dropzone').addEventListener('drop',e=>{e.preventDefault();$('dropzone').classList.remove('drag');upload(e.dataTransfer.files[0]);});
perform(async()=>{if(session){try{await refresh();return;}catch{session=null;}}await newSession();},'Connecting to the demo vault…');


function reminderButton(label,action,key,token) {
  const button=node('button','quiet',label);
  button.dataset.action=action; if(key)button.dataset.key=key;
  button.addEventListener('click',()=>{
    if(button.dataset.setup==='true'){ $('email-setup').open=true; $('reminder-panel').scrollIntoView({behavior:'smooth',block:'center'}); $('email-setup').querySelector('summary').focus(); return; }
    if(action==='preview')previewReturnKey=key;
    return perform(async()=>{
    const data=await request('/api/reminders',{session,action,key,token});
    render(data);
    const feedback={enable:'Reminders enabled. Your next email is scheduled.',test:'Email accepted by SES. Check your inbox to confirm delivery.',done:'Marked done. Find it under completed deadlines.',cancel:'Reminders cancelled. Your deadline is still saved.',snooze:'Next reminder moved back by 24 hours.'};
    if(feedback[action])notify(feedback[action]);
  }, action==='test'?'Sending the approved email once…':'Updating reminder settings…');});
  return button;
}
function renderReminders(data) {
  const info=data.reminders;
  const cloud=info?.mode==='cloud';
  $('email-setup').hidden=cloud;
  $('reminder-delivery').textContent=cloud ? 'Runs on AWS, even when your Mac is asleep. Emails are scheduled for 9am Hong Kong time, 7 days before, 1 day before and on the due date. Use this app online to change or cancel a plan; offline file edits do not update AWS.' : 'Opt in on each deadline. Scheduled for 9am Hong Kong time, 7 days before, 1 day before and on the due date. Keep this Mac awake and the server running; the browser can be closed.';
  $('delivery-footer').textContent=cloud ? 'Email reminders run on AWS after you opt in.' : 'Email reminders require opt-in and the local server.';
  $('reminder-status').textContent=info ? (info.configured ? `${cloud?'AWS delivery ready':'Local delivery ready'} · ${info.to}` : 'Email is not configured yet. No messages will be sent.') : 'Reminder controls unavailable. Restart the updated server.';
  if(info?.worker_error)$('reminder-status').textContent += ' '+info.worker_error;
  const box=$('email-preview');box.replaceChildren();const dialog=$('preview-dialog');
  if(!data.email_preview && dialog.open){dialog.close();restorePreviewFocus=true;}
  if(data.email_preview) {
    const p=data.email_preview;
    const title=node('h2','','A helpful nudge, on your terms.');title.id='preview-title';
    box.append(node('p','eyebrow','EMAIL PREVIEW'),title,node('p','',`From: ${p.from}`),node('p','',`To: ${p.to}`),node('strong','',p.subject),node('pre','email-body',p.body));
    box.append(node('p','subtle',p.schedule.length ? 'Scheduled times (HKT): '+p.schedule.map(t=>new Date(t).toLocaleString('en-GB',{timeZone:'Asia/Hong_Kong'})).join('; ') : 'No future standard reminder dates remain.'));
    box.append(node('p','subtle','The message above includes the saved source and context. Enabling reminders consents to sending it on the listed dates. Sending once does not enable the schedule. If a send fails, check your inbox before retrying.'));
    if(p.schedule.length && info.items[p.key]?.status!=='active')box.append(reminderButton('Enable these email reminders','enable',p.key,p.token));
    box.append(reminderButton('Send this email once','test',p.key,p.token),reminderButton('Close preview','dismiss'));
    if(!dialog.open)dialog.showModal();
  }
  const completed=$('completed-deadlines');completed.replaceChildren();
  for(const d of info?.completed || [])completed.append(node('p','',`${d.title} · due ${d.due} · done`));
  if(!info?.completed?.length)completed.append(node('p','subtle','No completed deadlines yet.'));
}

function relativeDays(iso) {
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Hong_Kong',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const value=type=>parts.find(p=>p.type===type).value;
  const today=Date.UTC(+value('year'),+value('month')-1,+value('day'));
  return Math.round((Date.parse(iso+'T00:00:00Z')-today)/86400000);
}
function relativeDate(iso) { const days=relativeDays(iso); return days<0?`${-days} day${days===-1?'':'s'} overdue`:days===0?'Due today':days===1?'Due tomorrow':`In ${days} days`; }
function renderBriefing(data) {
  const upcoming=[...data.deadlines].sort((a,b)=>a.due.localeCompare(b.due));
  const first=upcoming[0];
  $('open-total').textContent=data.warning?'—':upcoming.length;
  $('reminder-total').textContent=data.reminders?Object.values(data.reminders.items).filter(p=>p.status==='active').length:'—';
  $('next-label').textContent=data.warning?'CONNECTION NEEDS ATTENTION':first?relativeDate(first.due).toUpperCase():'ALL CLEAR IN THIS WINDOW';
  $('next-title').textContent=data.warning?'Let’s reconnect to your vault.':first?first.title:'Room for the rest of life.';
  $('next-detail').textContent=data.warning?'Your saved deadlines have not been removed.':first?`${new Date(first.due+'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'long'})} · Check the source before taking action.`:'No open deadlines in the next 60 days.';
}
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{
  selectedFilter=button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  if(latestState)render(latestState);
}));
$('preview-dialog').addEventListener('cancel',event=>{event.preventDefault();if(!busy)perform(async()=>render(await request('/api/reminders',{session,action:'dismiss'})));});

async function performDocument(action,message='Updating this document…') {
  if(busy)return;
  documentActionActive=true;
  $('error').hidden=true;
  $('document-result').hidden=true;
  try { await perform(action,message); }
  finally { documentActionActive=false; }
}
function renderDocument(data) {
  const box=$('document-result');box.replaceChildren();
  const result=data.document_result;
  box.hidden=!result || !!data.pending;
  if(!result || data.pending)return;
  box.append(node('p','eyebrow',result.status==='saved'?'SAVED TO YOUR DEADLINES':result.status==='already_saved'?'ALREADY SAVED':'DOCUMENT UPDATE'));
  if(result.filename)box.append(node('p','subtle',result.filename));
  box.append(node('p','',result.message));
  if(result.entry){
    box.append(node('blockquote','',result.entry.source || ''));
    const link=node('button','text-button',result.status==='already_saved'?'View existing deadline ↑':'View saved deadline ↑');
    link.addEventListener('click',()=>{
      selectedFilter='all';document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter==='all')));
      render(latestState);
      const item=latestState.deadlines.find(d=>d.title===result.entry.title && d.due===result.entry.due);
      const key=item && (item.key || item.title+item.due);
      const card=[...document.querySelectorAll('.deadline')].find(c=>c.dataset.key===key);
      if(card){card.querySelector('.evidence').open=true;card.tabIndex=-1;card.scrollIntoView({block:'center'});card.focus({preventScroll:true});}
      else notify('This saved record is outside the current open-deadline view.');
    });box.append(link);
  }
}
