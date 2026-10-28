'use strict';
const paths={funds:'M4 6c0-3 16-3 16 0s-16 3-16 0m0 0v4c0 3 16 3 16 0V6M4 10v4c0 3 16 3 16 0v-4M4 14v4c0 3 16 3 16 0v-4',treated:'m3 7 9-4 9 4-9 4-9-4m0 5 9 4 9-4M3 17l9 4 9-4',gain:'M4 21V12h3v9M11 21V8h3v13M18 21V3h3v18M3 8l7-5 5 2 5-4',cycles:'M12 2a10 10 0 1 1-10 10A10 10 0 0 1 12 2M12 6v2M12 16v2M6 12h2M16 12h2M10 10l4 4M14 10l-4 4',home:'M3 10 12 3l9 7M5 9v12h5v-7h4v7h5V9',sales:'M4 5h16v16H4zM8 2v6M16 2v6M8 12h8M8 16h5',machines:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M10 3h4l1 3 3 1 3-1 2 4-2 2v3l2 2-2 4-3-1-3 1-1 3h-4l-1-3-3-1-3 1-2-4 2-2v-3l-2-2 2-4 3 1 3-1z',tombola:'m3 8 15-4 3 12-15 4-1-4a3 3 0 0 0-1-6zM12 7l2 10',history:'M12 3a9 9 0 1 1-9 9 9 9 0 0 1 9-9M12 7v5l3 2',team:'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M2 21v-3a7 7 0 0 1 14 0v3M17 4a4 4 0 0 1 0 7M19 15a5 5 0 0 1 3 4v2',barrel:'M7 3h10c4 5 4 13 0 18H7C3 16 3 8 7 3M5 7h14M5 17h14M9 4v16M15 4v16'};
const icon=name=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.home}"/></svg>`;
const $=selector=>document.querySelector(selector);
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=value=>new Intl.NumberFormat('fr-FR',{maximumFractionDigits:2}).format(value)+' $';
const date=value=>new Intl.DateTimeFormat('fr-BE',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:BOT_RULES.timeZone}).format(new Date(value));
const DURATION=BOT_RULES.machineDurationMinutes*60*1000;let activePage='overview',formMode='',currentId=null,search='',machineSearch='',machineFilter='all',salesScope='current',tombolaWeek='',machineStatsWeek='current',toastTimer;
function seed(){return {version:1,sales:[],machines:[],events:[],raffles:[],tombolaRecords:[],catalog:{voitures:[],motos:[]},salesWeek:{archives:[],lastResetDate:null},allocations:{}};}
function load(){return seed();}
let state=load();
const pageOffsets={sales:0,events:0,machines:0,tombola:0,history:0,team:0,sheets:0};
function pagination(key){const p=state.pagination?.[key];if(!p||p.total<=p.limit)return '';return `<div class="list-pagination" aria-label="Pagination"><span>${p.offset+1}–${Math.min(p.offset+p.limit,p.total)} sur ${p.total}</span><button class="button glass" type="button" data-page-offset="${key}" data-offset="${Math.max(0,p.offset-p.limit)}" ${p.offset?'':'disabled'}>← Précédent</button><button class="button glass" type="button" data-page-offset="${key}" data-offset="${p.offset+p.limit}" ${p.hasMore?'':'disabled'}>Suivant →</button></div>`;}
// Récupère les deux anciens exemples simultanés du prototype sans perdre leur copie.
function migrateBatchExamples(data){
 if(data.machineModel==='batch-v1')return;
 const original=['021','022','023'].map(id=>data.machines.find(m=>m.id===id));
 if(original.every(Boolean)&&original[1].start-original[0].start===-92*60000&&original[2].start-original[0].start===54*60000){
  const obsolete=original.slice(0,2).filter((m,i)=>!m.recovered&&!m.cancelled&&!m.recoveredAt&&m.amount===1000000&&m.launchedBy===["Tom Kerrigan","Lily"][i]);
  if(obsolete.length){data.previousDemoMachineExamples=[...(data.previousDemoMachineExamples||[]),...obsolete];data.machines=data.machines.filter(m=>!obsolete.includes(m));}
 }
 for(const m of data.machines){m.machineCount??=BOT_RULES.machineCount;m.nominalUnitAmount??=BOT_RULES.machineUnitAmount;}
 data.machineModel='batch-v1';
}
migrateBatchExamples(state);
state.tombolaRecords??=[];state.catalog??={voitures:[],motos:[]};
// Les anciennes marques d’archive restent consultables sans déplacer les dossiers.
state.salesWeek??={archives:[],lastResetDate:null};
for(const name of new Set(state.sales.map(s=>s.archive).filter(Boolean))){
 if(!state.salesWeek.archives.some(a=>a.name===name))state.salesWeek.archives.push({name,closedAt:null,mode:'legacy'});
}
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),4200);}
let localIdCounter=0;
function localId(){return typeof crypto!=='undefined'&&typeof crypto.randomUUID==='function'?crypto.randomUUID():`${Date.now().toString(36)}-${++localIdCounter}-${Math.random().toString(36).slice(2)}`;}
function allocations(){return new Map(Object.entries(state.allocations||{}));}
function saleProgress(s){const treated=allocations().get(s.id)||0;return{treated,percent:Math.min(100,Math.round(treated/s.amount*100)),known:s.progressKnown!==false};}
const pages={overview:['Tableau de bord','L’HÉRITAGE<span class="domain-subtitle">— LE DOMAINE —</span>','Tradition · Passion · Excellence','home'],sales:['Gestion Blanchiments','Les dossiers<br>du domaine<span>.</span>','Chaque affaire a son histoire. Gardons le fil.','sales'],machines:['Gestion Machines','Le temps fait<br>son œuvre<span>.</span>','Un cycle de 4 h 45. Chaque récupération compte.','machines'],tombola:['Véhicule tombola','Le goût<br>du privilège<span>.</span>','Les véhicules du domaine. Des achats aux paiements.','tombola'],history:['Historique','La mémoire<br>des affaires<span>.</span>','Les mouvements du domaine, dans les moindres détails.','history'],stats:['Statistiques','Les chiffres<br>du domaine<span>.</span>','L’organisation aujourd’hui. La liberté demain.','sales'],journal:['Journal permanent','La mémoire<br>du domaine<span>.</span>','Les actions restent dans le registre.','history'],team:['Équipe','Les visages<br>de la famille<span>.</span>','La confiance se cultive. La loyauté se reconnaît.','team']};
$('#navigation').innerHTML=['overview','sales','machines','tombola','history','stats','team'].map(id=>[id,pages[id]]).map(([id,p])=>`<a href="#${id}" data-page="${id}">${icon(p[3])}<span>${p[0]}</span></a>`).join('');$('#home-icon').innerHTML=icon('home');
function saleExpired(s){return Date.now()-s.created>=BOT_RULES.activeDays*86400000;}
function badge(s){const p=saleProgress(s);if(s.status==='cancelled')return'<span class="badge wait">Annulé</span>';if(s.status==='finished')return'<span class="badge done">Restitué</span>';return p.percent===100?'<span class="badge done">À restituer</span>':`<span class="badge ${p.percent?'':'wait'}">${s.manualStatus==='progress'||p.percent?'En cours':'En attente'}</span>`;}
function dossier(s,expanded=false){const p=saleProgress(s),gold=s.group==='Zhovta Krov';return`<article class="dossier ${s.status==='cancelled'?'cancelled':''}"><div class="seal ${gold?'gold':''}">${gold?'♜':'✥'}</div><div><div class="dossier-top"><h3>${escapeHTML(s.group)}</h3>${badge(s)}</div><p class="dossier-id">DOSSIER #${escapeHTML(s.id)} · ${escapeHTML(s.employee)}</p><div class="dossier-amount">${money(s.amount)} <small>${money(Math.max(0,s.amount-p.treated))} restants</small></div><div class="progress-line"><div class="progress ${gold?'gold-progress':''}" role="progressbar" aria-label="Progression ${escapeHTML(s.group)}" aria-valuenow="${p.percent}" aria-valuemin="0" aria-valuemax="100"><i style="width:${p.percent}%"></i></div><span>${p.percent} %</span></div>${expanded?`<div class="sale-split"><span>Entreprise · 15 %<strong>${money(splitAmounts(s.amount).company)}</strong></span><span>Groupe · 80 %<strong>${money(splitAmounts(s.amount).group)}</strong></span><span>Perte · 5 %<strong>${money(splitAmounts(s.amount).loss)}</strong></span></div><p class="sale-metadata">Date reçue : ${escapeHTML(s.receivedDate||'Non renseignée')}${s.receiver?`<br>Restitution : ${escapeHTML(s.receiver)} · ${escapeHTML(s.returnedDate)}`:''}${s.archive?`<br>Archive du ${escapeHTML(s.archive)}`:''}${saleExpired(s)?'<br>Actions expirées après 365 jours.':''}</p>`:''}${expanded&&s.status!=='cancelled'&&!saleExpired(s)?`<div class="finish-actions"><button data-action="finish-sale" data-id="${escapeHTML(s.id)}" >Terminer / restituer</button><button data-action="sale-waiting" data-id="${escapeHTML(s.id)}">En attente</button><button data-action="sale-progress" data-id="${escapeHTML(s.id)}">En cours</button><button class="danger" data-action="cancel-sale" data-id="${escapeHTML(s.id)}">Annuler</button></div>`:''}</div><button class="circle-button" data-action="sale-detail" data-id="${escapeHTML(s.id)}" aria-label="Voir le dossier ${escapeHTML(s.id)}">↗</button></article>`;}
function remaining(m){return Math.max(0,m.start+DURATION-Date.now());}
function countdown(m){if(m.recovered)return'Récupérée';const n=Math.ceil(remaining(m)/1000);if(!n)return'00:00:00';return`${String(Math.floor(n/3600)).padStart(2,'0')}:${String(Math.floor(n/60)%60).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;}
function grapeMark(){return '<svg class="cycle-grape" viewBox="0 0 32 38" aria-hidden="true"><g fill="currentColor" stroke="none"><ellipse cx="20" cy="4" rx="7" ry="3" transform="rotate(-30 20 4)"/><circle cx="9" cy="14" r="4"/><circle cx="19" cy="14" r="4"/><circle cx="5" cy="22" r="4"/><circle cx="14" cy="22" r="4"/><circle cx="23" cy="22" r="4"/><circle cx="10" cy="30" r="4"/><circle cx="19" cy="30" r="4"/><circle cx="14.5" cy="36" r="3"/></g></svg>';}
function gauge(m){const p=m.recovered?100:cyclePercent(m);return `<div class="cycle-dial" data-gauge="${escapeHTML(m.id)}" style="--percent:${p}%;--cycle-angle:${p*3.6}deg"><div class="dial-outer" aria-hidden="true"></div><div class="dial-track" aria-hidden="true"></div><div class="dial-orbit" aria-hidden="true"><i></i></div><div class="dial-core">${grapeMark()}<small>TEMPS RESTANT</small><time data-countdown="${escapeHTML(m.id)}">${countdown(m)}</time><span>CYCLE DE 4 H 45</span></div></div>`;}

function metrics(){const a=allocations();const open=state.sales.filter(s=>s.status==='active');const pending=open.reduce((n,s)=>n+Math.max(0,s.amount-(a.get(s.id)||0)),0);const treated=state.sales.filter(s=>s.status!=='cancelled').reduce((n,s)=>n+(a.get(s.id)||0),0);const restitute=open.filter(s=>(a.get(s.id)||0)>=s.amount).reduce((n,s)=>n+splitAmounts(s.amount).group,0);return`<div class="metrics"><div class="metric-feature"><div class="metric-label">À blanchir</div><div class="metric-value">${money(pending)}</div><div class="metric-foot">↗ <b>${open.length} dossiers ouverts</b> au sein du domaine</div></div><div class="metric-strip"><div class="metric-small"><div class="metric-label">Montant blanchi · démo</div><div class="metric-value">${money(treated)}</div><svg class="sparkline" viewBox="0 0 200 30" preserveAspectRatio="none" aria-hidden="true"><path d="M0 25 Q15 20 30 22 T60 15 T90 19 T120 10 T150 12 T180 4 L200 7"/></svg></div><div class="metric-small"><div class="metric-label">À restituer</div><div class="metric-value">${money(restitute)}</div><svg class="sparkline rose" viewBox="0 0 200 30" preserveAspectRatio="none" aria-hidden="true"><path d="M0 22 Q15 17 30 20 T60 14 T90 7 T120 13 T150 9 T180 18 L200 14"/></svg></div></div></div>`;}
function cyclePercent(m){return Math.min(100,Math.max(0,(1-remaining(m)/DURATION)*100));}
function activeBatch(){return [...state.machines].filter(m=>!m.recovered&&!m.cancelled&&!m.historical&&!m.trackingDisabled).sort((a,b)=>b.start-a.start)[0]||null;}
function refreshMachineControls(){
 const records=[...state.machines,...(state.machineHistory||[])],active=activeBatch();
 document.querySelectorAll('[data-cycle-recover]').forEach(button=>{
  const machine=records.find(m=>m.id===button.dataset.cycleRecover);
  const blocked=!machine||machine.cancelled||machine.recovered||remaining(machine)>0;
  button.disabled=blocked||button.getAttribute('aria-busy')==='true';
  button.title=blocked?'Disponible à la fin du compteur de 4 h 45.':'';
 });
 document.querySelectorAll('[data-action="add-machine"]').forEach(button=>{
  button.disabled=Boolean(active)||button.getAttribute('aria-busy')==='true';
  button.title=active?'Récupère le lot précédent avant d’en lancer un nouveau.':'';
 });
 document.querySelectorAll('[data-cycle-state]').forEach(label=>{
  const machine=records.find(m=>m.id===label.dataset.cycleState);
  if(machine)label.textContent=remaining(machine)>0?'En cours':'À récupérer';
 });
}
function midnightMachine(m,index=0){return `<article class="night-machine counter-machine batch-card cut-frame"><div class="cut-inner"><div class="batch-main"><div class="batch-left"><div class="batch-wordmark">L’HÉRITAGE${grapeMark()}<span>LES AFFAIRES DE LA FAMILLE</span></div><div class="batch-identity"><h3>Lot #${escapeHTML(m.id)}</h3><span class="counter-status" data-cycle-state="${escapeHTML(m.id)}">${remaining(m)?'En cours':'À récupérer'}</span></div><div class="batch-total"><small>MONTANT TOTAL DU LOT</small><strong>${money(m.amount)}</strong><span>${BOT_RULES.machineCount} machines · un seul cycle</span></div></div><div class="batch-center">${gauge(m)}</div><dl class="batch-details"><div><dt>CHARGE HABITUELLE</dt><dd>${BOT_RULES.machineCount} × ${money(BOT_RULES.machineUnitAmount)}</dd></div><div><dt>LANCÉ PAR</dt><dd>${escapeHTML(m.launchedBy||'Non renseigné')}</dd></div><div><dt>FIN PRÉVUE · BRUXELLES</dt><dd>${date(m.start+DURATION)}</dd></div></dl></div><div class="batch-footer"><div class="batch-footer-actions"><a href="#machines">Voir le lot <span>→</span></a><button data-action="recover" data-id="${escapeHTML(m.id)}" data-cycle-recover="${escapeHTML(m.id)}">Tout récupérer <span>→</span></button></div></div></div></article>`;}

function saleContactText(s){return `Donneur : ${s.giver||'Non renseigné'} · Date reçue : ${s.receivedDate||'Non renseignée'}`;}
async function copySaleContact(s){
 const text=saleContactText(s);
 try{
  if(!navigator.clipboard?.writeText)throw Error('Presse-papiers indisponible');
  await navigator.clipboard.writeText(text);
 }catch{
  const input=document.createElement('textarea');input.value=text;input.readOnly=true;
  input.style.cssText='position:fixed;left:-9999px;top:0';document.body.append(input);
  const previous=document.activeElement;
  try{input.select();if(!document.execCommand('copy'))throw Error('Copie refusée');}
  catch{toast('Sélectionne les informations du dossier puis utilise Ctrl + C.');return;}
  finally{input.remove();previous?.focus({preventScroll:true});}
 }
 toast('Donneur et date reçue copiés.');
}
function midnightDossier(s,index){
 const p=saleProgress(s),split=splitAmounts(s.amount),editable=s.status!=='cancelled'&&!saleExpired(s);
 return `<details class="night-dossier sale-record cut-frame ${s.status==='cancelled'?'cancelled':''}"><summary class="cut-inner"><span class="night-dossier-photo dossier-photo-${index%3}" aria-hidden="true"></span><span class="night-dossier-id">#${escapeHTML(s.id)}</span><span class="night-dossier-name"><span class="sale-group-name">${escapeHTML(s.group)}</span><span class="sale-row-caption">${escapeHTML(s.employee)} · ${p.known?p.percent+' % traité':'Progression non renseignée'}</span><span class="sale-row-contact"><span class="sale-contact-text">${escapeHTML(saleContactText(s))}</span><button type="button" class="sale-copy" data-action="copy-sale-contact" data-id="${escapeHTML(s.id)}" aria-label="Copier le donneur et la date reçue du dossier ${escapeHTML(s.id)}">Copier</button></span></span><span class="night-dossier-amount"><strong>${money(s.amount)}</strong><span>À blanchir</span></span>${badge(s)}<span class="sale-chevron" aria-hidden="true">›</span></summary><div class="sale-record-details"><div class="sale-detail-grid"><div><small>MONTANT TRAITÉ</small><strong>${p.known?money(p.treated):'Non renseigné'}</strong><span>${p.known?money(Math.max(0,s.amount-p.treated))+' restants':'Progression absente des archives Google'}</span></div><div><small>ENTREPRISE · 15 %</small><strong>${money(split.company)}</strong></div><div><small>GROUPE · 80 %</small><strong>${money(split.group)}</strong></div><div><small>PERTE · 5 %</small><strong>${money(split.loss)}</strong></div></div><p class="sale-metadata">Donneur : ${escapeHTML(s.giver||'Non renseigné')} · Date reçue : ${escapeHTML(s.receivedDate||'Non renseignée')}${s.receiver?`<br>Restitution : ${escapeHTML(s.receiver)} · ${escapeHTML(s.returnedDate)}`:''}${s.archive?`<br>Archive du ${escapeHTML(s.archive)}`:''}${saleExpired(s)?'<br>Actions expirées après 365 jours.':''}</p><div class="finish-actions">${!saleExpired(s)?`<button data-action="sale-detail" data-id="${escapeHTML(s.id)}">${editable?'Modifier le dossier':'Voir le dossier'}</button>`:''}${editable?`<button data-action="finish-sale" data-id="${escapeHTML(s.id)}">Terminer / restituer</button><button data-action="sale-waiting" data-id="${escapeHTML(s.id)}">En attente</button><button data-action="sale-progress" data-id="${escapeHTML(s.id)}">En cours</button><button class="danger" data-action="cancel-sale" data-id="${escapeHTML(s.id)}">Annuler</button>`:''}</div></div></details>`;
}
function overview(){
 const current=activeBatch(),active=current?[current]:[],totals=state.summary||{},treated=totals.treated||0,pending=totals.pending||0;
 const cards=[['À blanchir',money(pending),'funds',totals.gross?pending/totals.gross*100:0],['Montant traité',money(treated),'treated',totals.gross?treated/totals.gross*100:0],['Gain entreprise estimé',money(totals.company),'gain',15],['Machines en activité',String(current?BOT_RULES.machineCount:0),'cycles',current?100:0]];
 return `<section class="night-metrics cut-frame" aria-label="Indicateurs du domaine"><div class="cut-inner">${cards.map(([label,value,symbol,percent],i)=>`<article class="night-metric">${icon(symbol)}<div><span>${label}</span><strong>${value}</strong><div class="progress ${i===0?'red-progress':''}" aria-hidden="true"><i style="width:${Math.min(100,percent)}%"></i></div></div></article>`).join('')}</div></section>
 <section class="night-machines"><div class="night-section-heading"><h2>Cycle du lot de machines</h2><div class="night-heading-actions"><button data-action="add-machine">＋ Lancer un lot</button><a href="#machines">Tout voir <span>↗</span></a></div></div><div class="night-machine-grid">${active.map(midnightMachine).join('')||'<p class="empty">Aucun lot actif. Lancez les 5 machines ensemble.</p>'}</div></section>
`;
}

function salesActivity(){return `<section class="night-activity sales-activity"><div class="night-section-heading"><h2>Journal des opérations <span></span></h2><span class="section-label">${state.events.length} MOUVEMENTS</span></div><ol class="night-event-list">${state.events.map(e=>`<li><span class="event-dot"></span><time>${date(e.created)}</time>${icon('history')}<div><h3>${escapeHTML(e.title)}</h3><p>${escapeHTML(e.detail)}</p><small class="activity-author">${escapeHTML(e.author||'Non renseigné')}</small></div></li>`).join('')||'<li>Aucune opération pour le moment.</li>'}</ol>${pagination('events')}</section>`;}
function selectedSales(){return state.sales.filter(s=>salesScope==='all'||(salesScope==='open'?s.status==='active':salesScope==='current'?!s.archive:s.archive===salesScope));}
function salesArchiveLabel(archive){return archive?.year&&archive?.week?`s${String(archive.week).padStart(2,'0')} · ${archive.year}${archive.sequence>1?` · clôture ${archive.sequence}`:''}`:archive?.name||'';}
function salesWeekOptions(){return [['current','En cours'],['open','Tous les dossiers ouverts'],['all','Tous les dossiers'],...[...state.salesWeek.archives].reverse().map(a=>[a.name,`Archive ${salesArchiveLabel(a)}`])].map(([value,label])=>`<option value="${escapeHTML(value)}" ${salesScope===value?'selected':''}>${escapeHTML(label)}</option>`).join('');}
function salesWeekSummary(){
 const selected=selectedSales(),totals=state.scopeTotals||financeTotals(selected),archive=state.salesWeek.archives.find(a=>a.name===salesScope);
 const current=salesWeekPeriod(Date.now());
 const title=salesScope==='current'?`En cours · s${String(current.week).padStart(2,'0')} · ${current.year}`:salesScope==='open'?'Tous les dossiers ouverts':salesScope==='all'?'Tous les dossiers':`Archive ${salesArchiveLabel(archive)}`;
 return `<section class="sales-week-panel" aria-label="Suivi de la semaine"><div class="sales-week-heading"><div><p class="eyebrow">GESTION DU SALE</p><h2>${escapeHTML(title)}</h2><p>${state.scopeCount??selected.length} dossier(s)${archive?.closedAt?` · archivée le ${date(archive.closedAt)}`:''}</p></div><label class="field">Afficher<select id="sales-week">${salesWeekOptions()}</select></label></div><dl class="sales-week-totals"><div><dt>Somme à blanchir</dt><dd>${money(totals.gross)}</dd></div><div><dt>Entreprise · 15 %</dt><dd>${money(totals.company)}</dd></div><div><dt>Groupes · 80 %</dt><dd>${money(totals.group)}</dd></div><div><dt>Perte · 5 %</dt><dd>${money(totals.loss)}</dd></div></dl><p class="sales-reset-note">Environnement de test indépendant · les archives de cette version ne modifient pas le bot ni Google Sheets.</p></section>`;
}
function salesPage(){return`<div class="toolbar"><button class="button primary" data-action="add-sale">＋ Ajouter du sale</button><button class="button glass" data-action="archive-sales">Reset semaine</button><input id="sale-search" type="search" placeholder="Rechercher un groupe, un employé…" aria-label="Rechercher les sales" value="${escapeHTML(search)}"></div>${salesWeekSummary()}<section class="night-dossiers sales-dossiers"><div class="night-section-heading"><h2>Dossiers du domaine <span></span></h2><span class="section-label">Clique sur un dossier pour le gérer</span></div><div class="night-dossier-list sales-list" id="sale-results">${saleResults()}</div>${pagination('sales')}<a class="night-stat-link" href="#stats">Répartition : entreprise 15 % · groupes 80 % · perte 5 % <span>↗</span></a></section>${salesActivity()}`;}

function saleResults(){const filtered=selectedSales().filter(s=>(s.group+' '+s.employee+' '+s.id+' '+s.giver).toLocaleLowerCase('fr').includes(search.toLocaleLowerCase('fr'))).sort((a,b)=>b.created-a.created||Number(b.id)-Number(a.id));return filtered.map(midnightDossier).join('')||(search?'<p class="empty">Aucun dossier ne correspond à cette recherche.</p>':'<p class="empty">Aucun dossier dans cette vue. Les anciens dossiers restent accessibles dans les archives et « Tous les dossiers ouverts ».</p>');}
function machineStatus(m){return m.cancelled?'cancelled':m.recovered?'recovered':m.historical||m.trackingDisabled?'unconfirmed':remaining(m)===0?'ready':'running';}
function machineHistoryRows(){
 const filtered=[...(state.machineHistory||state.machines)].sort((a,b)=>b.start-a.start).filter(m=>{
  const text=[m.id,m.launchedBy||'',m.recoveredBy||''].join(' ').toLocaleLowerCase('fr');
  return text.includes(machineSearch.toLocaleLowerCase('fr'))&&(machineFilter==='all'||machineStatus(m)===machineFilter);
 });
 return filtered.map(m=>{const status=machineStatus(m);return `<tr><td>#${escapeHTML(m.id)}</td><td><span class="operator-name">${escapeHTML(m.launchedBy||'Non renseigné')}</span></td><td>${money(m.amount)}</td><td>${date(m.start)}</td><td>${date(m.start+DURATION)}</td><td><span class="badge ${status==='ready'?'wait':''}">${status==='cancelled'?'Annulée':status==='recovered'?'Récupérée':status==='unconfirmed'?'Historique · non confirmé':status==='ready'?'À récupérer':'En cours'}</span></td><td>${m.recovered&&!m.cancelled?escapeHTML(m.recoveredBy||'Non renseigné'):'—'}<small class="recovery-date">${m.recovered&&m.recoveredAt?date(m.recoveredAt):''}</small></td><td>${!m.cancelled?`<div class="record-actions"><button data-action="edit-machine-time" data-id="${escapeHTML(m.id)}">Modifier l’heure</button><button data-action="${m.recovered?'unrecover':'recover'}" data-id="${escapeHTML(m.id)}" ${m.recovered?'':`data-cycle-recover="${escapeHTML(m.id)}"`}>${m.recovered?'Non récupérée':'Récupérée'}</button><button data-action="cancel-machine" data-id="${escapeHTML(m.id)}">Annuler</button></div>`:'—'}</td></tr>`;}).join('')||'<tr><td colspan="8" class="empty">Aucun lot ne correspond à ces filtres.</td></tr>';
}
function machinesPage(){
 const current=activeBatch(),active=current?[current]:[];
 const recovered=state.machines.filter(m=>m.recovered&&!m.cancelled);
 return `<p class="demo-notice">Les 5 machines partent ensemble et se récupèrent ensemble : un lancement correspond à un lot global. Charge habituelle : 200 000 $ par machine, soit 1 000 000 $ au total. Le montant global peut être corrigé au lancement.</p>
 <div class="machine-summary"><div><strong>${current?BOT_RULES.machineCount:0} / ${BOT_RULES.machineCount}</strong><span>machines · ${current?'1 lot actif':'aucun lot actif'}</span></div><div><strong>${state.machineSummary?.recovered??recovered.length}</strong><span>lots récupérés</span></div><div><strong>${money(state.machineSummary?.amount??recovered.reduce((sum,m)=>sum+m.amount,0))}</strong><span>montant total des lots récupérés</span></div></div>
 <div class="panel-header"><div><h2>Le lot en cours</h2><p>5 machines · un seul compteur de 4 h 45 · récupération groupée</p></div><button class="button glass" data-action="add-machine">＋ Lancer un lot</button></div>
 <div class="machine-list batch-list">${active.map(midnightMachine).join('')||'<p class="empty">Aucun lot actif. Les lancements précédents restent dans le registre.</p>'}</div>
 <section class="panel machine-history"><div class="panel-header"><div><h2>Historique des lots</h2><p>Un lancement = 5 machines · auteur, montant et récupération conservés</p></div><span class="section-label">${state.pagination?.machines?.total??state.machines.length} LOTS</span></div>
 <div class="machine-history-filters"><label>Rechercher<input id="machine-search" type="search" placeholder="Nom, numéro de lot…" value="${escapeHTML(machineSearch)}"></label><label>Statut<select id="machine-status"><option value="all" ${machineFilter==='all'?'selected':''}>Tous les lots</option><option value="running" ${machineFilter==='running'?'selected':''}>En cours</option><option value="ready" ${machineFilter==='ready'?'selected':''}>À récupérer</option><option value="recovered" ${machineFilter==='recovered'?'selected':''}>Récupérés</option><option value="cancelled" ${machineFilter==='cancelled'?'selected':''}>Annulés</option></select></label></div>
 <div class="table-wrap"><table class="history-table machine-history-table"><thead><tr><th>Lot</th><th>Lancé par</th><th>Montant total</th><th>Lancement</th><th>Fin prévue</th><th>Statut</th><th>Récupéré par / le</th><th>Gestion</th></tr></thead><tbody id="machine-history-rows">${machineHistoryRows()}</tbody></table></div>${pagination('machines')}</section>${machineSheetArchive()}`;
}
function machineSheetArchive(){const rows=state.machineSheetHistory||[],count=state.sheetCount??rows.length;if(!count)return '';return `<details class="panel machine-sheet-archive"><summary>Archives Google Sheets · ${count} lignes</summary><div id="sheet-archive-content"><p class="empty">Ouvre les archives pour charger leur contenu.</p></div></details>`;}
function sheetArchiveContent(){const rows=state.machineSheetHistory||[];return `<p class="form-note">Lancements conservés dans les tableaux du bot. La récupération n’est pas déduite de ces lignes.</p><div class="table-wrap"><table class="history-table"><thead><tr><th>Archive</th><th>Date</th><th>Heure</th><th>Employé</th><th>Montant</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${escapeHTML(row.sheet)} · ${row.row}</td><td>${escapeHTML(row.date||'Non renseignée')}</td><td>${escapeHTML(row.time||'—')}</td><td>${escapeHTML(row.launchedBy)}</td><td>${money(row.amount)}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">Aucune archive à afficher.</td></tr>'}</tbody></table></div>${pagination('sheets')}`;}

function tombolaPage(){
 const weeks=[...new Set(state.tombolaWeeks||[weekKey(),...state.tombolaRecords.map(r=>r.week)])].sort().reverse();const selected=tombolaWeek||weekKey();
 const records=state.tombolaRecords.filter(r=>r.week===selected);
 return `<p class="demo-notice">Gestion des véhicules : fiches par semaine, catalogue voitures/motos, achats et paiements.</p><div class="toolbar"><button class="button primary" data-action="raffle-record">Préparer une fiche</button><label class="field">Semaine<select id="tombola-week">${weeks.map(w=>`<option value="${escapeHTML(w)}" ${w===selected?'selected':''}>Semaine du ${escapeHTML(w.split('-').reverse().join('/'))}</option>`).join('')}</select></label></div><div class="raffle-grid">${records.map(r=>{
 const total=r.vehicles.reduce((n,v)=>n+(v.price||0),0),paid=r.vehicles.filter(v=>v.paid).reduce((n,v)=>n+(v.price||0),0),unknown=r.vehicles.some(v=>v.price==null);
 return `<article class="raffle"><p class="eyebrow">SEMAINE DU ${escapeHTML(r.week)}</p><h3>Les véhicules du domaine</h3>${r.vehicles.map((v,i)=>`<div class="vehicle-summary"><h4>${i+1}. ${escapeHTML(v.name)} <small>${escapeHTML(v.type)}</small></h4><p>${v.price==null?'En attente de prix':money(v.price)}</p><div class="record-actions"><button data-action="vehicle-buy" data-id="${escapeHTML(r.id)}|${i}">${v.bought?'Acheté ✓':'À acheter'}</button><button data-action="vehicle-pay" data-id="${escapeHTML(r.id)}|${i}">${v.paid?'Payé ✓':'Paiement en attente'}</button></div></div>`).join('')}<p>Total connu : ${money(total)}<br>Déjà payé : ${money(paid)}<br>Reste à payer : ${money(total-paid)}${unknown?'<br>Certains prix restent à renseigner.':''}</p><div class="record-actions"><button data-action="pay-all" data-id="${escapeHTML(r.id)}">Tout payer</button><button data-action="reset-payments" data-id="${escapeHTML(r.id)}">Tout remettre en attente</button><button data-action="raffle-record" data-id="${escapeHTML(r.id)}">Modifier véhicules / prix</button></div></article>`;
 }).join('')||'<p class="empty">Aucune fiche pour cette semaine. Préparez au moins deux véhicules.</p>'}</div>${pagination('tombola')}<datalist id="vehicle-catalog">${[...new Set([...state.catalog.voitures,...state.catalog.motos])].map(name=>`<option value="${escapeHTML(name)}"></option>`).join('')}</datalist>`;
}

function historyPage(){return`<section class="panel"><div class="panel-header"><div><h2>Le registre du domaine</h2><p>${state.pagination?.history?.total??state.events.length} mouvements</p></div><button class="text-link" data-action="export">Exporter en CSV ↗</button></div><div class="table-wrap"><table class="history-table"><thead><tr><th>Date</th><th>Opération</th><th>Détails</th><th>Auteur</th></tr></thead><tbody>${state.events.map(e=>`<tr><td>${date(e.created)}</td><td>${escapeHTML(e.title)}</td><td>${escapeHTML(e.detail)}</td><td>${escapeHTML(e.author)}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">Aucun mouvement pour le moment. Les prochaines opérations apparaîtront ici.</td></tr>'}</tbody></table></div>${pagination('history')}</section>`;}
function teamPage(){return `<div class="team-grid">${(state.members||[]).map(m=>`<article class="panel member"><span class="avatar member-avatar"><span ${m.avatar?'aria-hidden="true"':''}>${escapeHTML(m.displayName.slice(0,2))}</span>${m.avatar?`<img src="${escapeHTML(m.avatar)}" alt="Photo de profil de ${escapeHTML(m.displayName)}" loading="lazy" decoding="async">`:''}</span><h3>${escapeHTML(m.displayName)}</h3><p>${escapeHTML(m.discordName)}</p></article>`).join('')||'<p class="empty">Aucun compte à afficher.</p>'}</div>${pagination('team')}`;}
$('#content').addEventListener('error',e=>{const image=e.target;if(!image.matches?.('.member-avatar img'))return;const initials=image.parentElement.querySelector('span');initials?.removeAttribute('aria-hidden');image.remove();},true);
function updatePageContent(markup){
 const content=$('#content'),template=document.createElement('template');template.innerHTML=markup;
 const existing=[...content.childNodes],incoming=[...template.content.childNodes];
 incoming.forEach((node,index)=>{
  const previous=existing[index];
  if(previous?.isEqualNode(node))return;
  if(previous)previous.replaceWith(node);else content.append(node);
 });
 existing.slice(incoming.length).forEach(node=>node.remove());
}
function updatePageHeading(route,label){
 const p=pages[route];label=label||p?.[0]||'Le domaine';
 $('body').classList.toggle('dashboard-active',route==='overview');$('#breadcrumb').textContent=label;
 if(p)$('#page-title').innerHTML=p[1];else $('#page-title').textContent=label;
 $('#page-subtitle').textContent=p?.[2]||'';document.title=`${label} — L’Héritage`;
 document.querySelectorAll('[data-page]').forEach(el=>{const selected=el.dataset.page===route;el.classList.toggle('active',selected);if(selected)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
}
function render({incremental=false}={}){updatePageHeading(activePage);const markup=({overview,sales:salesPage,machines:machinesPage,tombola:tombolaPage,history:historyPage,team:teamPage,stats:statsPage}[activePage])();if(incremental)updatePageContent(markup);else $('#content').innerHTML=markup;refreshMachineControls();}
function navigate(){if(window.heritageNavigate){void window.heritageNavigate();return;}$('#entry-screen').hidden=false;$('main').hidden=true;$('#sidebar').hidden=true;$('body').classList.add('on-entry');}
document.addEventListener('click',event=>{
 const link=event.target.closest('a[href^="#"]');
 if(!link||event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
 // The GitHub entry uses a base URL for assets; routes stay on the current page.
 event.preventDefault();location.hash=link.getAttribute('href');
});
function closeMenu(){$('#sidebar').classList.remove('open');$('#scrim').classList.remove('visible');$('#menu-toggle').setAttribute('aria-expanded','false');}
window.addEventListener('hashchange',navigate);$('#menu-toggle').addEventListener('click',()=>{const open=$('#sidebar').classList.toggle('open');$('#scrim').classList.toggle('visible',open);$('#menu-toggle').setAttribute('aria-expanded',String(open));});$('#scrim').addEventListener('click',closeMenu);document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMenu();});
function options(values,selected){return values.map(v=>`<option ${v===selected?'selected':''}>${escapeHTML(v)}</option>`).join('');}
const employees=Object.keys(BOT_RULES.employees);
function field(label,name,value='',attrs=''){return `<label class="field">${label}<input name="${name}" value="${escapeHTML(value)}" ${attrs}></label>`;}
function employeeField(name,selected){return `<label class="field">${name==='receiver'?'Qui récupère le sale ?':'Employé'}<select name="${name}">${(selected&&!employees.includes(selected)?[selected,...employees]:employees).map(employee=>`<option value="${escapeHTML(employee)}" ${employee===selected?'selected':''}>${escapeHTML(employee)}${BOT_RULES.employees[employee]?' · '+BOT_RULES.employees[employee]:''}</option>`).join('')}</select></label>`;}
function operationActor(sale=null){
 const user=window.heritageSession?.user,name=sale?.employee||user?.displayName||'Votre profil';
 const initials=name.trim().split(/\s+/).slice(0,2).map(part=>part[0]||'').join('').toLocaleUpperCase('fr');
 const avatar=(!sale||sale.employeeId===user?.id)&&user?.avatar;
 return `<div class="operation-actor" role="group" aria-label="Auteur de l’opération"><span class="operation-actor-avatar" aria-hidden="true">${avatar?`<img src="${escapeHTML(avatar)}" alt="">`:escapeHTML(initials)}</span><div><small>${sale?'Dossier créé par':'Opération effectuée par'}</small><strong>${escapeHTML(name)}</strong><span>${sale?'L’auteur du dossier reste conservé.':'Votre profil · attribution automatique'}</span></div></div>`;
}
function openForm(mode,id=null){
 if($('#entry-form').dataset.submitting==='true'){toast('L’opération précédente est encore en cours d’enregistrement.');return;}
 formMode=mode;currentId=id;
 const sale=state.sales.find(s=>s.id===id),machine=[...state.machines,...(state.machineHistory||[])].find(m=>m.id===id);
 if(mode==='add-machine'&&activeBatch()){toast('Récupère le lot précédent avant de lancer un nouveau lot.');return;}
 if(['sale-detail','finish-sale'].includes(mode)&&(!sale||saleExpired(sale))){toast('Cette fiche est absente ou ses actions ont expiré après 365 jours.');return;}
 let fields='',title='';
 if(mode==='add-sale'||mode==='sale-detail'){
  title=sale?`Dossier #${sale.id}`:'Une nouvelle affaire.';
  fields=`${operationActor(sale)}<label class="field">Groupe<select name="group">${options(sale?.group&&!BOT_RULES.groups.includes(sale.group)?[sale.group,...BOT_RULES.groups]:BOT_RULES.groups,sale?.group)}</select></label>${field('ID du joueur qui donne','giver',sale?.giver||'','inputmode="numeric" maxlength="20" required')}${field('Date reçue · vide = aujourd’hui','receivedDate',sale?.receivedDate||'',`placeholder="JJ/MM ou JJ/MM/AAAA" maxlength="10" ${sale?'required':''}`)}${field('Somme à blanchir ($)','amount',sale?.amount||'',`inputmode="numeric" maxlength="20" placeholder="${sale?'Montant obligatoire':'Vide = 5 000 000 $'}" ${sale?'required':''}`)}`;
 }else if(mode==='finish-sale'){
  title='Terminer le sale.';fields=`<p class="demo-notice">${escapeHTML(sale.group)} · ${money(sale.amount)}. La restitution est une confirmation manuelle, distincte de la progression automatique.</p>${employeeField('receiver',employees[0])}${field('Date rendu · vide = aujourd’hui','returnedDate','','placeholder="JJ/MM ou JJ/MM/AAAA" maxlength="10"')}`;
 }else if(mode==='edit-machine-time'){
  if(!machine||machine.cancelled)return;const p=brusselsParts(machine.start);title=`Heure du cycle #${machine.id}`;fields=field('Heure de lancement · même jour à Bruxelles','launchTime',`${p.hour}:${p.minute}`,'placeholder="HH:MM" required maxlength="5"');
 }else if(mode==='raffle-record'){
  const record=state.tombolaRecords.find(r=>r.id===id);title=record?'Modifier la fiche Tombola':'Préparer la tombola.';
  fields=`<div class="raffle-week-row"><div><p class="eyebrow">LA SÉLECTION DU DOMAINE</p><p>Les belles mécaniques font les belles soirées.</p></div>${field('Semaine de la tombola','weekDate',record?.week?record.week.split('-').reverse().join('/'):'','placeholder="JJ/MM ou JJ/MM/AAAA" maxlength="10"')}<small>Une date suffit. Laisse vide pour cette semaine.</small></div>`;
  const vehicles=record?.vehicles||[{},{}];fields+=`<div class="raffle-vehicle-grid" id="raffle-vehicle-grid">${vehicles.map((v,i)=>vehicleFields(v,i)).join('')}</div><button class="raffle-add-vehicle" type="button" data-action="extra-vehicle"><span aria-hidden="true">＋</span> Ajouter un véhicule <span class="raffle-add-limit">50 au maximum</span></button><div class="raffle-form-summary" aria-live="polite"><div><span>SÉLECTION</span><strong id="raffle-vehicle-count"></strong></div><div><span>MONTANT RENSEIGNÉ</span><strong id="raffle-known-total"></strong></div><p id="raffle-price-note"></p></div>`;
 }else{
  title='Lancer les 5 machines.';fields=`${operationActor()}${field('Montant TOTAL du lot ($)','amount','','inputmode="numeric" maxlength="20" placeholder="Vide = 1 000 000 $"')}<p class="demo-notice">5 machines × 200 000 $ = 1 000 000 $ habituellement. Vide = 1 000 000 $ au total, jamais par machine. Un seul compteur de 4 h 45. Corrige le montant total si nécessaire, dans la limite de 1 000 000 $.</p>`;
 }
 $('#dialog-title').textContent=title;$('#form-fields').innerHTML=fields;
 $('#form-dialog').classList.toggle('raffle-dialog',mode==='raffle-record');
 $('#entry-form .submit').innerHTML=mode==='raffle-record'?'Enregistrer la fiche <span>↗</span>':'Enregistrer <span>↗</span>';
 if(mode==='raffle-record')updateRaffleForm();
 const readOnly=mode==='sale-detail'&&sale.status==='cancelled';$('#entry-form .submit').hidden=readOnly;
 $('#form-fields').querySelectorAll('input,select').forEach(el=>el.disabled=readOnly);$('#form-dialog').showModal();
}
function vehicleMark(type='voiture'){return type==='moto'?'<svg viewBox="0 0 64 40" aria-hidden="true"><circle cx="13" cy="28" r="9"/><circle cx="51" cy="28" r="9"/><path d="m13 28 12-17 13 17H13m12-17h13l13 17M37 5h7l7 23M20 8h10M31 28l8-15"/></svg>':'<svg viewBox="0 0 64 40" aria-hidden="true"><path d="m7 20 7-12h34l8 12 3 3v10H5V23l2-3Zm0 0h49M18 8l-4 12m31-12 5 12M10 26h9m26 0h9M5 33v4h9v-4m36 0v4h9v-4M25 28h14"/></svg>';}
function vehicleFields(v,i){const type=v.type==='moto'?'moto':'voiture';return `<fieldset class="vehicle-fields raffle-vehicle" data-vehicle-index="${i}"><legend class="vehicle-legend">Véhicule ${i+1}</legend><div class="raffle-vehicle-heading"><span class="raffle-vehicle-mark">${vehicleMark(type)}</span><div><p class="eyebrow">VÉHICULE ${String(i+1).padStart(2,'0')}</p><h3 class="raffle-vehicle-title">${escapeHTML(v.name||'À sélectionner')}</h3></div><span class="raffle-vehicle-number" aria-hidden="true">${String(i+1).padStart(2,'0')}</span></div><div class="vehicle-type-picker" role="group" aria-label="Type du véhicule ${i+1}">${['voiture','moto'].map(kind=>`<label><input type="radio" name="type${i}" value="${kind}" ${type===kind?'checked':''}><span>${kind==='moto'?'Moto':'Voiture'}</span></label>`).join('')}</div>${field('Modèle du véhicule','vehicle'+i,v.name||'','required maxlength="100" data-vehicle-picker placeholder="Rechercher dans le catalogue…" autocomplete="off"')}<label class="field vehicle-price-field">Prix d’achat<span class="vehicle-price-input"><input name="price${i}" value="${escapeHTML(v.price??'')}" inputmode="numeric" placeholder="En attente de prix" maxlength="15"><span aria-hidden="true">$</span></span></label><p class="vehicle-price-help">Le prix peut être renseigné plus tard.</p></fieldset>`;}
function updateRaffleForm(){
 if(formMode!=='raffle-record')return;
 const cards=[...$('#form-fields').querySelectorAll('.raffle-vehicle')];let total=0,pending=0,invalid=0;
 for(const card of cards){const i=card.dataset.vehicleIndex,name=card.querySelector(`[name="vehicle${i}"]`).value.trim(),type=card.querySelector(`[name="type${i}"]:checked`).value;
  card.querySelector('.raffle-vehicle-title').textContent=name||'À sélectionner';card.querySelector('.raffle-vehicle-mark').innerHTML=vehicleMark(type);
  const price=card.querySelector(`[name="price${i}"]`).value.trim();if(!price)pending++;else try{total+=parseAmount(price,{allowZero:true});}catch{invalid++;}
 }
 $('#raffle-vehicle-count').textContent=`${cards.length} véhicules`;
 $('#raffle-known-total').textContent=money(total);
 $('#raffle-price-note').textContent=invalid?'Un prix est à vérifier.':pending?`${pending} prix en attente · tu peux enregistrer la fiche.`:'Tous les prix sont renseignés.';
 const add=$('#form-fields [data-action="extra-vehicle"]');add.disabled=cards.length>=50;
}
$('#form-fields').addEventListener('input',updateRaffleForm);
$('#close-dialog').addEventListener('click',()=>$('#form-dialog').close());$('#form-dialog').addEventListener('click',e=>{if(e.target===$('#form-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
$('#entry-form').addEventListener('submit',async e=>{
 e.preventDefault();if(e.target.dataset.submitting==='true'||!e.target.reportValidity())return;
 const values=Object.fromEntries(new FormData(e.target));
 const submit=e.target.querySelector('[type=submit]'),label=submit.innerHTML;e.target.dataset.submitting='true';submit.disabled=true;submit.setAttribute('aria-busy','true');submit.textContent='Enregistrement…';
 try{
  await window.heritageAction(formMode,currentId,values);
  $('#form-dialog').close();
 }catch(error){toast(error.message);}finally{delete e.target.dataset.submitting;submit.disabled=false;submit.removeAttribute('aria-busy');submit.innerHTML=label;}
});
$('#content').addEventListener('input',e=>{if(e.target.id==='machine-search'){machineSearch=e.target.value;window.heritageFilter?.('machines');}if(e.target.id==='sale-search'){search=e.target.value;window.heritageFilter?.('sales');}});
document.addEventListener('click',async e=>{
 if(e.target.closest('.sale-contact-text')&&window.getSelection()?.isCollapsed===false){e.preventDefault();return;}
 const b=e.target.closest('[data-action]');if(!b||b.disabled)return;
 const action=b.dataset.action,id=b.dataset.id;
 try{
  if(['add-sale','add-machine','sale-detail','finish-sale','edit-machine-time','raffle-record'].includes(action)){if(action==='raffle-record'){b.disabled=true;try{await window.heritageCatalog();}finally{b.disabled=false;}if(!b.isConnected||activePage!=='tombola')return;}openForm(action,id);return;}
  if(action==='extra-vehicle'){const container=$('#raffle-vehicle-grid');const count=container.querySelectorAll('.vehicle-fields').length;if(count<50){container.insertAdjacentHTML('beforeend',vehicleFields({},count));updateRaffleForm();const added=container.lastElementChild;added.querySelector(`[name="vehicle${count}"]`).focus({preventScroll:true});added.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}return;}
  if(action==='copy-sale-contact'){e.preventDefault();const sale=state.sales.find(s=>s.id===id);if(sale)await copySaleContact(sale);return;}
  if(action==='archive-sales'){$('#sales-reset-dialog').showModal();return;}
  if(action==='export'){
   const cell=v=>'"'+String(v).replace(/^(?=[\s\uFEFF]*[=+@-]|[\t\r\n])/,"'").replaceAll('"','""')+'"';
   const exported=await window.heritageHistoryExport();
   const csv='\uFEFF'+[['Date','Opération','Détails','Auteur'],...exported.map(e=>[new Date(e.created).toISOString(),e.title,e.detail,e.author])].map(row=>row.map(cell).join(';')).join('\r\n');
   const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='heritage-test-historique.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;
  }
  if(['cancel-sale','cancel-machine','reset-payments'].includes(action)&&!confirm('Confirmer cette modification ?'))return;
  b.disabled=true;b.setAttribute('aria-busy','true');
  try{await window.heritageAction(action,id,{});if(action==='confirm-sales-reset')$('#sales-reset-dialog').close();}
  finally{b.disabled=false;b.removeAttribute('aria-busy');}
 }catch(error){toast(error.message);}
});
$('#reset-demo').addEventListener('click',()=>window.heritageResetTestData?.());

setInterval(()=>{document.querySelectorAll('[data-countdown]').forEach(el=>{const m=state.machines.find(m=>m.id===el.dataset.countdown);if(!m)return;el.textContent=countdown(m);const gaugeEl=el.closest('[data-gauge]');if(gaugeEl){const p=m.recovered?100:cyclePercent(m);gaugeEl.style.setProperty('--percent',`${p}%`);gaugeEl.style.setProperty('--cycle-angle',`${p*3.6}deg`);}});refreshMachineControls();},1000);
function salesWeekPeriod(now,{previous=false}={}){
 const p=brusselsParts(now),day=new Date(Date.UTC(Number(p.year),Number(p.month)-1,Number(p.day)));
 if(previous)day.setUTCDate(day.getUTCDate()-1);
 day.setUTCDate(day.getUTCDate()+4-(day.getUTCDay()||7));
 const year=day.getUTCFullYear(),week=Math.ceil((((day-new Date(Date.UTC(year,0,1)))/86400000)+1)/7);
 return {year,week};
}

$('#cancel-sales-reset').addEventListener('click',()=>$('#sales-reset-dialog').close());

navigate();

$('#content').addEventListener('change',e=>{if(e.target.id==='machine-status'){machineFilter=e.target.value;pageOffsets.machines=0;void window.heritageNavigate({preserveFocus:true});}});
setInterval(()=>{if(activePage==='machines'&&$('#machine-history-rows'))$('#machine-history-rows').innerHTML=machineHistoryRows();},10000);

$('#content').addEventListener('change',e=>{if(e.target.id==='sales-week'){salesScope=e.target.value;pageOffsets.sales=0;pageOffsets.events=0;void window.heritageNavigate({preserveFocus:true});}if(e.target.id==='tombola-week'){tombolaWeek=e.target.value;pageOffsets.tombola=0;void window.heritageNavigate({preserveFocus:true});}if(e.target.id==='machine-stats-week'){machineStatsWeek=e.target.value;void window.heritageNavigate({preserveFocus:true});}});
$('#form-fields').addEventListener('change',e=>{if(e.target.name==='employee'){const giver=$('#form-fields').querySelector('[name="giver"]');if(giver)giver.value=BOT_RULES.employees[e.target.value];}});

function splitAmounts(amount){return{company:amount*15/100,group:amount*80/100,loss:amount*5/100};}
function financeTotals(sales=state.sales){const valid=sales.filter(s=>s.status!=='cancelled'),gross=valid.reduce((sum,s)=>sum+s.amount,0);return{gross,...splitAmounts(gross)};}
function statsPage(){
 const totals=state.summary||{},treated=totals.treated||0,days=state.days||[],max=Math.max(1,...days.map(d=>d.amount)),reports=state.machineReports||[],report=reports.find(r=>r.key===machineStatsWeek)||reports[0],employeesTotal=report?.rows||state.employeesTotal||[];
 const reportLabel=r=>r.weekStart?'Semaine du '+r.weekStart.split('-').reverse().join('/'):'Cette semaine';
 return `<div class="toolbar site-data-toolbar"><p>Données du site</p></div><div class="stats-top"><article class="panel"><span class="metric-label">Somme reçue</span><strong>${money(totals.gross)}</strong><small>Dossiers non annulés · toutes périodes</small></article><article class="panel"><span class="metric-label">Montant traité</span><strong>${money(treated)}</strong><small>Selon le suivi de progression</small></article><article class="panel"><span class="metric-label">Gain entreprise estimé</span><strong>${money(totals.company)}</strong><small>15 % des montants reçus, pas un encaissement confirmé</small></article></div>
 <div class="stats-grid"><section class="panel"><div class="panel-header"><div><h2>L’activité du domaine</h2><p>Montants reçus · 7 derniers jours à Bruxelles</p></div><span class="section-label">SALES</span></div><div class="estate-chart" role="img" aria-label="${days.map(d=>`${d.label} : ${money(d.amount)}`).join('; ')}">${days.map(d=>`<div class="chart-column"><span>${d.amount?money(d.amount):'—'}</span><div class="bar-track"><i style="height:${d.amount/max*100}%"></i></div><small>${d.label}</small></div>`).join('')}</div></section>
 <section class="panel"><div class="panel-header"><div><h2>La répartition</h2><p>Règle fixe sur les montants reçus</p></div></div><div class="split-chart"><div class="split-donut" role="img" aria-label="Groupe 80 %, entreprise 15 %, perte 5 %"><div><strong>15 %</strong><small>LE DOMAINE</small></div></div><ul><li><i></i>Groupes <b>80 %</b><span>${money(totals.group)}</span></li><li><i></i>Entreprise <b>15 %</b><span>${money(totals.company)}</span></li><li><i></i>Perte <b>5 %</b><span>${money(totals.loss)}</span></li></ul></div></section>
 <section class="panel"><div class="panel-header"><div><h2>Les artisans du domaine</h2><p>Lancements par employé · semaine en cours</p></div>${reports.length?`<label class="field machine-report-picker">Classement<select id="machine-stats-week">${reports.map(r=>`<option value="${escapeHTML(r.key)}" ${r===report?'selected':''}>${escapeHTML(reportLabel(r))}${r.key==='current'?' · en cours':' · archive'}</option>`).join('')}</select></label>`:''}</div><div class="employee-ranking">${employeesTotal.map((e,i)=>`<div><span class="rank-number">${i+1}</span><span class="avatar">${escapeHTML(e.name[0])}</span><span>${escapeHTML(e.name)}</span><strong>${e.count} <small>lancement${e.count>1?'s':''}</small></strong></div>`).join('')||'<p class="empty">Aucun lancement dans ce classement.</p>'}</div><p class="form-note">Un lancement correspond au lot entier de 5 machines.</p></section>
 <section class="estate-quote"><p class="eyebrow">DISCRÉTION · ORGANISATION · EFFICACITÉ</p><blockquote>« Derrière chaque grand vin,<br>il y a une histoire. »</blockquote><span>L’HÉRITAGE — LES AFFAIRES RESTENT EN FAMILLE</span></section></div>`;
}
$('#estate-date').textContent=new Intl.DateTimeFormat('fr-BE',{weekday:'long',day:'numeric',month:'long',timeZone:BOT_RULES.timeZone}).format(new Date());

$('#enter-demo').addEventListener('click',()=>{if(window.heritageLogin){window.heritageLogin();return;}if(window.heritageSession)location.hash=window.heritageSession.pages.some(page=>page.id==='overview')?'overview':'profile';else location.assign('/auth/start');});


setInterval(()=>{document.querySelectorAll('[data-cycle-progress]').forEach(el=>{const m=state.machines.find(m=>m.id===el.dataset.cycleProgress);if(!m)return;el.style.width=`${cyclePercent(m)}%`;el.parentElement.setAttribute('aria-valuenow',String(Math.round(cyclePercent(m))));});},1000);

setInterval(()=>{document.querySelectorAll('[data-cycle-state]').forEach(el=>{const m=state.machines.find(m=>m.id===el.dataset.cycleState);if(m){el.textContent=remaining(m)?'En cours':'À récupérer';el.classList.toggle('is-ready',remaining(m)===0);}});document.querySelectorAll('[data-cycle-percent]').forEach(el=>{const m=state.machines.find(m=>m.id===el.dataset.cyclePercent);if(m)el.textContent=`${Math.floor(cyclePercent(m))} %`;});},1000);
