'use strict';
window.heritageCouncil=function({access,accounts},{api,when}){
  const roles=access.roles.filter(r=>r.active),privatePages=access.pages.filter(p=>p.kind==='private');
  let selected=new Set(access.selectedRoles.filter(id=>roles.some(r=>r.id===id))),draft=new Set(selected),saving=false;
  const permissions=Object.fromEntries(roles.map(r=>[r.id,Object.fromEntries(privatePages.map(p=>[p.id,access.permissions.some(v=>v.role_id===r.id&&v.page_id===p.id&&v.allowed)]))]));
  $('#content').innerHTML=`<section class="panel council-panel access-intro"><p class="eyebrow">RÉSERVÉ À L’ADMINISTRATEUR SUPRÊME</p><h2>Le Conseil des Accès</h2><p>Seul le rôle Discord le plus élevé du membre compte. Les accès des rôles inférieurs ne sont jamais cumulés.</p><details class="domain-roles" open><summary>Rôles du domaine <span id="role-selection-count"></span></summary><p>Retiens les rôles à afficher dans le tableau. Un rôle non retenu n’a aucun accès privé. Un nouveau rôle retenu commence sans autorisation.</p><label class="field role-search">Rechercher un rôle<input id="role-search" type="search" placeholder="Nom du rôle Discord…" autocomplete="off"></label><div id="role-chips" class="role-chips" aria-label="Rôles Discord à retenir"></div><p id="role-search-empty" class="form-note" hidden>Aucun rôle ne correspond à ta recherche.</p><div class="access-controls"><button id="apply-access-roles" class="button primary" type="button">Appliquer les rôles →</button><button id="restore-role-selection" class="button glass" type="button">Annuler la sélection</button><span id="role-selection-note" role="status" aria-live="polite"></span></div></details></section><section class="panel council-panel access-matrix-panel"><div class="access-matrix-heading"><h2>Les autorisations du domaine</h2><span id="access-save-status" role="status" aria-live="polite">Configuration enregistrée</span></div><form id="access-form"><div id="access-matrix" class="access-matrix-scroll" role="region" aria-label="Tableau des accès par page et par rôle" tabindex="0"></div><p class="form-note">✓ Autorisé · case vide : interdit. « Tout » inverse les accès de la ligne pour les rôles affichés. Mon Registre reste accessible aux employés autorisés ; le Conseil reste exclusivement réservé à ton compte.</p><div class="access-controls"><button class="button primary" type="submit">Enregistrer les autorisations →</button></div></form></section><section class="panel council-panel" id="individual-access"></section><section class="panel council-panel"><h2>Journal permanent</h2><p class="form-note">Toutes les actions et leurs valeurs avant/après sont conservées dans le journal.</p><a class="button glass" href="#journal">Consulter le journal →</a></section>`;
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
  function matrix(){
   const columns=roles.filter(r=>selected.has(r.id));
   $('#access-form [type=submit]').disabled=!columns.length;
   $('#access-matrix').innerHTML=columns.length?`<table class="access-matrix"><thead><tr><th scope="col">Page</th>${columns.map(r=>`<th scope="col">${escapeHTML(r.name)}</th>`).join('')}</tr></thead><tbody>${privatePages.map(p=>`<tr><th scope="row"><span>${escapeHTML(p.label)}</span><button type="button" class="access-row-all" data-page-id="${escapeHTML(p.id)}" aria-label="Tout autoriser ou interdire pour ${escapeHTML(p.label)}">Tout</button></th>${columns.map(r=>`<td><input type="checkbox" class="access-toggle" name="${escapeHTML(p.id)}" data-role-id="${escapeHTML(r.id)}" data-page-id="${escapeHTML(p.id)}" aria-label="${escapeHTML(p.label)} — ${escapeHTML(r.name)}" ${permissions[r.id][p.id]?'checked':''}></td>`).join('')}</tr>`).join('')}</tbody></table>`:'<p class="access-empty">Aucun rôle retenu. Sélectionne les rôles du domaine ci-dessus, puis applique ta sélection pour configurer leurs accès.</p>';
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
  $('#access-matrix').addEventListener('change',e=>{const box=e.target.closest('.access-toggle');if(!box||saving)return;permissions[box.dataset.roleId][box.dataset.pageId]=box.checked;markDirty();});
  $('#access-matrix').addEventListener('click',e=>{const button=e.target.closest('.access-row-all');if(!button||saving)return;const page=button.dataset.pageId,ids=[...selected],allow=!ids.every(id=>permissions[id][page]);for(const id of ids)permissions[id][page]=allow;matrix();markDirty();});
  $('#access-form').addEventListener('submit',e=>{e.preventDefault();saveSelection(new Set(selected));});
  chips();matrix();
 };
