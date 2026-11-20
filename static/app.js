'use strict';
const $ = (s) => document.querySelector(s);
const state = {history: [], filters: {}, selected: new Map(), busy: false, status: null, view: 'chat', offset: 0, browseFilters: {}, arabic: false};
const escapeHTML = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nice = (s) => String(s ?? '').replaceAll('_', ' ').replaceAll('|', ' / ');
const money = (n) => Number(n).toLocaleString(undefined, {maximumFractionDigits: 0});
function safeURL(value) {
  try { const u = new URL(value); return u.protocol === 'https:' && ['darglobal.co.uk','wasalt.sa','auction.wasalt.sa','blog.wasalt.sa','cdn.darglobal.co.uk'].includes(u.hostname.replace(/^www\./,'')) ? u.href : '#'; } catch { return '#'; }
}
function toast(text) { $('#toast').textContent=text; $('#toast').classList.remove('hidden'); setTimeout(()=>$('#toast').classList.add('hidden'),4500); }
let browserStorage=null;
try { browserStorage=window.localStorage; } catch { /* Private/restricted browser: retain in-memory chat. */ }
const chatStore=new AtlasHistory.ConversationStore(browserStorage, message=>toast(message));
function renderConversations(){
  const list=$('#conversation-list');list.replaceChildren();
  for(const conversation of chatStore.list()){
    const row=document.createElement('div');row.className='conversation-row'+(conversation.id===chatStore.data.currentId?' current':'');
    const open=document.createElement('button');open.className='conversation-open';open.textContent=conversation.title;open.title=conversation.title;
    open.setAttribute('aria-current',conversation.id===chatStore.data.currentId?'true':'false');
    open.addEventListener('click',()=>{if(state.busy)return toast('Please wait for the current answer.');chatStore.select(conversation.id);restoreConversation();});
    const remove=document.createElement('button');remove.className='conversation-delete';remove.textContent='×';remove.setAttribute('aria-label','Delete conversation: '+conversation.title);
    remove.addEventListener('click',()=>{if(state.busy)return toast('Please wait for the current answer.');chatStore.remove(conversation.id);if(!chatStore.current())chatStore.create();restoreConversation();});
    row.append(open,remove);list.append(row);
  }
  $('#history-empty').classList.toggle('hidden',chatStore.list().length>0);
}
function restoreConversation(){
  const conversation=chatStore.current()||chatStore.create();
  state.history=[];state.filters={...(conversation.filters||{})};state.selected.clear();updateTray();$('#messages').replaceChildren();
  for(const message of conversation.messages){
    if(message.role==='user'){appendUser(message.content);state.history.push({role:'user',content:message.content});}
    else if(message.role==='assistant'){appendAnswer(message.result);state.history.push({role:'assistant',content:message.result.answer});}
    else if(message.role==='error'){const el=document.createElement('p');el.className='message notice error-text';el.textContent=message.content;$('#messages').append(el);}
  }
  state.history=state.history.slice(-16);$('#welcome').classList.toggle('hidden',conversation.messages.length>0);
  $('#message-input').value='';$('#message-input').style.height='auto';filterChips();renderConversations();setView('chat');
}
$('#download-chat').addEventListener('click',()=>{
  const conversation=chatStore.exportCurrent();
  if(!conversation?.messages.length)return toast('Start a conversation first.');
  const text=conversation.messages.map(m=>m.role==='user'?'You: '+m.content:m.role==='assistant'?'Atlas: '+m.result.answer+'\n'+(m.result.sources||[]).map(s=>'['+s.id+'] '+s.title+' '+s.url).join('\n'):'Notice: '+m.content).join('\n\n');
  const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download='atlas-conversation.txt';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
async function api(path, options={}) { const response=await fetch(path, options); let data; try { data=await response.json(); } catch { throw new Error('Unable to read the response. Please try again.'); } if(!response.ok) throw new Error(response.status>=500?'Something went wrong. Please try again shortly.':data.error || 'Unable to complete this request.'); return data; }
function setView(view) {
  state.view=view;
  for(const name of ['chat','browse']) { $(`#${name}-view`).classList.toggle('hidden',name!==view); $(`#${name}-nav`).classList.toggle('active',name===view); }
  $('#page-name').textContent={chat:'Research assistant',browse:'Explore properties'}[view];
  $('#sidebar').classList.remove('open');
  if(view==='browse') runBrowse(true);
  window.scrollTo({top:0,behavior:'smooth'});
}
function renderText(text, sources=[]) {
  const byId=Object.fromEntries(sources.map(s=>[s.id,s]));
  return escapeHTML(text).split(/\n\s*\n/).map(paragraph=>'<p>'+paragraph.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\[S(\d+)\]/g,(_,n)=>{
    const source=byId[`S${n}`];return source?`<a class="citation" href="${escapeHTML(safeURL(source.url))}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(source.title)}">${n}</a>`:'';
  })+'</p>').join('');
}
function priceText(r) { if(!r.price) return 'Price unavailable'; if(r.price_kind==='range'&&r.price_max)return `${r.currency || ''} ${money(r.price)} – ${money(r.price_max)}`; const qualifier=r.price_kind==='starting_from'?'From ':'';return `${qualifier}${r.currency || ''} ${money(r.price)}`; }
function renderCards(records, target) {
  for(const r of records) {
    const card=document.createElement('article');card.className='property-card';
    const facts=[r.bedrooms?`${r.bedrooms} beds`:'',r.bathrooms?`${r.bathrooms} baths`:'',r.area_sqm?`${money(r.area_sqm)} m²`:''].filter(Boolean);
    const source=r.source==='darglobal'?'DarGlobal':'Wasalt';
    const period=r.price&&r.price_period&&r.price_period!=='total'?`/ ${nice(r.price_period)}`:'';
    const flags=String(r.quality_flags).includes('summary_only')?'Limited listing details — check the original source':String(r.quality_flags).includes('price_requires_verification')?'Source price requires verification':String(r.quality_flags).includes('partial_page')?'Some details may be unavailable':'';
    card.innerHTML=`<div class="card-art"><span>${escapeHTML(r.city || source)}</span></div><div class="card-body"><div class="card-source"><span>${source}</span><span class="kind">${escapeHTML(nice(r.kind))}</span></div><h3 class="card-title">${escapeHTML(r.title)}</h3><div class="card-location">${escapeHTML([r.district,r.city,r.country].filter(Boolean).join(' · ') || 'Location unavailable')}</div><div class="card-price">${escapeHTML(priceText(r))}<small>${escapeHTML(period)}</small></div><div class="card-facts">${facts.map(f=>`<span>${escapeHTML(f)}</span>`).join('') || '<span>See source for specifications</span>'}</div>${flags?`<div class="card-flag">${escapeHTML(flags)}</div>`:''}<div class="card-actions"><button class="detail-button">Details</button><button class="select-button ${state.selected.has(r.id)?'selected':''}" aria-pressed="${state.selected.has(r.id)}">${state.selected.has(r.id)?'Selected':'＋ Compare'}</button><a href="${escapeHTML(safeURL(r.url))}" target="_blank" rel="noopener noreferrer">View source</a></div></div>`;
    card.querySelector('.detail-button').addEventListener('click',()=>showDetails(r));
    card.querySelector('.select-button').addEventListener('click',e=>{ if(state.selected.has(r.id))state.selected.delete(r.id);else if(state.selected.size<4)state.selected.set(r.id,r);else return toast('Choose up to four records to compare.');e.currentTarget.classList.toggle('selected',state.selected.has(r.id));e.currentTarget.setAttribute('aria-pressed',String(state.selected.has(r.id)));e.currentTarget.textContent=state.selected.has(r.id)?'Selected':'＋ Compare';updateTray(); });
    target.append(card);
  }
}
function showDetails(r) {
  const fields={country:'Country',city:'City',district:'District',property_type:'Property type',purpose:'Purpose',bedrooms:'Bedrooms',bathrooms:'Bathrooms',area_sqm:'Area (m²)',furnishing:'Furnishing',amenities:'Amenities',reference:'Listing reference',price_period:'Price period'};
  const values=Object.entries(fields).filter(([key])=>r[key]!==''&&r[key]!=null);
  $('#record-content').innerHTML=`<span class="eyebrow">${escapeHTML(r.source==='darglobal'?'DARGLOBAL':'WASALT')} · ${escapeHTML(nice(r.kind))}</span><h2 class="detail-title">${escapeHTML(r.title)}</h2><p class="card-price">${escapeHTML(priceText(r))}</p><table class="data-table"><tbody>${values.map(([key,label])=>`<tr><td>${escapeHTML(label)}</td><td>${escapeHTML(nice(r[key]))}</td></tr>`).join('')}</tbody></table><p class="notice">Some details may be unavailable. Confirm current specifications, price and availability with the listing provider.</p><p><a href="${escapeHTML(safeURL(r.url))}" target="_blank" rel="noopener noreferrer">Open original listing</a></p>`;
  $('#record-dialog').showModal();
}
function updateTray() { $('#compare-tray').classList.toggle('hidden',state.selected.size===0);$('#compare-count').textContent=`${state.selected.size} selected`;$('#compare-button').disabled=state.selected.size<2; }
function comparisonTable(records) {
  const wrap=document.createElement('div');wrap.className='comparison-table';
  const keys=['source','city','country','property_type','price','price_period','bedrooms','bathrooms','area_sqm','furnishing'];
  wrap.innerHTML=`<table class="data-table"><thead><tr><th>Field</th>${records.map(r=>`<th>${escapeHTML(r.title)}</th>`).join('')}</tr></thead><tbody>${keys.map(k=>`<tr><td>${escapeHTML(nice(k))}</td>${records.map(r=>`<td>${escapeHTML(k==='price'?priceText(r):r[k]?nice(r[k]):'Unknown')}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  return wrap;
}
function filterChips() {
  const target=$('#filter-chips');target.replaceChildren();
  for(const [key,value] of Object.entries(state.filters)) {
    const labels={price_min:'Minimum price',price_max:'Maximum price',bedrooms_min:'Bedrooms (minimum)',bathrooms_min:'Bathrooms (minimum)',area_min:'Minimum area',area_max:'Maximum area',price_period:'Price period',property_type:'Property type',kind:'Category'};
    const chip=document.createElement('span');chip.className='filter-chip';chip.append(document.createTextNode(`${labels[key]||nice(key)}: ${nice(value)} `));
    const button=document.createElement('button');button.textContent='×';button.setAttribute('aria-label',`Remove ${nice(key)} filter`);button.addEventListener('click',()=>{delete state.filters[key];chatStore.setFilters(state.filters);filterChips();});chip.append(button);target.append(chip);
  }
}
function appendUser(text) { const node=document.createElement('div');node.className='message user';const bubble=document.createElement('div');bubble.className='user-bubble';bubble.dir='auto';bubble.textContent=text;node.append(bubble);$('#messages').append(node); }
function appendAnswer(result) {
  const node=document.createElement('article');node.className='message assistant';
  node.innerHTML=`<div class="assistant-label"><img src="/favicon.svg" alt="">Atlas <small>${result.mode==='clarification'?'A quick clarification':''}</small></div><div class="answer-text" dir="auto">${renderText(result.answer,result.sources)}</div>`;
  if(result.intent==='compare'&&result.records.length>1)node.append(comparisonTable(result.records));
  if(result.records?.length){const grid=document.createElement('div');grid.className='property-grid';renderCards(result.records,grid);node.append(grid);}
  if(result.sources?.length) {
    const details=document.createElement('details');details.className='sources-details';
    details.innerHTML=`<summary>${result.sources.length} supporting source passages</summary><div class="source-list">${result.sources.map(s=>`<div class="source-item"><a href="${escapeHTML(safeURL(s.url))}" target="_blank" rel="noopener noreferrer">[${escapeHTML(s.id)}] ${escapeHTML(s.title)}</a><p dir="auto">${escapeHTML(s.excerpt.slice(0,450))}</p></div>`).join('')}</div>`;node.append(details);
  }
  if(result.notice&&result.mode!=='ai'){const note=document.createElement('p');note.className='notice';note.textContent='The assistant is temporarily unavailable. You can still explore the results and read the sources.';node.append(note);}
  $('#messages').append(node);
}
async function send(text, compareIds=[]) {
  if(state.busy||!text.trim())return;
  state.busy=true;$('#send-button').disabled=true;$('#welcome').classList.add('hidden');appendUser(text);chatStore.addUser(text);renderConversations();$('#message-input').value='';$('#message-input').style.height='auto';
  const thinking=document.createElement('div');thinking.className='thinking';thinking.innerHTML='<span></span><span></span><span></span> Searching collected evidence…';$('#messages').append(thinking);thinking.scrollIntoView({behavior:'smooth',block:'center'});
  try {
    const result=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,history:state.history.slice(-8),filters:state.filters,compare_ids:compareIds})});
    thinking.remove();appendAnswer(result);state.filters=result.filters||{};filterChips();state.history.push({role:'user',content:text},{role:'assistant',content:result.answer});
    if(state.history.length>16)state.history=state.history.slice(-16);
    chatStore.addAnswer(result);renderConversations();
  } catch(error) {thinking.remove();const el=document.createElement('p');el.className='message notice error-text';el.textContent=error.message;$('#messages').append(el);chatStore.addError(error.message);}
  finally {state.busy=false;$('#send-button').disabled=false;$('#message-input').focus();}
}
async function runBrowse(reset=false) {
  if(reset){state.offset=0;state.browseFilters=Object.fromEntries([...new FormData($('#browse-form')).entries()].filter(([,v])=>v!==''));$('#browse-results').replaceChildren();}
  if(state.browseFilters.price_max&&!state.browseFilters.currency){toast('Choose a currency before filtering by budget.');return;}
  $('#browse-summary').textContent='Searching collected records…';
  try {
    const params=new URLSearchParams({...state.browseFilters,limit:12,offset:state.offset});const result=await api('/api/search?'+params);
    if(reset&&result.total===0)$('#browse-results').innerHTML='<div class="empty-state">No matches were found in the available listings. Try another location or adjust your filters.</div>';
    renderCards(result.records,$('#browse-results'));state.offset+=result.records.length;$('#browse-summary').textContent=`${result.total.toLocaleString()} matching properties and developments · showing ${state.offset} · availability unconfirmed`;
    $('#load-more').classList.toggle('hidden',state.offset>=result.total);
  } catch(error){$('#browse-summary').textContent=error.message;}
}

$('#chat-form').addEventListener('submit',event=>{event.preventDefault();send($('#message-input').value);});
$('#message-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();send(event.currentTarget.value);}});
$('#message-input').addEventListener('input',event=>{event.currentTarget.style.height='auto';event.currentTarget.style.height=Math.min(event.currentTarget.scrollHeight,150)+'px';});
$('#suggestions').addEventListener('click',event=>{const button=event.target.closest('[data-prompt]');if(button)send(button.dataset.prompt);});
$('#new-chat').addEventListener('click',()=>{if(state.busy)return toast('Please wait for the current answer.');chatStore.create();restoreConversation();});
for(const view of ['chat','browse'])$(`#${view}-nav`).addEventListener('click',()=>setView(view));
$('#menu-toggle').addEventListener('click',()=>$('#sidebar').classList.toggle('open'));
$('#browse-form').addEventListener('submit',event=>{event.preventDefault();runBrowse(true);});
$('#load-more').addEventListener('click',()=>runBrowse(false));
$('#close-dialog').addEventListener('click',()=>$('#record-dialog').close());
$('#record-dialog').addEventListener('click',event=>{if(event.target===$('#record-dialog'))$('#record-dialog').close();});
$('#clear-compare').addEventListener('click',()=>{state.selected.clear();updateTray();document.querySelectorAll('.select-button.selected').forEach(button=>{button.classList.remove('selected');button.textContent='＋ Compare';button.setAttribute('aria-pressed','false');});});
$('#compare-button').addEventListener('click',()=>{if(state.busy)return;setView('chat');const selected=[...state.selected.values()];send('Compare these properties: '+selected.map(r=>r.title).join(' vs '),selected.map(r=>r.id));state.selected.clear();updateTray();});
$('#language-toggle').addEventListener('click',()=>{state.arabic=!state.arabic;document.documentElement.classList.toggle('arabic',state.arabic);document.documentElement.lang=state.arabic?'ar':'en';$('#language-toggle').textContent=state.arabic?'English':'العربية';$('#message-input').placeholder=state.arabic?'اسأل عن مشروع، موقع، ميزانية، أو عقار…':'Ask about a project, location, budget, or property…';$('#message-input').focus();});
async function init(){
  if(!chatStore.current())chatStore.create();
  restoreConversation();
  try{
    state.status=await api('/api/status');
    for(const city of Object.keys(state.status.stats.by_city||{}).sort()){
      const option=document.createElement('option');option.value=option.textContent=city;$('#city-select').append(option);
    }
  }catch{toast('Unable to connect. Please check your connection and try again.');}
}
init();
