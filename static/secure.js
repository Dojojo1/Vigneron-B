'use strict';
(() => {
 const publicPages=location.hostname.endsWith('.github.io')||document.querySelector('meta[name="heritage-hosting"]')?.content==='github-pages';
 if(publicPages){
  void window.heritageOpenConnectedSite().then(connected=>{
   if(connected==='preview')window.heritagePublicDemo();
  });
  return;
 }
 let session=null,navigationVersion=0,navigationAbort=null,filterTimer=null,catalogCache=null,lastVisited=null,sheetsAbort=null,sheetsVersion=0;
 const pendingActions=new Map(),operationKeys=new Map(),requestCooldowns=new Map();
 const pageCache=new Map(),bootstrapTasks=new Set(),CACHE_LIMIT=48,CACHE_BYTES=16*1024*1024,LOADING_DELAY=180,SESSION_LEASE=30000,REFRESH_INTERVAL=60000;
 const versionedRoutes=new Set(['overview','sales','machines','tombola','stats','team','history']);
 let cacheEpoch=0,displayedPage=null,accountMarkup='',profileDraft=null,sessionConfirmedAt=0,sessionCheck=null,suspendedForm=null;
 function clearPageCache(routes){
  cacheEpoch++;
  if(!routes){pageCache.clear();catalogCache=null;return;}
  for(const [key,entry] of pageCache)if(routes.includes(entry.route))pageCache.delete(key);
 }
 function cachedPage(key){
  const entry=pageCache.get(key);if(!entry)return null;
  if(entry.userId!==session?.user.id||entry.roleId!==session?.user.role.id||!can(entry.route)){pageCache.delete(key);return null;}
  pageCache.delete(key);pageCache.set(key,entry);return entry;
 }
 function rememberPage(key,route,data,version){
  if(!can(route))return;
  const json=JSON.stringify(data),bytes=json.length*2;
  if(bytes>CACHE_BYTES)return;
  pageCache.delete(key);pageCache.set(key,{route,json,bytes,version,at:performance.now(),userId:session.user.id,roleId:session.user.role.id});
  while(pageCache.size>CACHE_LIMIT||[...pageCache.values()].reduce((sum,item)=>sum+item.bytes,0)>CACHE_BYTES){
   const discard=[...pageCache].find(([url,item])=>url!==pageURL(item.route,true));
   pageCache.delete(discard?discard[0]:pageCache.keys().next().value);
  }
 }
 function affectedPages(path){
  if(path==='/api/admin/company-history')return ['overview','stats','journal'];
  if(path.startsWith('/api/actions/tombola')){catalogCache=null;return ['tombola','history','journal'];}
  if(path.startsWith('/api/actions/'))return ['overview','sales','machines','stats','history','journal'];
  if(path.startsWith('/api/me/'))return ['profile','team','council','journal'];
  return null;
 }
 const can=page=>Boolean(session?.pages.some(p=>p.id===page));
 const landingPage=()=>can('overview')?'overview':'profile';
 const actionPage=action=>action==='company-history'?'stats':['add-sale','sale-detail','finish-sale','sale-waiting','sale-progress','cancel-sale','confirm-sales-reset','archive-sales'].includes(action)?'sales':['add-machine','edit-machine-time','recover','unrecover','cancel-machine'].includes(action)?'machines':['raffle-record','vehicle-buy','vehicle-pay','pay-all','reset-payments','delete-vehicle','delete-tombola-week'].includes(action)?'tombola':null;
 const whenFormatter=new Intl.DateTimeFormat('fr-BE',{dateStyle:'medium',timeStyle:'short',timeZone:'Europe/Brussels'});
 const when=seconds=>whenFormatter.format(new Date(seconds*1000));
 async function api(path,{method='GET',body,form,signal,requestKey,visit=false,exporting=false,cached,pageResponse,background=false}={}){
  const requestScope=sessionScope(session),requestEpoch=cacheEpoch,privateRead=method==='GET'&&(path.startsWith('/api/pages/')||path.split('?')[0]==='/api/bootstrap');
  const currentScope=()=>(!requestScope||requestScope===sessionScope(session))&&(!privateRead||requestEpoch===cacheEpoch);
  const cooldownKey=path.split('?')[0],cooldown=requestCooldowns.get(cooldownKey);
  if(cooldown&&cooldown.until>Date.now())throw cooldown.error;
  requestCooldowns.delete(cooldownKey);
  const headers={};if(method!=='GET')headers['X-CSRF-Token']=session?.csrf||'';
  if(visit)headers['X-Heritage-Visit']='1';
  if(exporting)headers['X-Heritage-Export']='1';
  if(cached?.version)headers['X-Heritage-Cache']=cached.version;
  if(background)headers['X-Heritage-Background']='1';
  if(requestKey)headers['Idempotency-Key']=requestKey;
  if(body){headers['Content-Type']='application/json';body=JSON.stringify(body);}
  const controller=new AbortController();
  const cancel=()=>controller.abort();
  if(signal?.aborted)cancel();else signal?.addEventListener('abort',cancel,{once:true});
  const timer=setTimeout(()=>controller.abort(),20000);
  const writing=method!=='GET'&&!path.startsWith('/api/visits/')&&path!=='/api/client-errors';
  try{
   let response;
   try{response=await fetch(path,{method,headers,body:form||body,credentials:'same-origin',cache:'no-store',keepalive:path.startsWith('/api/visits/'),signal:controller.signal});}
   catch(cause){
    if(signal?.aborted){const error=new Error('Chargement remplacé.');error.cancelled=true;throw error;}
    const error=new Error(cause.name==='AbortError'?'Le serveur met trop de temps à répondre.':navigator.onLine===false?'La connexion avec le site est interrompue.':'Impossible de joindre le serveur du site. Vérifie qu’il est démarré.');
    error.uncertain=writing;error.clientKind=cause.name==='AbortError'?'timeout':'network';if(currentScope())window.heritageReportError?.(error.clientKind);throw error;
   }
   if(pageResponse&&(response.ok||response.status===304)){
    pageResponse.version=response.headers.get('X-Heritage-Data-Version');
    const userId=response.headers.get('X-Heritage-User'),roleId=response.headers.get('X-Heritage-Role');
    if(!/^[0-9a-f]{64}$/.test(pageResponse.version||'')||![userId,roleId].every(id=>/^(?:[0-9]{1,24}|local-preview|guest-[0-9a-f]{32}|access-code)$/.test(id||''))){const error=new Error('Le serveur a renvoyé une réponse de page invalide. Réessaie dans quelques instants.');error.clientKind='unexpected';if(currentScope())window.heritageReportError?.(error.clientKind);throw error;}
    if(userId!==session?.user.id||roleId!==session?.user.role.id){const error=new Error('Ton accès au domaine a été actualisé.');error.sessionChanged=true;throw error;}
    if(response.status===304){
     if(!cached||cached.userId!==userId||cached.roleId!==roleId||!cached.version||cached.version!==pageResponse.version){const error=new Error('La réponse du serveur ne correspond pas à cette page. Réessaie.');error.clientKind='unexpected';throw error;}
     window.heritageFeedback?.recovered(path);
     return JSON.parse(cached.json);
    }
   }
   let data;
   try{data=await response.json();}
   catch{const error=new Error(controller.signal.aborted?'Le serveur met trop de temps à répondre.':'Le serveur a renvoyé une réponse illisible. Réessaie dans quelques instants.');error.status=response.status;error.uncertain=writing;error.cancelled=Boolean(signal?.aborted);error.clientKind='unexpected';if(!error.cancelled&&currentScope())window.heritageReportError?.(error.clientKind);throw error;}
   if(!response.ok){
    const detail=typeof data?.detail==='string'?data.detail:null;
    const error=new Error(response.status>=500&&!data?.reason?'Le serveur rencontre un problème. Réessaie dans quelques instants.':detail||'La demande a échoué.');
    error.status=response.status;error.reason=data?.reason;error.uncertain=writing&&response.status>=500&&data?.reason!=='api_budget_exhausted';
    if(path==='/api/me'&&typeof data?.configured==='boolean')error.configuration={configured:data.configured,localPreview:data.localPreview,preview:data.preview};
    const wait=Number(response.headers.get('Retry-After'));
    if((response.status===429||data?.reason==='api_budget_exhausted')&&Number.isFinite(wait)&&wait>0){
     requestCooldowns.set(cooldownKey,{until:Date.now()+wait*1000,error});
    }
    throw error;
   }
   if(privateRead&&!currentScope()){const error=new Error('Les données ont changé pendant le chargement. Réessaie.');error.cancelled=true;error.staleRead=true;throw error;}
   if(writing){const routes=affectedPages(path);clearPageCache(routes);if(path!=='/auth/logout')queuePreload(routes);}
   window.heritageFeedback?.recovered(path);
   return data;
  }catch(error){
   if(!currentScope()){error.cancelled=true;error.staleRead=privateRead&&!signal?.aborted;throw error;}
   if(writing&&error.uncertain)clearPageCache(affectedPages(path));
   if(error.uncertain)error.message+=' L’enregistrement n’a pas pu être confirmé : vérifie l’historique avant de refaire l’action.';
   if(error.status!==401&&!error.cancelled&&!error.sessionChanged)window.heritageFeedback?.show({title:writing?'Action interrompue':'Chargement impossible',message:error.message,key:path});
   throw error;
  }finally{clearTimeout(timer);signal?.removeEventListener('abort',cancel);}
 }
 function sessionScope(data){return data?JSON.stringify([data.user.id,data.user.role.id,data.user.supreme,data.localPreview,data.csrf,data.pages.map(p=>p.id)]):null;}
 function publishSession(data){
  if(sessionScope(data)!==sessionScope(session)){clearPageCache();lastVisited=null;if(session)concealPrivateUI();}
  if(session&&(!data||data.user.id!==session.user.id)){profileDraft=null;state=seed();$('#content').replaceChildren();displayedPage=null;accountMarkup='';}
  session=data;sessionConfirmedAt=data?performance.now():0;window.heritageSession=data;refreshAccount();void flushErrors();
 }
 const reportedErrors=new Map();
 let errorFlush=false;
 const errorStorage=()=>session?'heritage.pending-errors.'+session.user.id:null;
 function readErrors(key){try{const data=JSON.parse(localStorage.getItem(key)||'[]');return Array.isArray(data)?data:[];}catch{return [];}}
 let memoryErrors=new Map();
 function pendingErrors(key){if(!memoryErrors.has(key))memoryErrors.set(key,readErrors(key));return memoryErrors.get(key);}
 function persistErrors(key){try{localStorage.setItem(key,JSON.stringify(pendingErrors(key)));}catch{}}
 async function flushErrors(){
  const key=errorStorage();if(!key||errorFlush||navigator.onLine===false)return;
  errorFlush=true;
  try{
   while(session&&errorStorage()===key&&pendingErrors(key).length){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);
    try{
     const response=await fetch('/api/client-errors',{method:'POST',credentials:'same-origin',signal:controller.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify(pendingErrors(key)[0])});
     if(!response.ok)break;
     pendingErrors(key).shift();persistErrors(key);
    }catch{break;}finally{clearTimeout(timer);}
   }
  }finally{errorFlush=false;}
 }
 window.addEventListener('online',()=>void flushErrors());
 window.heritageReportError=kind=>{
  if(!session||!['script','network','timeout','unexpected','offline'].includes(kind))return;
  const route=location.hash.slice(1)||landingPage(),page=route==='welcome'||session.pages.some(p=>p.id===route)?route:'profile',key=kind+':'+page;
  if(Date.now()-(reportedErrors.get(key)||0)<30000)return;reportedErrors.set(key,Date.now());
  const storage=errorStorage();pendingErrors(storage).push({kind,page,key:'client-error-'+crypto.randomUUID(),occurredAt:Date.now()});persistErrors(storage);void flushErrors();
 };
 function refreshAccount(){
  if(!session){$('#enter-demo .entry-button-label').textContent='SE CONNECTER AVEC DISCORD';return;}
  const u=session.user;
  $('#profile-name').textContent=u.displayName;
  $('#profile-menu p').textContent=u.authProvider==='access_code'?'Profil personnel · accès individuel':u.authProvider==='local'?'Profil de test local':'Profil personnel · identité Discord vérifiée';
  $('#profile-role').textContent=session.localPreview?u.role.name:u.supreme?'Administrateur Suprême':u.role.name;
  if($('#profile-avatar img')?.getAttribute('src')!==u.avatar)$('#profile-avatar').innerHTML=`<img src="${escapeHTML(u.avatar)}" alt="">`;
  const markup=session.pages.map(p=>`<a href="#${escapeHTML(p.id)}" data-page="${escapeHTML(p.id)}">${icon(p.id==='profile'?'team':p.id==='council'?'machines':pages[p.id]?.[3]||'home')}<span>${escapeHTML(p.label)}</span></a>`).join('');
  if(markup!==accountMarkup){$('#navigation').innerHTML=markup;accountMarkup=markup;document.querySelectorAll('#navigation [data-page]').forEach(el=>{const selected=el.dataset.page===activePage;el.classList.toggle('active',selected);if(selected)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});}
  $('footer > span:last-child').firstChild.textContent=session.localPreview?'Aperçu local · données d’essai ':'Espace privé · données partagées ';
  $('#reset-demo').hidden=!u.supreme||!session.localPreview;
  $('#reset-demo').textContent='Réinitialiser les données de test';
  $('#enter-demo .entry-button-label').textContent=can('overview')?'ACCÉDER AU TABLEAU DE BORD':'RETROUVER MON REGISTRE';
  if(session.localPreview){
   $('.entry-demo-note').textContent='Aperçu local · connexion Discord temporairement désactivée.';
   $('#logout').textContent='Revenir à l’accueil';
  }
 }
 function applyAccessUI(){
  document.querySelectorAll('[data-action]').forEach(el=>{const page=actionPage(el.dataset.action);if(page)el.hidden=!can(page);});
  document.querySelectorAll('a[href^="#"]').forEach(el=>{const page=el.hash.slice(1);if(page&&page!=='welcome'&&Object.hasOwn(pages,page))el.hidden=!can(page);});
 }
 function visibleDomain(show){
  const changed=$('body').classList.contains('on-entry')===show;
  $('#entry-screen').hidden=show;$('main').hidden=!show;$('#sidebar').hidden=!show;$('body').classList.toggle('on-entry',!show);closeMenu();
  if(!show){$('#session-resume-loading')?.remove();concealPrivateUI();}
  if(changed)window.dispatchEvent(new Event('heritage:domain-visibility'));
 }
 function concealPrivateUI({preserveDraft=false}={}){
  const dialog=$('#form-dialog'),fields=$('#form-fields');
  if(preserveDraft&&dialog.open&&session&&can(actionPage(formMode))){
   const fragment=document.createDocumentFragment();fragment.append(...fields.childNodes);
   suspendedForm={scope:sessionScope(session),page:activePage,mode:formMode,id:currentId,title:$('#dialog-title').textContent,raffle:dialog.classList.contains('raffle-dialog'),fields:fragment};
  }else if(!preserveDraft)suspendedForm=null;
  for(const modal of document.querySelectorAll('dialog[open]'))modal.close();
  fields.replaceChildren();$('#dialog-title').textContent='';formMode='';currentId=null;
  $('#profile-form').reset();$('#profile-preview').replaceChildren();
  hidePanels();$('#notifications-panel').replaceChildren();$('#search-results').replaceChildren();
 }
 function restoreFormDraft(){
  if(!suspendedForm||$('#entry-form').dataset.submitting==='true')return;
  const draft=suspendedForm;suspendedForm=null;
  if(draft.scope!==sessionScope(session)||draft.page!==activePage||!can(actionPage(draft.mode)))return;
  formMode=draft.mode;currentId=draft.id;$('#dialog-title').textContent=draft.title;
  $('#form-fields').replaceChildren(draft.fields);$('#form-dialog').classList.toggle('raffle-dialog',draft.raffle);$('#form-dialog').showModal();
 }
 function rememberProfileDraft(){
  const form=$('#secure-profile-form');
  if(form&&session){
   profileDraft=null;
   const displayName=form.querySelector('[name=displayName]').value,file=form.querySelector('[name=photo]').files?.[0];
   if(displayName!==session.user.displayName||file?.size)profileDraft={userId:session.user.id,displayName,file};
  }
 }
 function failPage(error){
  rememberProfileDraft();
  concealPrivateUI({preserveDraft:error.status!==401&&error.status!==403});
  displayedPage=null;sessionConfirmedAt=0;clearPageCache();
  state=seed();$('#content').innerHTML=`<section class="panel secure-message"><p class="eyebrow">LES AFFAIRES RESTENT EN FAMILLE</p><h2>${error.status===403?'Accès réservé':'La page n’a pas pu s’ouvrir'}</h2><p>${escapeHTML(error.message)}</p><div class="register-actions">${error.status===403?'':'<button class="button primary" type="button" id="retry-page">Réessayer →</button>'}<a class="button glass" href="#profile">Mon Registre →</a></div></section>`;
  $('#content').hidden=false;$('#content').setAttribute('aria-busy','false');$('#session-resume-loading')?.remove();
  $('#retry-page')?.addEventListener('click',()=>window.heritageRetry());
 }
 function profilePage(){
  const u=session.user,nameLocked=u.authProvider==='discord';
  $('#content').innerHTML=`<section class="panel register-panel"><div class="register-heading"><img class="register-avatar" src="${escapeHTML(u.avatar)}" alt="Avatar de ${escapeHTML(u.displayName)}"><div><p class="eyebrow">MON REGISTRE</p><h2>${escapeHTML(u.displayName)}</h2><p>${escapeHTML(session.localPreview?u.role.name:u.supreme?'Administrateur Suprême':u.role.name)}</p></div></div><dl class="register-details"><div><dt>${u.authProvider==='access_code'?'Compte du site':'Compte Discord'}</dt><dd>${escapeHTML(u.discordName)}</dd></div><div><dt>Identifiant permanent</dt><dd>${escapeHTML(u.id)}</dd></div><div><dt>Entrée au registre</dt><dd>${when(u.createdAt)}</dd></div><div><dt>Dernière connexion</dt><dd>${when(u.lastLogin)}</dd></div></dl><form id="secure-profile-form"><label class="field">${nameLocked?'Surnom sur le serveur Discord':'Pseudo sur L’Héritage'}<input name="displayName" value="${escapeHTML(u.displayName)}" ${nameLocked?'readonly aria-describedby="discord-name-note"':'required maxlength="60"'}></label>${nameLocked?'<p class="form-note" id="discord-name-note">Ce pseudo suit automatiquement ton surnom sur le serveur. Tu peux le modifier dans Discord.</p>':''}<label class="field">Photo sur L’Héritage<input name="photo" type="file" accept="image/jpeg,image/png,image/webp"></label><p class="form-note">JPG, PNG ou WebP · 10 Mo maximum. Ces changements concernent uniquement L’Héritage.</p><div class="register-actions"><button class="button primary" type="submit">Enregistrer mon profil →</button><button class="button glass" type="button" id="restore-discord-profile">Rétablir mon profil Discord</button><button class="button glass" type="button" id="register-logout">Se déconnecter</button></div></form></section>`;
  if(u.authProvider==='access_code')$('#restore-discord-profile').textContent='Rétablir le profil d’origine';
  if(u.authProvider==='local'){$('#restore-discord-profile').textContent='Rétablir le profil de test';$('#register-logout').textContent='Revenir à l’accueil';}
  const profileForm=$('#secure-profile-form');
  if(profileDraft?.userId===u.id){
   if(!nameLocked)profileForm.querySelector('[name=displayName]').value=profileDraft.displayName;
   if(profileDraft.file){try{const transfer=new DataTransfer();transfer.items.add(profileDraft.file);profileForm.querySelector('[name=photo]').files=transfer.files;}catch{toast('Ton pseudo est conservé. Sélectionne à nouveau la photo avant d’enregistrer.');}}
  }
  profileForm.addEventListener('submit',async e=>{
   e.preventDefault();if(e.target.dataset.submitting==='true')return;e.target.dataset.submitting='true';const button=e.target.querySelector('[type=submit]');button.disabled=true;
   try{
    const data=new FormData(e.target),file=data.get('photo');
    if(file?.size>10*1024*1024)throw Error('Choisis une photo de 10 Mo maximum.');
    if(!nameLocked)await api('/api/me/profile',{method:'PATCH',body:{displayName:data.get('displayName')}});
    if(file?.size){const form=new FormData();form.append('file',file);await api('/api/me/avatar',{method:'POST',form});}
    const account=await api('/api/me');profileDraft=null;publishSession(account);if(profileForm.isConnected)profilePage();toast('Ton profil est enregistré.');
   }catch(error){toast(error.message);}finally{button.disabled=false;delete e.target.dataset.submitting;}
  });
  $('#restore-discord-profile').addEventListener('click',async event=>{
   const button=event.currentTarget;if(button.disabled||profileForm.dataset.submitting==='true')return;
   button.disabled=true;profileForm.dataset.submitting='true';
   try{await api('/api/me/profile',{method:'PATCH',body:{resetName:true,resetAvatar:true}});const account=await api('/api/me');profileDraft=null;publishSession(account);if(profileForm.isConnected)profilePage();}
   catch(error){toast(error.message);}
   finally{button.disabled=false;delete profileForm.dataset.submitting;}
  });
  $('#register-logout').addEventListener('click',logout);
 }
 function councilPage(data){window.heritageCouncil(data,{api,when});}
 function pageURL(route,defaults=false){
  if(route==='journal')return '/api/pages/journal?'+(defaults?'':window.heritageJournalQuery());
  const params=new URLSearchParams({view:'screen'});
  const offsets={sales:['sales','events'],machines:['machines'],tombola:['tombola'],history:['history'],team:['team']}[route]||[];
  if(!defaults)for(const key of offsets)if(pageOffsets[key])params.set(key+'Offset',pageOffsets[key]);
  if(route==='sales'){params.set('scope',defaults?'current':salesScope);params.set('q',defaults?'':search);}
  if(route==='machines'){params.set('q',defaults?'':machineSearch);params.set('status',defaults?'all':machineFilter);}
  if(route==='tombola')params.set('week',defaults?weekKey():tombolaWeek||weekKey());
  if(route==='stats')params.set('report',defaults?'current':machineStatsWeek);
  return '/api/pages/'+encodeURIComponent(route)+'?'+params;
 }
 // Les données privées restent uniquement en mémoire, liées au compte et à ses droits.
 // Les vues de départ sont chargées en un groupe ; les filtres gardent leurs propres clés.
 function bootstrapError(message){const error=new Error(message);error.clientKind='unexpected';window.heritageReportError?.('unexpected');return error;}
 async function preloadPages(routes=null,{resync=true}={}){
  if(!session)return false;
  const selected=(routes||session.pages.map(page=>page.id)).filter((route,index,all)=>can(route)&&all.indexOf(route)===index);
  if(!selected.length)return true;
  const epoch=cacheEpoch,scope=sessionScope(session),defaults=Object.fromEntries(selected.map(route=>[route,pageURL(route,true)]));
  const existing=[...bootstrapTasks].find(task=>task.epoch===epoch&&task.scope===scope&&selected.every(route=>task.routes.includes(route)));
  if(existing)return existing.promise;
  const task={epoch,scope,routes:selected,promise:null};
  task.promise=(async()=>{
   const query=routes?'?'+new URLSearchParams(selected.map(route=>['pages',route])):'';
   let data;
   try{
    // An unchanged visible screen needs only an authenticated version check.
    const route=selected.length===1&&versionedRoutes.has(selected[0])?selected[0]:null;
    const cached=route?cachedPage(defaults[route]):null;
    if(cached?.version){
     const pageResponse={},page=await api(defaults[route],{cached,pageResponse,background:true});
     data={pages:{[route]:page},versions:{[route]:pageResponse.version},
           identity:{userId:session.user.id,roleId:session.user.role.id}};
    }else data=await api('/api/bootstrap'+query);
    if(epoch!==cacheEpoch||scope!==sessionScope(session))return false;
    if(!data||typeof data.pages!=='object'||!data.pages||Array.isArray(data.pages)||typeof data.versions!=='object'||!data.versions||!data.identity)throw bootstrapError('Le chargement du domaine est incomplet. Réessaie.');
    if(typeof data.identity!=='object'||Array.isArray(data.identity)||![data.identity.userId,data.identity.roleId].every(id=>typeof id==='string'&&/^(?:[0-9]{1,24}|local-preview|guest-[0-9a-f]{32}|access-code)$/.test(id)))throw bootstrapError('Le serveur a renvoyé une identité invalide. Réessaie.');
    if(data.identity.userId!==session.user.id||data.identity.roleId!==session.user.role.id){const error=new Error('Ton accès au domaine a été actualisé.');error.sessionChanged=true;throw error;}
    const keys=Object.keys(data.pages);
    if(keys.length!==selected.length||keys.some(route=>!selected.includes(route))||Object.keys(data.versions).length!==selected.length||selected.some(route=>!Object.hasOwn(data.pages,route)||!data.pages[route]||typeof data.pages[route]!=='object'||Array.isArray(data.pages[route])||!/^[0-9a-f]{64}$/.test(data.versions[route]||'')))throw bootstrapError('Le serveur a renvoyé des données de page invalides. Réessaie.');
    for(const route of selected)rememberPage(defaults[route],route,data.pages[route],data.versions[route]);
    return true;
   }catch(error){
    if(error.cancelled)throw error;
    if(resync&&(error.sessionChanged||error.status===403)){
     clearPageCache();await checkSession();return preloadPages(null,{resync:false});
    }
    if(error.sessionChanged){error.sessionChanged=false;error.clientKind='unexpected';error.message='Le serveur n’a pas pu confirmer ton accès au domaine. Réessaie dans quelques instants.';window.heritageReportError?.('unexpected');}
    throw error;
   }
  })();
  bootstrapTasks.add(task);
  try{return await task.promise;}finally{bootstrapTasks.delete(task);}
 }
 async function ensurePreloaded(routes=null){
  for(let attempt=0;attempt<2;attempt++)if(await preloadPages(routes))return true;
  throw new Error('Les données sont en cours de modification. Réessaie dans un instant.');
 }
 function backgroundFailure(error){
  if(error.cancelled)return;
  if(error.status===401){publishSession(null);visibleDomain(false);$('.entry-demo-note').textContent=error.message;}
  else if(error.status===403||error.sessionChanged||!$('#content').hasChildNodes())failPage(error);
  // Les autres erreurs sont déjà présentées par api(), sans effacer une saisie.
 }
 function queuePreload(routes=null){
  if(!session)return;
  const scope=sessionScope(session);
  void ensurePreloaded(routes).catch(error=>{if(scope===sessionScope(session))backgroundFailure(error);});
 }
 function recordVisit(route){
  if(lastVisited===route)return;
  lastVisited=route;const scope=sessionScope(session);
  void api('/api/visits/'+encodeURIComponent(route),{method:'POST',body:{}}).catch(error=>{if(scope===sessionScope(session))backgroundFailure(error);});
 }
 const refreshingQueries=new Set();
 function refreshQuery(route,url,entry){
  if(url===pageURL(route,true)||performance.now()-entry.at<REFRESH_INTERVAL||refreshingQueries.has(url))return;
  const epoch=cacheEpoch,scope=sessionScope(session),pageResponse=versionedRoutes.has(route)?{}:undefined;
  refreshingQueries.add(url);
  void api(url,{cached:pageResponse?entry:undefined,pageResponse}).then(data=>{
   if(epoch!==cacheEpoch||scope!==sessionScope(session))return;
   rememberPage(url,route,data,pageResponse?.version);
   if(activePage===route&&pageURL(route)===url&&!document.querySelector('dialog[open]')&&!document.activeElement?.matches('input,select,textarea'))void window.heritageNavigate({preserveFocus:true});
  }).catch(error=>{if(epoch===cacheEpoch&&scope===sessionScope(session))backgroundFailure(error);}).finally(()=>refreshingQueries.delete(url));
 }
 async function checkSession(){
  if(sessionCheck)return sessionCheck;
  sessionCheck=(async()=>{const account=await api('/api/me');publishSession(account);return account;})();
  try{return await sessionCheck;}finally{sessionCheck=null;}
 }
 window.heritageFilter=key=>{pageOffsets[key]=0;clearTimeout(filterTimer);filterTimer=setTimeout(()=>void window.heritageNavigate({preserveFocus:true}),300);};
 window.heritageNavigate=async({preserveFocus=false,fresh=false,sessionRefreshed=false,staleRetries=0}={})=>{
  clearTimeout(filterTimer);
  const version=++navigationVersion;
  navigationAbort?.abort();navigationAbort=new AbortController();
  sheetsAbort?.abort();sheetsAbort=null;sheetsVersion++;
  const signal=navigationAbort.signal;
  const focused=preserveFocus?document.activeElement:null,focusId=focused?.id,position=focused?.selectionStart;
  const route=location.hash.slice(1)||landingPage();
  $('#session-resume-loading')?.remove();
  if(!session||route==='welcome'){visibleDomain(false);displayedPage=null;activePage=route;return;}
  if(!sessionConfirmedAt||performance.now()-sessionConfirmedAt>=SESSION_LEASE){
   rememberProfileDraft();
   if(!$('#content').hasChildNodes()){
    $('#content').innerHTML=window.heritageLoadingMarkup('Vérification de tes accès…');
    displayedPage=null;
   }
   $('#content').hidden=false;$('#content').setAttribute('aria-busy','true');
   try{await checkSession();}catch(error){if(!error.cancelled&&version===navigationVersion){if(error.status===401)backgroundFailure(error);else failPage(error);}return false;}
   if(version!==navigationVersion)return false;
  }
  visibleDomain(true);activePage=route;
  const descriptor=session.pages.find(p=>p.id===route);
  updatePageHeading(route,descriptor?.label||'Accès réservé');
  const content=$('#content'),samePage=displayedPage===route;
  const url=pageURL(route),entry=!fresh?cachedPage(url):null;
  const epoch=cacheEpoch;
  let showing=samePage,shownJson=samePage?JSON.stringify(state):null;
  content.setAttribute('aria-busy',entry?'false':'true');content.classList.remove('is-refreshing');
  if(!samePage){content.replaceChildren();displayedPage=null;}
  let loading=entry?null:setTimeout(()=>{
   if(version!==navigationVersion)return;
   if(showing)content.classList.add('is-refreshing');
   else content.innerHTML=window.heritageLoadingMarkup('Ouverture du registre…');
  },LOADING_DELAY);
  function showData(data,incremental=false){
   const selected=document.activeElement,inputId=selected?.id,selection=selected?.selectionStart;
   state=data;render({incremental});applyAccessUI();displayedPage=route;showing=true;content.hidden=false;
   if(inputId){const input=document.getElementById(inputId);if(input&&input!==selected){input.focus({preventScroll:true});if(typeof selection==='number'&&input.setSelectionRange)input.setSelectionRange(selection,selection);}}
  }
  try{
   if(!descriptor){const error=new Error('Ton rôle prioritaire ne permet pas cet accès.');error.status=403;throw error;}
   const pageResponse=versionedRoutes.has(route)?{}:undefined;
   let data;
   try{
    if(entry)data=JSON.parse(entry.json);
    else if(url===pageURL(route,true)){
     await ensurePreloaded([route]);
     const preloaded=cachedPage(url);
     if(!preloaded)throw bootstrapError('Les données de cette page n’ont pas pu être conservées. Réessaie.');
     data=JSON.parse(preloaded.json);
    }else data=await api(url,{signal,pageResponse});
   }
   catch(error){
    if(!error.sessionChanged)throw error;
    if(sessionRefreshed){error.sessionChanged=false;error.clientKind='unexpected';error.message='Le serveur n’a pas pu confirmer ton accès à cette page. Réessaie dans quelques instants.';window.heritageReportError?.(error.clientKind);window.heritageFeedback?.show({title:'Chargement impossible',message:error.message,key:url});throw error;}
    clearPageCache();
    await checkSession();
    if(version!==navigationVersion)return;
    return await window.heritageNavigate({preserveFocus,sessionRefreshed:true});
   }
   if(version!==navigationVersion)return;
   if(epoch!==cacheEpoch)return await window.heritageNavigate({preserveFocus,sessionRefreshed});
   recordVisit(route);
   if(route==='profile'){profilePage();displayedPage=route;content.hidden=false;return true;}
   if(route==='council'){councilPage(data);displayedPage=route;content.hidden=false;return true;}
   if(route==='journal'){window.heritageJournal({data,api,signal,when});displayedPage=route;content.hidden=false;return true;}
   if(epoch===cacheEpoch&&!entry&&url!==pageURL(route,true))rememberPage(url,route,data,pageResponse?.version);
   if(Object.hasOwn(pages,route)){if(shownJson!==JSON.stringify(data)||!content.hasChildNodes())showData(data,showing&&content.hasChildNodes());}else content.innerHTML='<p class="empty">Cet espace est enregistré ; son interface sera disponible prochainement.</p>';
   content.hidden=false;
   if(focusId){const input=document.getElementById(focusId);input?.focus({preventScroll:true});if(typeof position==='number'&&input?.setSelectionRange)input.setSelectionRange(position,position);}
   if(entry)refreshQuery(route,url,entry);
   return true;
  }catch(error){if(version!==navigationVersion)return false;if(error.staleRead&&staleRetries<2)return await window.heritageNavigate({preserveFocus,sessionRefreshed,staleRetries:staleRetries+1});if(error.cancelled&&!error.staleRead)return false;if(!error.status&&!error.clientKind)window.heritageReportError?.('script');if(error.status===401){publishSession(null);location.assign('/?login_error='+(error.reason==='employee_required'?'employee_required':error.reason==='site_access_revoked'?'site_access_revoked':'session'));}else failPage(error);return false;}
  finally{clearTimeout(loading);if(version===navigationVersion){content.setAttribute('aria-busy','false');content.classList.remove('is-refreshing');}}
 };
 // Machines refresh: fetch confirmed snapshots even when all actions originate in Discord.
 let machineRefreshInFlight=false,lastMachineRefresh=0;
 async function refreshMachineSnapshot(){
  if(!session||!['machines','sales','tombola','overview','stats'].includes(activePage)||document.hidden||refreshingPages||machineRefreshInFlight||pendingActions.size
      ||document.querySelector('dialog[open], #content[aria-busy="true"]')||document.activeElement?.matches('input,select,textarea'))return;
  const interval=[...(state.machineCommands||[]),...(state.businessCommands||[])].some(job=>job.status==='pending')?15000:30000;
  const now=Date.now();if(now-lastMachineRefresh<interval)return;
  machineRefreshInFlight=true;lastMachineRefresh=now;
  try{await window.heritageNavigate({fresh:true,preserveFocus:true});}
  catch(error){backgroundFailure(error);}
  finally{machineRefreshInFlight=false;}
 }
 setInterval(()=>void refreshMachineSnapshot(),15000);
 // End Machines refresh.
 async function performAction(action,id,values,requestKey){
  if(action==='company-history'){
   if(!session?.user.supreme||!can('stats'))throw Error('Cet accès est réservé à l’administrateur suprême.');
   const payload=companyHistorySubmission(values);
   await api('/api/admin/company-history',{method:'POST',body:{...payload,operationKey:requestKey,expectedId:id||null}});
   const refreshed=await window.heritageNavigate({fresh:true,preserveFocus:true});
   toast(refreshed?'Total de départ enregistré.':'Total enregistré. Actualise la page pour le consulter.');return;
  }

  const page=actionPage(action);if(!page)throw Error('Action inconnue.');
  const result=await api('/api/actions/'+page,{method:'POST',requestKey,body:{action,id:id||null,values}});
  if(action==='add-sale'||action==='confirm-sales-reset'){salesScope='current';search='';pageOffsets.sales=0;pageOffsets.events=0;}
  const refreshed=await window.heritageNavigate({fresh:true,preserveFocus:true});
  toast(result.pending?(refreshed?'Demande en attente du bot. L’opération sera confirmée après exécution.':'Demande envoyée au bot. Actualise la page pour suivre sa confirmation.'):refreshed?'Opération enregistrée dans la base du site.':'Opération enregistrée, mais l’affichage n’a pas pu être actualisé.');
 }
 window.heritageAction=async(action,id,values)=>{
  const key=JSON.stringify([action,id||null,values]);
  if(pendingActions.has(key))return pendingActions.get(key);
  const token=operationKeys.get(key)||localId();operationKeys.set(key,token);
  const task=performAction(action,id,values,token);pendingActions.set(key,task);
  try{const result=await task;operationKeys.delete(key);return result;}
  catch(error){if(!error.uncertain)operationKeys.delete(key);throw error;}
  finally{pendingActions.delete(key);}
 };
 $('#form-dialog').addEventListener('close',()=>{if(formMode==='company-history')for(const key of operationKeys.keys())if(key.startsWith('["company-history",'))operationKeys.delete(key);});
 window.heritageCatalog=async()=>{
  if(!catalogCache)catalogCache=(await api('/api/pages/tombola?view=catalog')).catalog;
  state.catalog=catalogCache;
  const list=$('#vehicle-catalog');if(list)list.innerHTML=[...new Set([...catalogCache.voitures,...catalogCache.motos])].map(name=>`<option value="${escapeHTML(name)}"></option>`).join('');
 };
 window.heritageHistoryExport=async()=> (await api('/api/pages/history?view=export',{exporting:true})).events;
 async function loadSheets(retries=0){
  const container=$('#sheet-archive-content');if(!container)return;
  sheetsAbort?.abort();sheetsAbort=new AbortController();
  const controller=sheetsAbort,version=++sheetsVersion;
  container.setAttribute('aria-busy','true');
  container.innerHTML=window.heritageLoadingMarkup('Chargement des archives…');
  try{const data=await api('/api/pages/machines?view=sheets&sheetsOffset='+pageOffsets.sheets,{signal:controller.signal});if(version!==sheetsVersion||!container.isConnected)return;state.machineSheetHistory=data.machineSheetHistory;state.pagination={...state.pagination,...data.pagination};container.innerHTML=sheetArchiveContent();}
  catch(error){if(error.staleRead&&retries<2&&version===sheetsVersion&&container.isConnected)return await loadSheets(retries+1);if((!error.cancelled||error.staleRead)&&version===sheetsVersion&&container.isConnected)container.innerHTML='<p class="empty">Les archives n’ont pas pu être chargées.</p><button class="button glass" id="retry-sheets" type="button">Réessayer</button>';}
  finally{if(version===sheetsVersion&&container.isConnected)container.setAttribute('aria-busy','false');}
 }
 document.addEventListener('toggle',event=>{if(event.target.matches?.('.machine-sheet-archive')&&event.target.isConnected){if(event.target.open)void loadSheets();else{sheetsAbort?.abort();sheetsVersion++;}}},true);
 document.addEventListener('click',event=>{
  if(event.target.closest('#retry-sheets')){void loadSheets();return;}
  const button=event.target.closest('[data-page-offset]');if(!button||button.disabled)return;
  const key=button.dataset.pageOffset;if(!Object.hasOwn(pageOffsets,key))return;
  pageOffsets[key]=Number(button.dataset.offset);
  if(key==='sheets')void loadSheets();else void window.heritageNavigate({preserveFocus:true});
 });
 window.heritageResetTestData=async()=>{
  if(!session?.user.supreme||!confirm('Réinitialiser uniquement les données métier de test ? Une sauvegarde sera conservée.'))return;
  try{await api('/api/admin/reset-test-data',{method:'POST',body:{}});machineStatsWeek='current';salesScope='current';tombolaWeek='';for(const key of Object.keys(pageOffsets))pageOffsets[key]=0;await window.heritageNavigate();toast('Données de test réinitialisées.');}catch(error){toast(error.message);}
 };
 async function logout(){if(session?.user.authProvider==='local'){try{await api('/auth/logout',{method:'POST',body:{}});lastVisited=null;location.hash='welcome';}catch(error){toast(error.message);}return;}try{await api('/auth/logout',{method:'POST',body:{}});session=null;window.heritageSession=null;state=seed();location.assign('/');}catch(error){toast(error.message);}}
 function hidePanels(){['profile-menu','notifications-panel','search-results'].forEach(id=>$('#'+id).hidden=true);$('#profile-toggle').setAttribute('aria-expanded','false');$('#notifications-toggle').setAttribute('aria-expanded','false');}
 $('#profile-toggle').addEventListener('click',()=>{const opening=$('#profile-menu').hidden;hidePanels();$('#profile-menu').hidden=!opening;$('#profile-toggle').setAttribute('aria-expanded',String(opening));});
 $('#edit-profile').addEventListener('click',()=>{hidePanels();location.hash='profile';});
 $('#profile-settings').addEventListener('click',()=>{location.hash='profile';});
 $('#logout').addEventListener('click',logout);
 $('#access-code-login-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget;if(form.dataset.busy)return;
  form.dataset.busy='true';const button=form.querySelector('[type=submit]'),notice=$('#access-code-login-status');button.disabled=true;
  notice.hidden=false;notice.textContent='Vérification de ton accès…';
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
  try{
   const values=new FormData(form),response=await fetch('/auth/access-code',{method:'POST',credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({loginName:values.get('loginName'),accessCode:values.get('accessCode')})});
   const result=await response.json();
   if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'La connexion a échoué. Réessaie.');
   form.reset();location.assign('/app#'+(result.landing==='overview'?'overview':'profile'));
  }catch(error){notice.textContent=error.name==='AbortError'?'Le serveur met trop de temps à répondre. Réessaie.':error instanceof TypeError?'Impossible de joindre le serveur. Vérifie ta connexion.':error.message;}
  finally{clearTimeout(timer);button.disabled=false;delete form.dataset.busy;}
 });
 $('#global-search').addEventListener('input',e=>{hidePanels();const q=e.target.value.trim().toLocaleLowerCase('fr');if(!q||!session)return;const result=session.pages.filter(p=>p.label.toLocaleLowerCase('fr').includes(q));$('#search-results').innerHTML=result.map(p=>`<a class="notification-item" href="#${escapeHTML(p.id)}">${escapeHTML(p.label)}</a>`).join('')||'<p>Aucun espace accessible ne correspond.</p>';$('#search-results').hidden=false;});
 $('#notifications-toggle').addEventListener('click',async()=>{const opening=$('#notifications-panel').hidden;hidePanels();if(!opening)return;$('#notifications-toggle').setAttribute('aria-expanded','true');$('#notifications-panel').hidden=false;$('#notifications-panel').innerHTML='<p>Aucun rappel accessible.</p>';if(!can('machines'))return;try{const data=await api('/api/pages/machines?view=active');const items=data.machines.filter(m=>!m.recovered&&!m.cancelled&&remaining(m)===0).map(m=>`<a class="notification-item" href="#machines">Lot #${escapeHTML(m.id)} à récupérer</a>`).join('');$('#notifications-panel').innerHTML='<h3>Rappels des machines</h3>'+(items||'<p>Aucun lot à récupérer pour le moment.</p>');}catch(error){$('#notifications-panel').textContent=error.message;}});
 document.addEventListener('click',e=>{if(!e.target.closest('.account-controls'))hidePanels();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')hidePanels();});
 window.addEventListener('hashchange',hidePanels);
 const estateDateFormatter=new Intl.DateTimeFormat('fr-BE',{dateStyle:'full',timeZone:'Europe/Brussels'});
 const estateClockFormatter=new Intl.DateTimeFormat('fr-BE',{timeStyle:'medium',timeZone:'Europe/Brussels'});
 function clock(){if(document.hidden||document.body.classList.contains('on-entry'))return;const now=new Date();$('#estate-date').textContent=estateDateFormatter.format(now);$('#estate-clock').textContent=estateClockFormatter.format(now);}
 clock();setInterval(clock,1000);
 document.addEventListener('visibilitychange',clock);
 window.addEventListener('heritage:domain-visibility',clock);
 async function boot(){
  $('#enter-demo').disabled=true;
  let account,error;
  try{account=await api('/api/me');}catch(cause){error=cause;}
  const status=account||error?.configuration;
  if(!status)throw error||new Error('Le serveur n’a pas pu vérifier la connexion.');
  $('#enter-demo').disabled=!status.configured&&!status.localPreview;
  if(!status.configured&&!status.localPreview)$('.entry-demo-note').textContent='Connexion Discord en attente de configuration locale.';
  const loginError=status.localPreview?null:new URLSearchParams(location.search).get('login_error');
  if(loginError){const messages={site_access_revoked:'Ton accès au site a été révoqué par le propriétaire.',api_budget_exhausted:'Le plafond des appels Discord du site est atteint. Patiente avant de recommencer la connexion.',configuration:'Connexion Discord en attente de configuration locale.',client_configuration:'Discord refuse la configuration OAuth2. Vérifie le Client Secret OAuth2 dans le fichier privé du serveur de test.',authorization_expired:'L’autorisation Discord a expiré ou a déjà été utilisée. Clique à nouveau sur « Se connecter avec Discord ».',membership:'Ton compte doit appartenir au serveur Discord de L’Héritage pour se connecter.',employee_required:'La connexion est réservée aux membres qui possèdent le rôle Employé du domaine.',discord_unavailable:'Discord n’a pas pu être vérifié. Réessaie dans quelques instants.',discord_rate_limited:'Discord limite temporairement les vérifications. Patiente un instant avant de recommencer.',bot_configuration:'Le bot ne peut pas vérifier les membres du serveur. Sa configuration doit être vérifiée par l’administrateur.',oauth_scope:'L’autorisation Discord est incomplète. Clique à nouveau sur « Se connecter avec Discord ».',cancelled:'Connexion annulée. Tu peux recommencer quand tu le souhaites.',session:'Ta session a expiré ou a été révoquée. Connecte-toi à nouveau.'};$('.entry-demo-note').textContent=messages[loginError]||'Connexion non terminée. Recommence depuis cet accueil.';}
  if(error){if(error.status!==401||error.reason==='employee_required')$('.entry-demo-note').textContent=error.message;visibleDomain(false);return error.status===401&&error.reason!=='employee_required';}
  try{
   publishSession(account);
   const loadingLabel=$('#initial-loading p');if(loadingLabel)loadingLabel.textContent='Préparation de tes espaces…';
   await ensurePreloaded();
   if(location.hash==='#welcome'||loginError){visibleDomain(false);return true;}
   else{
    if(!location.hash)history.replaceState(null,'','/app'+location.search+'#'+landingPage());
    return await window.heritageNavigate();
   }
  }
  catch(error){if(error.status!==401||error.reason==='employee_required'){$('.entry-demo-note').textContent=error.message;window.heritageFeedback?.show({title:'Chargement impossible',message:error.message,key:'/api/bootstrap'});}else publishSession(null);visibleDomain(false);return error.status===401&&error.reason!=='employee_required';}
 }
 window.heritageRetry=async()=>{
  if(!session){if(await boot())window.heritageFeedback?.clear();return;}
  await checkSession();
  await ensurePreloaded();
  if(location.hash==='#welcome'){window.heritageFeedback?.clear();return;}
  if(await window.heritageNavigate()){restoreFormDraft();window.heritageFeedback?.clear();}
 };
 boot().catch(()=>{$('.entry-demo-note').textContent='Impossible de joindre le site. Utilise « Réessayer » pour vérifier la connexion.';visibleDomain(false);}).finally(()=>window.heritageFinishLoading());
 let checkingSession=false,refreshingPages=false;
 async function verifySession(){
  if(!session||document.hidden||checkingSession)return;
  checkingSession=true;
  try{
   const previous=sessionScope(session);await checkSession();
   if(!can(activePage)&&activePage!=='welcome')failPage(Object.assign(new Error('Les autorisations de ton rôle ont changé.'),{status:403}));
   else if(previous!==sessionScope(session)){
    await ensurePreloaded();
    if(activePage!=='welcome')await window.heritageNavigate({preserveFocus:true});
    toast('Ton accès au domaine a été actualisé.');
   }
  }catch(error){if(error.cancelled)return;if(error.status===401){publishSession(null);visibleDomain(false);$('.entry-demo-note').textContent=error.message;if(error.reason==='employee_required')location.assign('/?login_error=employee_required');}else backgroundFailure(error);}
  finally{checkingSession=false;}
 }
 setInterval(verifySession,10000);
 setInterval(async()=>{
  if(!session||document.hidden||activePage==='welcome'||refreshingPages||machineRefreshInFlight)return;
  refreshingPages=true;
  try{
   await checkSession();await ensurePreloaded();
   if(versionedRoutes.has(activePage)&&pageURL(activePage)===pageURL(activePage,true)&&!document.querySelector('dialog[open]')&&!document.activeElement?.matches('input,select,textarea'))await window.heritageNavigate({preserveFocus:true});
  }catch(error){backgroundFailure(error);}
  finally{refreshingPages=false;}
 },REFRESH_INTERVAL);
 let resumeTask=null,deferredResumeRoute=null;
 function resumePrivateView({force=false}={}){
  if(document.hidden||!session||activePage==='welcome'||resumeTask)return resumeTask;
  if(!force&&sessionConfirmedAt&&performance.now()-sessionConfirmedAt<SESSION_LEASE)return;
  rememberProfileDraft();
  const content=$('#content'),scope=sessionScope(session),epoch=cacheEpoch,version=navigationVersion,route=activePage;
  // Keep the already displayed page and its drafts in place during verification.
  // A confirmed revocation still clears the private UI through the usual handlers.
  content.setAttribute('aria-busy','true');
  const task=(async()=>{
   try{
    await checkSession();
    if(version!==navigationVersion)return;
    if(route!==(location.hash.slice(1)||landingPage())){await window.heritageNavigate({preserveFocus:true});return;}
    if(!session){visibleDomain(false);return;}
    if(scope===sessionScope(session)&&epoch===cacheEpoch&&displayedPage===route&&content.hasChildNodes()&&can(route)){
     content.hidden=false;content.setAttribute('aria-busy','false');
     if(versionedRoutes.has(route)){
      if(document.querySelector('dialog[open]')||document.activeElement?.matches('input,select,textarea')||pendingActions.size){await ensurePreloaded([route]);deferredResumeRoute=route;}
      else await window.heritageNavigate({fresh:true,preserveFocus:true});
     }
    }else await window.heritageNavigate({preserveFocus:true});
   }catch(error){
    if(version!==navigationVersion)return;
    if(error.cancelled){if(session)await window.heritageNavigate({preserveFocus:true});else visibleDomain(false);}
    else backgroundFailure(error);
   }finally{
    if(resumeTask===task)resumeTask=null;
    if(version===navigationVersion&&!content.hidden)content.setAttribute('aria-busy','false');
   }
  })();
  resumeTask=task;return task;
 }
 function refreshDeferredResume(){
  if(!deferredResumeRoute||document.hidden||!session||activePage!==deferredResumeRoute||document.querySelector('dialog[open]')||document.activeElement?.matches('input,select,textarea')||pendingActions.size)return;
  deferredResumeRoute=null;void window.heritageNavigate({fresh:true,preserveFocus:true});
 }
 document.addEventListener('focusout',()=>setTimeout(refreshDeferredResume,0));
 document.addEventListener('close',()=>setTimeout(refreshDeferredResume,0),true);
 window.addEventListener('online',()=>void resumePrivateView({force:true}));
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)void resumePrivateView();});
 window.addEventListener('focus',()=>void resumePrivateView());
 window.addEventListener('pageshow',event=>{if(event.persisted){sessionConfirmedAt=0;void resumePrivateView({force:true});}});
})();
