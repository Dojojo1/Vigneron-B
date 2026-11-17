'use strict';
(() => {
 const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const currency=new Intl.NumberFormat('fr-FR');
 const clock=new Intl.DateTimeFormat('fr-BE',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Europe/Brussels'});
 window.heritageLogs=({data,api})=>{
  const entries=Array.isArray(data?.entries)?data.entries:[];
  const page=data?.pagination?.logs||{total:entries.length,offset:0,limit:50,hasMore:false};
  const root=document.querySelector('#content');
  root.innerHTML=`<section class="panel journal-panel logs-panel"><p class="eyebrow">LE REGISTRE DU BOT</p><h2>Logs du coffre</h2><p class="form-note">Mouvements reçus depuis le 16 novembre 2026, classés selon l’heure réelle de l’opération. Les logs indiqués « hors contrôle » restent consultables mais ne servent pas à vérifier les deux nouveaux dossiers.</p>${entries.length?`<div class="table-wrap"><table class="history-table"><thead><tr><th>Opération</th><th>Mouvement</th><th>Type</th><th>Joueur</th><th>Montant</th><th>Contrôle</th><th>Source</th></tr></thead><tbody>${entries.map(row=>`<tr><td><time datetime="${escape(row.eventTime)}">${clock.format(new Date(row.eventTime))}</time></td><td>${row.action==='depot'?'Dépôt':'Retrait'}</td><td>${row.itemId==='saleMoney'?'Argent sale':'Argent'}</td><td>${escape(row.playerName)}</td><td>${currency.format(row.amount)} $</td><td>${row.exclusionReason?`<span class="badge wait" title="${escape(row.exclusionReason)}">Hors contrôle</span>`:'—'}</td><td><a href="${escape(row.sourceUrl)}" target="_blank" rel="noopener noreferrer">Voir le log ↗</a></td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">Aucun nouveau log du coffre pour le moment.</p>'}${page.total>page.limit?`<div class="list-pagination"><span>${page.offset+1}–${Math.min(page.offset+page.limit,page.total)} sur ${page.total}</span><button class="button glass" type="button" data-coffre-offset="${Math.max(0,page.offset-page.limit)}" ${page.offset?'':'disabled'}>← Précédent</button><button class="button glass" type="button" data-coffre-offset="${page.offset+page.limit}" ${page.hasMore?'':'disabled'}>Suivant →</button></div>`:''}</section>`;
  root.querySelector('.logs-panel').addEventListener('click',async event=>{
   const button=event.target.closest('[data-coffre-offset]');
   if(!button||button.disabled)return;
   button.disabled=true;
   try{window.heritageLogs({data:await api('/api/pages/logs?view=screen&logsOffset='+button.dataset.coffreOffset),api});}
   catch(error){button.disabled=false;window.heritageFeedback?.show({title:'Logs indisponibles',message:error.message,key:'coffre-logs'});}
  });
 };
})();
