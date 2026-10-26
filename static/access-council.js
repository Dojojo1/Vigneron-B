'use strict';
window.heritageCouncil=function({access,accounts},{api,when}){
  const roles=access.roles.filter(r=>r.active),privatePages=access.pages.filter(p=>p.kind==='private');
  const pageIcons={overview:'home',sales:'funds',machines:'machines',tombola:'tombola',history:'history',stats:'gain',journal:'sales',team:'team'};
  function roleHeading(name){
   const parts=name.match(/^(.+?)\s*[·•]\s*(.+)$/u);
   return parts?`<span class="access-role-heading"><span class="access-role-symbol" aria-hidden="true">${escapeHTML(parts[1].trim())}</span><span>${escapeHTML(parts[2])}</span></span>`:`<span class="access-role-heading">${escapeHTML(name)}</span>`;
  }
  let selected=new Set(access.selectedRoles.filter(id=>roles.some(r=>r.id===id))),draft=new Set(selected),saving=false;
  const permissions=Object.fromEntries(roles.map(r=>[r.id,Object.fromEntries(privatePages.map(p=>[p.id,access.permissions.some(v=>v.role_id===r.id&&v.page_id===p.id&&v.allowed)]))]));
  $('#content').innerHTML=`<section class="panel council-panel access-intro"><p class="eyebrow">RÉSERVÉ À L’ADMINISTRATEUR SUPRÊME</p><h2>Le Conseil des Accès</h2><p>Seul le rôle Discord le plus élevé du membre compte. Les accès des rôles inférieurs ne sont jamais cumulés.</p><details class="domain-roles" open><summary>Rôles du domaine <span id="role-selection-count"></span></summary><p>Sélectionne les rôles dont tu veux configurer les accès. Un rôle non retenu n’a aucun accès privé. Un nouveau rôle retenu commence sans autorisation.</p><label class="field role-search">Rechercher un rôle<input id="role-search" type="search" placeholder="Nom du rôle Discord…" autocomplete="off"></label><div id="role-chips" class="role-chips" aria-label="Rôles Discord à retenir"></div><p id="role-search-empty" class="form-note" hidden>Aucun rôle ne correspond à ta recherche.</p><div class="access-controls"><button id="apply-access-roles" class="button primary" type="button">Appliquer les rôles →</button><button id="restore-role-selection" class="button glass" type="button">Annuler la sélection</button><span id="role-selection-note" role="status" aria-live="polite"></span></div></details></section><section class="panel council-panel access-matrix-panel"><div class="access-matrix-heading"><h2>Les autorisations du domaine</h2><span id="access-save-status" role="status" aria-live="polite">Configuration enregistrée</span></div><form id="access-form"><div id="access-matrix" class="access-matrix-scroll" role="region" aria-label="Tableau des accès par page et par rôle" tabindex="0"></div><p class="form-note">Choisis un r\u00f4le \u00e0 gauche, modifie ses acc\u00e8s puis enregistre. Les changements restent conserv\u00e9s quand tu passes d\u2019un r\u00f4le \u00e0 un autre. Le Conseil reste r\u00e9serv\u00e9 au propri\u00e9taire.</p><div class="access-controls"><button class="button primary" type="submit">Enregistrer les autorisations →</button></div></form></section><section class="panel council-panel" id="individual-access"></section><section class="panel council-panel"><h2>Journal permanent</h2><p class="form-note">Toutes les actions et leurs valeurs avant/après sont conservées dans le journal.</p><a class="button glass" href="#journal">Consulter le journal →</a></section>`;
  window.heritageAccessAccounts({root:$('#individual-access'),accounts:{...accounts,roles:access.roles},pages:privatePages,api,esc:escapeHTML,when,toast});
  const councilRoot=$('#content').firstElementChild;
  function selectionChanged(){return draft.size!==selected.size||[...draft].some(id=>!selected.has(id));}
  function chips(){
   const query=$('#role-search').value.trim().toLocaleLowerCase('fr');
   const visible=roles.filter(r=>r.name.toLocaleLowerCase('fr').includes(query));
   $('#role-chips').innerHTML=visible.map(r=>`<button type="button" class="role-chip" data-role-id="${escapeHTML(r.id)}" aria-pressed="${draft.has(r.id)}"><span>${escapeHTML(r.name)}</span><span class="role-chip-mark" aria-hidden="true">${draft.has(r.id)?'✓':'+'}</span></button>`).join('');
   $('#role-selection-count').textContent=`— ${draft.size} retenu${draft.size>1?'s':''} sur ${roles.length}`;
   $('#role-search-empty').hidden=visible.length>0;
   $('#role-selection-note').textContent=selectionChanged()?'Sélection à appliquer':'Sélection enregistrée';
   $('#apply-access-roles').disabled=saving||!selectionChanged();
   $('#restore-role-selection').disabled=saving||!selectionChanged();
  }
  function markDirty(){$('#access-save-status').textContent='Modifications à enregistrer';}
  let activeRole=null;
  function matrix(){
   const retained=roles.filter(r=>selected.has(r.id));
   $('#access-form [type=submit]').disabled=!retained.length;
   if(!retained.some(r=>r.id===activeRole))activeRole=retained[0]?.id||null;
   const role=retained.find(r=>r.id===activeRole),count=id=>privatePages.filter(p=>permissions[id][p.id]).length;
   if(!role){$('#access-matrix').innerHTML='<p class="access-empty">Aucun r\u00f4le retenu. Applique une s\u00e9lection ci-dessus pour configurer ses acc\u00e8s.</p>';return;}
   const descriptions={overview:'Vue g\u00e9n\u00e9rale du domaine',sales:'Suivi des dossiers et transactions',machines:'Gestion des lots de machines',tombola:'V\u00e9hicules, achats et paiements',history:'Historique des op\u00e9rations',stats:'Analyses et rapports',journal:'Registre des actions',team:'Les membres du domaine'};
   const general=['overview','sales','machines','tombola'],tracking=['history','stats','journal'];
   const groups=[{title:'Acc\u00e8s g\u00e9n\u00e9raux',symbol:'home',pages:privatePages.filter(p=>general.includes(p.id))},{title:'Suivi & analyses',symbol:'gain',pages:privatePages.filter(p=>tracking.includes(p.id))},{title:'Autres acc\u00e8s',symbol:'team',pages:privatePages.filter(p=>!general.includes(p.id)&&!tracking.includes(p.id))}];
   $('#access-matrix').innerHTML=`<div class="role-workspace"><aside class="role-directory" aria-label="S\u00e9lection du r\u00f4le"><header>${icon('machines')}<div><h3>S\u00e9lection d\u2019un r\u00f4le</h3><p>Choisis un r\u00f4le pour g\u00e9rer ses acc\u00e8s</p></div></header><div class="role-directory-list">${retained.map(r=>`<button type="button" class="role-directory-item ${r.id===role.id?'is-selected':''}" data-manage-role="${escapeHTML(r.id)}" aria-pressed="${r.id===role.id}">${roleHeading(r.name)}<small class="role-access-count">${count(r.id)} / ${privatePages.length} rubriques</small><span class="role-directory-arrow" aria-hidden="true">\u203a</span></button>`).join('')}</div></aside><section class="role-editor" aria-label="Autorisations du r\u00f4le"><header class="role-editor-heading"><div><p>Autorisations du r\u00f4le</p><h3>${roleHeading(role.name)}</h3></div><label class="role-retained"><span>R\u00f4le retenu</span><input type="checkbox" data-retain-role="${escapeHTML(role.id)}" checked aria-label="Retenir ${escapeHTML(role.name)} dans les r\u00f4les du domaine"></label></header><div class="role-permission-groups">${groups.filter(g=>g.pages.length).map(g=>`<section class="role-permission-group"><h4>${icon(g.symbol)}<span>${g.title}</span></h4>${g.pages.map(p=>`<label class="role-permission-row">${icon(pageIcons[p.id]||'home')}<span><strong>${escapeHTML(p.label)}</strong><small>${escapeHTML(descriptions[p.id]||'Acc\u00e8s \u00e0 cette rubrique')}</small></span><input type="checkbox" class="access-toggle" name="${escapeHTML(p.id)}" data-role-id="${escapeHTML(role.id)}" data-page-id="${escapeHTML(p.id)}" aria-label="${escapeHTML(p.label)} \u2014 ${escapeHTML(role.name)}" ${permissions[role.id][p.id]?'checked':''}></label>`).join('')}${g.symbol==='team'?'<p class="role-protected-note">Mon Registre reste accessible aux membres autoris\u00e9s. La gestion des acc\u00e8s reste r\u00e9serv\u00e9e au propri\u00e9taire.</p>':''}</section>`).join('')}</div><div class="role-bulk-actions"><button type="button" data-role-allow="true">Tout autoriser pour ce r\u00f4le</button><button type="button" data-role-allow="false">Tout interdire</button></div></section></div>`;
  }
  async function saveSelection(next){
   if(saving)return;
   saving=true;$('#access-form [type=submit]').disabled=true;$('#apply-access-roles').disabled=true;$('#restore-role-selection').disabled=true;
   $('#role-chips').querySelectorAll('button').forEach(button=>button.disabled=true);
   $('#access-matrix').querySelectorAll('input,button').forEach(el=>el.disabled=true);
   const ordered=roles.filter(r=>next.has(r.id)).map(r=>r.id);
   try{
    await api('/api/admin/access',{method:'PUT',body:{selectedRoles:ordered,permissions:Object.fromEntries(ordered.map(id=>[id,permissions[id]]))}});
    if(!councilRoot.isConnected)return;
    for(const id of selected)if(!next.has(id))permissions[id]=Object.fromEntries(privatePages.map(p=>[p.id,false]));
    selected=new Set(ordered);draft=new Set(selected);
    $('#access-save-status').textContent='Configuration enregistrée';
    toast('Les rôles et leurs autorisations sont enregistrés.');
   }catch(error){if(councilRoot.isConnected)$('#access-save-status').textContent='Enregistrement non effectué';toast(error.message);}
   finally{saving=false;if(councilRoot.isConnected){chips();matrix();}}
  }
  $('#role-chips').addEventListener('click',e=>{const button=e.target.closest('[data-role-id]');if(!button||saving)return;const id=button.dataset.roleId;if(draft.has(id))draft.delete(id);else draft.add(id);chips();$('#role-chips').querySelector(`[data-role-id="${CSS.escape(id)}"]`)?.focus();});
  $('#role-search').addEventListener('input',chips);
  $('#restore-role-selection').addEventListener('click',()=>{draft=new Set(selected);chips();});
  $('#apply-access-roles').addEventListener('click',()=>saveSelection(new Set(draft)));
  $('#access-matrix').addEventListener('change',e=>{
   if(saving)return;
   const retained=e.target.closest('[data-retain-role]');
   if(retained){const next=new Set(selected);if(retained.checked)next.add(retained.dataset.retainRole);else next.delete(retained.dataset.retainRole);void saveSelection(next);return;}
   const box=e.target.closest('.access-toggle');if(!box)return;
   permissions[box.dataset.roleId][box.dataset.pageId]=box.checked;markDirty();
   const count=privatePages.filter(p=>permissions[box.dataset.roleId][p.id]).length;
   const row=$('#access-matrix').querySelector(`[data-manage-role="${CSS.escape(box.dataset.roleId)}"] .role-access-count`);if(row)row.textContent=`${count} / ${privatePages.length} rubriques`;
  });
  $('#access-matrix').addEventListener('click',e=>{
   if(saving)return;
   const role=e.target.closest('[data-manage-role]');if(role){activeRole=role.dataset.manageRole;matrix();$('#access-matrix').querySelector(`[data-manage-role="${CSS.escape(activeRole)}"]`)?.focus({preventScroll:true});return;}
   const bulk=e.target.closest('[data-role-allow]');if(!bulk||!activeRole)return;
   for(const page of privatePages)permissions[activeRole][page.id]=bulk.dataset.roleAllow==='true';matrix();markDirty();
  });
  $('#access-form').addEventListener('submit',e=>{e.preventDefault();saveSelection(new Set(selected));});
  chips();matrix();
 };
