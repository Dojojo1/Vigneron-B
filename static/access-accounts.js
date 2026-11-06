/* Comptes individuels : codes affichés une fois, jamais conservés dans le navigateur. */
window.heritageAccessAccounts=function({root,accounts,pages,api,esc,when,toast}){
 let users=accounts.users;
 const choices=(selected=[])=>pages.map(p=>`<label><input type="checkbox" name="pages" value="${esc(p.id)}" ${selected.includes(p.id)?'checked':''}><span>${esc(p.label)}</span></label>`).join('');
 root.innerHTML=`<p class="eyebrow">ACCÈS PROPRES AU SITE</p><h2>Les comptes du domaine</h2><p>Révoquer un compte coupe ses sessions et bloque ses prochaines connexions au site. Ses rôles Discord et son historique restent conservés.</p><details class="individual-create"><summary>Créer un accès par pseudo et code</summary><form id="individual-create-form"><div class="individual-fields"><label class="field">Pseudo de connexion<input name="loginName" required minlength="3" maxlength="40" pattern="[a-zA-Z0-9][a-zA-Z0-9._-]{2,39}" autocomplete="off" placeholder="Ex. tom.kerrigan"></label><label class="field">Nom affiché<input name="displayName" required maxlength="60" placeholder="Ex. Tom Kerrigan"></label></div><fieldset class="individual-pages"><legend>Catégories autorisées</legend>${choices()}</fieldset><p class="form-note">Sans catégorie cochée, seul Mon Registre est accessible. Ce compte fonctionne sans Discord et ne peut jamais administrer les accès.</p><button class="button primary" type="submit">Créer l’accès individuel →</button></form></details><section id="individual-code" class="individual-code" hidden aria-label="Nouvel accès individuel"><h3>À transmettre uniquement à cette personne</h3><p>Le code s’affiche une seule fois. Si tu le perds, génère un nouveau code depuis son compte.</p><label class="field">Pseudo<input id="individual-login-value" readonly autocomplete="off"></label><label class="field">Code d’accès<input id="individual-code-value" readonly autocomplete="off" spellcheck="false"></label><div class="register-actions"><button class="button primary" type="button" id="individual-copy">Copier le pseudo et le code</button><button class="button glass" type="button" id="individual-hide-code">Masquer le code</button></div></section><div id="individual-users" class="individual-users"></div>`;
 const container=root.querySelector('#individual-users'),codePanel=root.querySelector('#individual-code');
 function reveal(data){
  if(!root.isConnected)return;
  root.querySelector('#individual-login-value').value=data.account.loginName;
  root.querySelector('#individual-code-value').value=data.accessCode;
  codePanel.hidden=false;codePanel.scrollIntoView({block:'nearest',behavior:'smooth'});
 }
 function hideCode(){codePanel.hidden=true;root.querySelector('#individual-login-value').value='';root.querySelector('#individual-code-value').value='';}
 root.querySelector('#individual-hide-code').addEventListener('click',hideCode);
 root.querySelector('#individual-copy').addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(`Pseudo : ${root.querySelector('#individual-login-value').value}\nCode : ${root.querySelector('#individual-code-value').value}`);if(root.isConnected)toast('Accès copié. Transmets-le en privé à la personne concernée.');}
  catch{root.querySelector('#individual-code-value').select();toast('Sélectionne les champs pour les copier manuellement.');}
 });
 function table(){
  container.innerHTML=`<div class="table-wrap"><table class="individual-table"><thead><tr><th>Identité</th><th>Connexion et rôles</th><th>Accès au site</th><th>Dernière connexion</th><th>Gestion</th></tr></thead><tbody>${users.map(u=>{
   const a=u.siteAccess,guest=a.provider==='access_code';
   return `<tr data-account-id="${esc(u.id)}"><td><strong>${esc(u.display_name||u.username)}</strong><small>${esc(guest?a.loginName:u.id)}</small></td><td>${guest?'Pseudo et code':u.id==='local-preview'?'Aperçu local':`Discord<small>${JSON.parse(u.role_ids).map(id=>esc(accounts.roles?.find(r=>r.id===id)?.name||id)).join(', ')||'@everyone'}</small>`}</td><td><span class="individual-status ${a.blocked?'is-blocked':''}">${a.blocked?'Révoqué':u.protected?'Propriétaire protégé':!guest&&!u.member?'Hors du serveur':'Actif'}</span>${a.expiresAt?`<small>Expire le ${when(a.expiresAt)}</small>`:''}</td><td>${when(u.last_login)}</td><td>${u.protected?'<span class="form-note">Compte protégé</span>':`<button class="button glass" type="button" data-site-block="${!a.blocked}">${a.blocked?'Réactiver l’accès':'Révoquer l’accès'}</button>`}${guest?`<details class="individual-edit"><summary>Catégories et code</summary><form class="individual-edit-form"><fieldset class="individual-pages"><legend>Catégories autorisées</legend>${choices(a.pages)}</fieldset><button class="button primary" type="submit">Enregistrer</button><button class="button glass" type="button" data-rotate-code>Générer un nouveau code</button></form></details>`:''}</td></tr>`;
  }).join('')||'<tr><td colspan="5" class="empty">Aucun compte à afficher.</td></tr>'}</tbody></table></div>`;
 }
 async function refresh(){const result=await api('/api/admin/users');if(root.isConnected){users=result.users;table();}}
 const form=root.querySelector('#individual-create-form');
 form.addEventListener('submit',async event=>{
  event.preventDefault();if(form.dataset.busy)return;form.dataset.busy='true';const button=form.querySelector('[type=submit]');button.disabled=true;
  try{
   const data=new FormData(form),result=await api('/api/admin/access-accounts',{method:'POST',body:{loginName:data.get('loginName'),displayName:data.get('displayName'),pages:data.getAll('pages')}});
   if(!root.isConnected)return;
   form.reset();reveal(result);await refresh();toast('Accès créé. Copie le code avant de quitter cette page.');
  }catch(error){toast(error.message);}finally{button.disabled=false;delete form.dataset.busy;}
 });
 async function act(row,button,operation){
  if(container.dataset.busy)return;
  container.dataset.busy='true';container.querySelectorAll('button').forEach(el=>el.disabled=true);
  try{const result=await operation();if(!root.isConnected)return;if(result.accessCode)reveal(result);await refresh();toast(result.accessCode?'Nouveau code créé. Les anciennes sessions sont coupées.':'Accès enregistré.');}
  catch(error){toast(error.message);}
  finally{delete container.dataset.busy;container.querySelectorAll('button').forEach(el=>el.disabled=false);}
 }
 container.addEventListener('click',event=>{
  const button=event.target.closest('[data-site-block],[data-rotate-code]');if(!button||button.disabled||container.dataset.busy)return;
  const row=button.closest('[data-account-id]'),id=row.dataset.accountId,user=users.find(u=>u.id===id);
  if(button.hasAttribute('data-site-block')){
   const blocked=button.dataset.siteBlock==='true';
   if(!confirm(`${blocked?'Révoquer':'Réactiver'} l’accès au site de ${user.display_name||user.username} ?${blocked?' Ses sessions seront coupées. Ses rôles Discord restent conservés.':''}`))return;
   void act(row,button,()=>api('/api/admin/accounts/'+encodeURIComponent(id)+'/site-access',{method:'POST',body:{blocked}}));
  }else{
   if(!confirm('Générer un nouveau code ? L’ancien code et toutes les sessions de cette personne seront invalidés.'))return;
   hideCode();void act(row,button,()=>api('/api/admin/access-accounts/'+encodeURIComponent(id)+'/rotate-code',{method:'POST',body:{}}));
  }
 });
 container.addEventListener('submit',event=>{
  const edit=event.target.closest('.individual-edit-form');if(!edit)return;event.preventDefault();
  const row=edit.closest('[data-account-id]'),data=new FormData(edit);
  void act(row,edit.querySelector('[type=submit]'),()=>api('/api/admin/access-accounts/'+encodeURIComponent(row.dataset.accountId),{method:'PATCH',body:{pages:data.getAll('pages')}}));
 });
 table();
};
