'use strict';
(() => {
 const filters={q:'',actor:'',page:'',result:'',from:'',to:'',limit:'10'};
 let before=null,previous=[];
 const outcomes={success:'Réussi',failure:'Échec',refused:'Refusé',duplicate:'Déjà enregistré'};
 const labels={'add-sale':'Dossier ajouté','sale-detail':'Dossier modifié','finish-sale':'Restitution confirmée','cancel-sale':'Dossier annulé','sale-waiting':'Dossier mis en attente','sale-progress':'Dossier mis en cours','confirm-sales-reset':'Semaine archivée','add-machine':'Lot de machines lancé','recover':'Lot récupéré','unrecover':'Récupération annulée','cancel-machine':'Lot de machines annulé','edit-machine-time':'Heure du lot corrigée','add-vehicle':'Vehicule ajoute a la tombola','raffle-record':'Tombola enregistrée','vehicle-buy':'Achat du véhicule modifié','vehicle-pay':'Paiement du véhicule modifié','pay-all':'Paiements confirmés','reset-payments':'Paiements réinitialisés',permissions_changed:'Permissions modifiées',access_matrix_changed:'Accès modifiés',access_account_created:'Accès individuel créé',access_account_permissions_changed:'Permissions d’un accès modifiées',access_account_deleted:'Accès individuel supprimé',site_access_revoked:'Accès révoqué',site_access_restored:'Accès réactivé',machine_resolution_completed:'Lot de machines régularisé'};
 const reason=error=>{
  if(!error)return '';
  try{const value=typeof error==='string'?JSON.parse(error):error;return String(value?.message||value?.detail||value?.reason||'').slice(0,180);}
  catch{return typeof error==='string'?error.slice(0,180):'';}
 };
 const actionKinds=new Set(['business_action','bot_business_action','bot_command_applied','bot_command_failed','business_command_applied','business_command_failed','request_refused','request_failed']);
 const visibleEntry=entry=>actionKinds.has(entry.kind)?Boolean(labels[entry.action]):Boolean(labels[entry.kind]);
 window.heritageJournalQuery=()=>{
  const params=new URLSearchParams(Object.entries(filters).filter(([,value])=>value));
  if(before)params.set('before',before);
  return params;
 };
 window.heritageJournal=({data,api,signal,when})=>{
  const esc=escapeHTML;
  const visibleEntries=data.audit.filter(visibleEntry);
  const option=(value,label,selected)=>`<option value="${esc(value)}" ${value===selected?'selected':''}>${esc(label)}</option>`;
  const field=(label,name,type='text')=>`<label class="field">${label}<input name="${name}" type="${type}" value="${esc(filters[name])}" ${type==='text'?'maxlength="100"':''}></label>`;
  const entries=visibleEntries.map(entry=>{
   const title=labels[entry.action]||labels[entry.kind]||'Action du domaine';
   const actor=entry.actorName||entry.actor||'Bot du domaine';
   const detail=reason(entry.error);
   return `<details class="journal-entry" data-entry-id="${entry.id}"><summary class="journal-summary"><time>${when(entry.at)}</time><span><strong>${esc(actor)} · ${esc(title)}</strong>${entry.record?`<small>${esc(entry.record)}</small>`:''}${detail?`<small class="journal-reason">Pourquoi : ${esc(detail)}</small>`:''}</span><span class="journal-outcome" data-result="${esc(entry.result||'success')}">${esc(outcomes[entry.result]||'Réussi')}</span><span class="journal-expand" aria-hidden="true">＋</span></summary><div class="journal-detail"><p class="form-note">Chargement des détails à l’ouverture.</p></div></details>`;
  }).join('');
  document.querySelector('#content').innerHTML=`<section class="panel journal-panel"><h2>Journal permanent</h2><p class="form-note">Les actions du domaine, leur résultat et la raison d’un échec. Les événements techniques restent hors de cette vue.</p><form id="journal-filters" class="journal-filters">${field('Rechercher une personne ou une fiche','q')}${field('Identifiant de l’auteur','actor')}<label class="field">Espace<select name="page">${option('','Tous',filters.page)}${data.pages.map(page=>option(page.id,page.label,filters.page)).join('')}</select></label><label class="field">Résultat<select name="result">${option('','Tous',filters.result)}${Object.entries(outcomes).map(([key,label])=>option(key,label,filters.result)).join('')}</select></label>${field('Du','from','date')}${field('Au','to','date')}<label class="field">Actions par page<select name="limit">${[10,20,50].map(size=>option(String(size),String(size),filters.limit)).join('')}</select></label><div class="register-actions"><button class="button primary" type="submit">Filtrer →</button><button class="button glass" id="journal-clear" type="button">Effacer les filtres</button></div></form><div class="journal-list">${entries||'<p class="empty">Aucune action ne correspond à ces filtres.</p>'}</div><div class="list-pagination"><span>${visibleEntries.length} action(s) affichée(s) · du plus récent au plus ancien</span><button class="button glass" id="journal-previous" type="button" ${previous.length?'':'disabled'}>Plus récents</button><button class="button glass" id="journal-next" type="button" ${data.nextBefore?'':'disabled'}>Plus anciens</button></div></section>`;
  const form=document.querySelector('#journal-filters');
  form.addEventListener('submit',event=>{
   event.preventDefault();for(const key of Object.keys(filters))filters[key]=String(new FormData(form).get(key)||'').trim();
   before=null;previous=[];void window.heritageNavigate();
  });
  form.elements.limit.addEventListener('change',()=>form.requestSubmit());
  document.querySelector('#journal-clear').addEventListener('click',()=>{for(const key of Object.keys(filters))filters[key]='';filters.limit='10';before=null;previous=[];void window.heritageNavigate();});
  const navigating=()=>document.querySelector('#content').getAttribute('aria-busy')==='true';
  document.querySelector('#journal-next').addEventListener('click',()=>{if(navigating())return;previous.push(before);before=data.nextBefore;void window.heritageNavigate();});
  document.querySelector('#journal-previous').addEventListener('click',()=>{if(navigating())return;before=previous.pop()??null;void window.heritageNavigate();});
  const showValue=(value,exists)=>exists===false?'Valeur absente':typeof value==='string'?value:JSON.stringify(value,null,2);
  async function load(entry){
   if(entry.dataset.loaded||entry.dataset.loading||!entry.open)return;
   entry.dataset.loading='true';
   const target=entry.querySelector('.journal-detail');
   target.innerHTML=window.heritageLoadingMarkup('Chargement des détails…');
   try{
    const event=await api('/api/pages/journal/entries/'+entry.dataset.entryId,{signal});
    if(!entry.isConnected)return;
    const detail=event.detail||{};
    const summary=data.audit.find(item=>String(item.id)===entry.dataset.entryId);
    const failureReason=reason(detail.error||summary?.error);
    target.innerHTML=`<dl class="journal-metadata"><div><dt>Événement</dt><dd>#${event.id} · ${esc(event.kind)}</dd></div><div><dt>Auteur enregistré</dt><dd>${esc(summary?.actorName||detail.actorName||event.actor||'Bot du domaine')}</dd></div>${detail.requestId?`<div><dt>Requête</dt><dd>${esc(detail.requestId)}</dd></div>`:''}${detail.route?`<div><dt>Route</dt><dd>${esc(detail.method||'')} ${esc(detail.route)}</dd></div>`:''}</dl>${failureReason?`<p class="journal-reason">Pourquoi : ${esc(failureReason)}</p>`:''}${Array.isArray(detail.changes)?detail.changes.length?`<div class="journal-changes">${detail.changes.map(change=>`<section class="journal-change"><h3>${esc(change.path)}</h3><div class="journal-values"><div><h4>Avant</h4><pre tabindex="0">${esc(showValue(change.before,change.beforeExists))}</pre></div><div><h4>Après</h4><pre tabindex="0">${esc(showValue(change.after,change.afterExists))}</pre></div></div></section>`).join('')}</div>`:'<p class="form-note">Aucune valeur métier modifiée par cet événement.</p>':('before' in detail||'after' in detail)?`<div class="journal-values"><div><h4>Avant</h4><pre tabindex="0">${esc(showValue(detail.before,true))}</pre></div><div><h4>Après</h4><pre tabindex="0">${esc(showValue(detail.after,true))}</pre></div></div>`:'<p class="form-note">Cet événement ne contient pas de valeurs avant/après.</p>'}<details class="journal-technical"><summary>Toutes les informations enregistrées</summary><pre tabindex="0">${esc(JSON.stringify(detail,null,2))}</pre></details>`;
    entry.dataset.loaded='true';
   }catch(error){
    if(!error.cancelled&&entry.isConnected){target.innerHTML='<p class="form-note">Les détails n’ont pas pu être chargés.</p><button class="button glass" type="button">Réessayer</button>';target.querySelector('button').addEventListener('click',()=>void load(entry));}
   }finally{delete entry.dataset.loading;}
  }
  document.querySelector('.journal-list').addEventListener('toggle',event=>{if(event.target.matches('.journal-entry'))void load(event.target);},true);
 };
})();
