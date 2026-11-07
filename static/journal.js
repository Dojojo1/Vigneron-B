'use strict';
(() => {
 const filters={q:'',actor:'',page:'',result:'',from:'',to:''};
 let before=null,previous=[];
 const outcomes={success:'Réussi',failure:'Échec',refused:'Refusé',duplicate:'Déjà enregistré'};
 const labels={'add-sale':'Dossier ajouté','sale-detail':'Dossier modifié','finish-sale':'Restitution confirmée','cancel-sale':'Dossier annulé','sale-waiting':'Dossier mis en attente','sale-progress':'Dossier mis en cours','confirm-sales-reset':'Semaine archivée','add-machine':'Lot de machines lancé','recover':'Lot récupéré','unrecover':'Récupération annulée','cancel-machine':'Lot de machines annulé','edit-machine-time':'Heure du lot corrigée','raffle-record':'Tombola enregistrée','vehicle-buy':'Achat du véhicule modifié','vehicle-pay':'Paiement du véhicule modifié','pay-all':'Paiements confirmés','reset-payments':'Paiements réinitialisés',permissions_changed:'Permissions modifiées',access_matrix_changed:'Accès modifiés',access_account_created:'Accès individuel créé',access_account_permissions_changed:'Permissions d’un accès modifiées',access_account_deleted:'Accès individuel supprimé',site_access_revoked:'Accès révoqué',site_access_restored:'Accès réactivé',machine_resolution_completed:'Lot de machines régularisé'};
 const reason=error=>{
  if(!error)return '';
  try{const value=typeof error==='string'?JSON.parse(error):error;return String(value?.message||value?.detail||value?.reason||'').slice(0,180);}
  catch{return typeof error==='string'?error.slice(0,180):'';}
 };
 window.heritageJournalQuery=()=>{
  const params=new URLSearchParams(Object.entries(filters).filter(([,value])=>value));
  if(before)params.set('before',before);
  return params;
 };
 window.heritageJournal=({data,when})=>{
  const esc=escapeHTML;
  const option=(value,label,selected)=>`<option value="${esc(value)}" ${value===selected?'selected':''}>${esc(label)}</option>`;
  const field=(label,name,type='text')=>`<label class="field">${label}<input name="${name}" type="${type}" value="${esc(filters[name])}" ${type==='text'?'maxlength="100"':''}></label>`;
  const entries=data.audit.map(entry=>{
   const title=labels[entry.action]||labels[entry.kind]||'Action du domaine';
   const actor=entry.actorName||entry.actor||'Bot du domaine';
   const detail=reason(entry.error);
   return `<article class="journal-entry"><div class="journal-summary"><time>${when(entry.at)}</time><div><strong>${esc(actor)} · ${esc(title)}</strong>${entry.record?`<small>${esc(entry.record)}</small>`:''}${detail?`<small class="journal-reason">Pourquoi : ${esc(detail)}</small>`:''}</div><span class="journal-outcome" data-result="${esc(entry.result||'success')}">${esc(outcomes[entry.result]||'Réussi')}</span></div></article>`;
  }).join('');
  document.querySelector('#content').innerHTML=`<section class="panel journal-panel"><h2>Journal permanent</h2><p class="form-note">Les actions du domaine, leur résultat et la raison d’un échec. Les événements techniques restent hors de cette vue.</p><form id="journal-filters" class="journal-filters">${field('Rechercher une personne ou une fiche','q')}${field('Identifiant de l’auteur','actor')}<label class="field">Espace<select name="page">${option('','Tous',filters.page)}${data.pages.map(page=>option(page.id,page.label,filters.page)).join('')}</select></label><label class="field">Résultat<select name="result">${option('','Tous',filters.result)}${Object.entries(outcomes).map(([key,label])=>option(key,label,filters.result)).join('')}</select></label>${field('Du','from','date')}${field('Au','to','date')}<div class="register-actions"><button class="button primary" type="submit">Filtrer →</button><button class="button glass" id="journal-clear" type="button">Effacer les filtres</button></div></form><div class="journal-list">${entries||'<p class="empty">Aucune action ne correspond à ces filtres.</p>'}</div><div class="list-pagination"><span>${data.audit.length} action(s) affichée(s) · du plus récent au plus ancien</span><button class="button glass" id="journal-previous" type="button" ${previous.length?'':'disabled'}>Plus récents</button><button class="button glass" id="journal-next" type="button" ${data.nextBefore?'':'disabled'}>Plus anciens</button></div></section>`;
  const form=document.querySelector('#journal-filters');
  form.addEventListener('submit',event=>{
   event.preventDefault();for(const key of Object.keys(filters))filters[key]=String(new FormData(form).get(key)||'').trim();
   before=null;previous=[];void window.heritageNavigate();
  });
  document.querySelector('#journal-clear').addEventListener('click',()=>{for(const key of Object.keys(filters))filters[key]='';before=null;previous=[];void window.heritageNavigate();});
  const navigating=()=>document.querySelector('#content').getAttribute('aria-busy')==='true';
  document.querySelector('#journal-next').addEventListener('click',()=>{if(navigating())return;previous.push(before);before=data.nextBefore;void window.heritageNavigate();});
  document.querySelector('#journal-previous').addEventListener('click',()=>{if(navigating())return;before=previous.pop()??null;void window.heritageNavigate();});
 };
})();
