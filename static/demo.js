'use strict';
window.heritagePublicDemo=()=>{
 const routes=[...Object.keys(pages),'profile','council','external-access'];
 const labels={profile:'Mon profil',council:'Droits et grades Discord','external-access':'Accès extérieurs'};
 window.heritageSession={demo:true,user:{displayName:'Visiteur',supreme:false},pages:routes.map(id=>({id,label:pages[id]?.[0]||labels[id]}))};
 const privatePages=Object.keys(pages).map(id=>({id,label:pages[id][0],kind:'private'}));
 const exampleRoles=['👑 · Patron','👑 · Co Patron','⚜ · DRH','👔 · Ressource Humaine','🤝 · Responsable Commercial','🎉 · Responsable événementiel','🍇 · Ouvrier Viticole','🌱 · Saisonnier','💼 · Partenaire'].map((name,i)=>({id:'example-'+i,name,position:100-i,active:true}));
 let settings={selectedRoles:exampleRoles.slice(0,6).map(r=>r.id),permissions:{},users:[]};
 try{const saved=JSON.parse(localStorage.getItem('heritage.preview.access.v1'));if(saved&&Array.isArray(saved.selectedRoles)&&saved.permissions&&Array.isArray(saved.users))settings=saved;}catch{}
 const persist=()=>{try{localStorage.setItem('heritage.preview.access.v1',JSON.stringify(settings));}catch{toast('Les réglages restent disponibles pendant cette visite ; le stockage du navigateur est indisponible.');}};
 const when=seconds=>new Intl.DateTimeFormat('fr-BE',{dateStyle:'medium',timeStyle:'short'}).format(new Date(seconds*1000));
 async function previewAPI(path,{method='GET',body={}}={}){
  if(path==='/api/admin/access'&&method==='PUT'){settings.selectedRoles=body.selectedRoles;settings.permissions=body.permissions;persist();return {};}
  if(path==='/api/admin/users')return {users:settings.users};
  const code=()=> 'APERCU-'+localId();
  if(path==='/api/admin/access-accounts'&&method==='POST'){
   if(settings.users.some(u=>u.siteAccess.loginName.toLowerCase()===String(body.loginName).toLowerCase()))throw new Error('Ce pseudo est déjà utilisé dans cet aperçu.');
   const account={id:'preview-'+localId(),username:body.displayName,display_name:body.displayName,last_login:Date.now()/1000,role_ids:'[]',member:false,protected:false,siteAccess:{provider:'access_code',loginName:body.loginName,pages:body.pages,blocked:false}};
   settings.users.push(account);persist();return {account:{loginName:body.loginName},accessCode:code()};
  }
  const match=path.match(/^\/api\/admin\/(?:access-accounts|accounts)\/([^/]+)(?:\/(site-access|rotate-code))?$/);
  if(match){const user=settings.users.find(u=>u.id===decodeURIComponent(match[1]));if(!user)throw new Error('Compte introuvable.');
   if(match[2]==='rotate-code')return {account:{loginName:user.siteAccess.loginName},accessCode:code()};
   if(match[2]==='site-access')user.siteAccess.blocked=body.blocked;else if(method==='PATCH')user.siteAccess.pages=body.pages;else throw new Error('Action indisponible.');
   persist();return {};
  }
  throw new Error('Cette opération n’est pas disponible dans l’aperçu local.');
 }
 function accessPanel(route){
  updatePageHeading(route,labels[route]);$('#page-title').textContent=labels[route];
  $('#page-subtitle').textContent=route==='council'?'Sélection des rôles et autorisations par rubrique.':'Des accès individuels pour les personnes hors du Discord.';
  const permissions=Object.entries(settings.permissions).flatMap(([role,values])=>Object.entries(values).map(([page,allowed])=>({role_id:role,page_id:page,allowed})));
  window.heritageCouncil({access:{roles:exampleRoles,pages:privatePages,selectedRoles:settings.selectedRoles,permissions},accounts:{users:settings.users}},{api:previewAPI,when});
  const individual=$('#individual-access');
  if(route==='external-access')for(const child of [...$('#content').children]){if(child!==individual)child.remove();}
  else individual.remove();
  const info=document.createElement('p');info.className='panel form-note';info.textContent='Réglages de préparation conservés dans ce navigateur. Grades d’exemple : les vrais rôles Discord seront récupérés lors du raccordement au serveur. Les codes d’aperçu ne permettent aucune connexion réelle.';$('#content').prepend(info);
  if(route==='external-access'){$('#individual-access > h2').textContent='Accès extérieurs';$('#individual-access > p:not(.eyebrow)').textContent='Choisis les rubriques visibles pour un comptable ou un partenaire. Tu peux essayer la création, les catégories et la révocation ici, sans modifier les accès réels.';}
 }
 state=seed();
 state.members=[{displayName:'Visiteur démo',discordName:'Profil de démonstration'}];
 state.catalog={voitures:['Sultan','Elegy','Comet'],motos:['Bati 801','Hakuchou']};
 $('#navigation').innerHTML=window.heritageSession.pages.map(p=>`<a href="#${p.id}" data-page="${p.id}">${icon(pages[p.id]?.[3]||'team')}<span>${escapeHTML(p.label)}</span></a>`).join('');
 $('#profile-name').textContent='Visiteur';$('#profile-role').textContent='Démonstration';$('#profile-avatar').textContent='VD';
 $('#enter-demo').disabled=false;
 $('#enter-demo .entry-button-label').textContent='ENTRER DANS LE DOMAINE';
 $('.entry-demo-note').textContent='Démonstration · données fictives · aucun lien avec le bot Discord.';
 $('.access-code-entry').hidden=true;
 $('#access-code-login-form').addEventListener('submit',event=>event.preventDefault());
 $('footer > span:last-child').firstChild.textContent='Démonstration · données fictives ';
 $('#reset-demo').hidden=true;
 function entry(show){
  $('#entry-screen').hidden=!show;$('main').hidden=show;$('#sidebar').hidden=show;
  $('body').classList.toggle('on-entry',show);
  window.dispatchEvent(new Event('heritage:domain-visibility'));
 }
 window.heritageNavigate=async()=>{
  const route=location.hash.slice(1)||'welcome';closeMenu();
  if(route==='welcome'){activePage='welcome';entry(true);return true;}
  activePage=routes.includes(route)?route:'overview';entry(false);
  if(activePage==='council'||activePage==='external-access')accessPanel(activePage);
  else if(activePage==='journal'||activePage==='profile'){
   updatePageHeading(activePage);
   $('#content').innerHTML=activePage==='journal'?'<section class="panel"><h2>Journal du domaine</h2><p>Les futures opérations apparaîtront ici. Aucune donnée Discord n’est chargée dans cette démonstration.</p></section>':'<section class="panel"><h2>Profil de démonstration</h2><p>Tu explores le domaine en tant que visiteur. La connexion Discord sera raccordée ultérieurement.</p></section>';
  }else render();
  return true;
 };
 window.heritageRetry=async()=>{await window.heritageNavigate();window.heritageFeedback?.clear();};
 window.heritageFilter=()=>void window.heritageNavigate();
 window.heritageCatalog=async()=>{const list=$('#vehicle-catalog');if(list)list.innerHTML=[...state.catalog.voitures,...state.catalog.motos].map(name=>`<option value="${escapeHTML(name)}"></option>`).join('');};
 window.heritageHistoryExport=async()=>state.events;
 window.heritageAction=async()=>{throw new Error('Aperçu du formulaire : l’enregistrement des opérations sera ajouté ensuite. Aucune donnée n’a été envoyée au bot.');};
 for(const id of ['logout','edit-profile','profile-settings'])$('#'+id).addEventListener('click',()=>{location.hash=id==='logout'?'welcome':'profile';});
 $('#profile-toggle').addEventListener('click',()=>{const menu=$('#profile-menu');menu.hidden=!menu.hidden;$('#profile-toggle').setAttribute('aria-expanded',String(!menu.hidden));});
 $('#notifications-toggle').addEventListener('click',()=>{const panel=$('#notifications-panel');panel.hidden=!panel.hidden;panel.innerHTML='<p>Aucune notification de démonstration.</p>';$('#notifications-toggle').setAttribute('aria-expanded',String(!panel.hidden));});
 $('#global-search').addEventListener('input',e=>{const q=e.target.value.trim().toLocaleLowerCase('fr'),result=$('#search-results');result.hidden=!q;result.innerHTML=window.heritageSession.pages.filter(p=>p.label.toLocaleLowerCase('fr').includes(q)).map(p=>`<a class="notification-item" href="#${p.id}">${escapeHTML(p.label)}</a>`).join('')||'<p>Aucun espace trouvé.</p>';});
 window.addEventListener('hashchange',()=>{for(const id of ['profile-menu','notifications-panel','search-results'])$('#'+id).hidden=true;});
 void window.heritageNavigate();window.heritageFinishLoading();
};
