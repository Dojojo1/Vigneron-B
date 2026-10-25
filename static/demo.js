'use strict';
window.heritagePublicDemo=()=>{
 const routes=[...Object.keys(pages),'profile'];
 window.heritageSession={demo:true,user:{displayName:'Visiteur',supreme:false},pages:routes.map(id=>({id,label:pages[id]?.[0]||'Mon profil'}))};
 state=seed();
 state.members=[{displayName:'Visiteur démo',discordName:'Profil de démonstration'}];
 state.catalog={voitures:['Sultan','Elegy','Comet'],motos:['Bati 801','Hakuchou']};
 $('#navigation').innerHTML=window.heritageSession.pages.map(p=>`<a href="#${p.id}" data-page="${p.id}">${icon(pages[p.id]?.[3]||'team')}<span>${escapeHTML(p.label)}</span></a>`).join('');
 $('#profile-name').textContent='Visiteur';$('#profile-role').textContent='Démonstration';$('#profile-avatar').textContent='VD';
 $('#enter-demo').disabled=false;
 $('#enter-demo .entry-button-label').textContent='EXPLORER LE DOMAINE';
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
  if(activePage==='journal'||activePage==='profile'){
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
