'use strict';
// This file only receives a PUBLIC server address. No credential belongs here.
window.heritageOpenConnectedSite=async()=>{
 const button=document.querySelector('#enter-demo'),note=document.querySelector('.entry-demo-note');
 let loginURL=null;
 const showEntry=()=>{
  document.querySelector('#entry-screen').hidden=false;
  document.querySelector('main').hidden=true;document.querySelector('#sidebar').hidden=true;
  document.body.classList.add('on-entry');
  window.heritageFinishLoading?.();
 };
 window.heritageSession=null;
 window.heritageNavigate=async()=>{showEntry();return true;};
 window.heritageLogin=()=>{
  if(loginURL)location.assign(loginURL);
 };
 button.disabled=true;button.querySelector('.entry-button-label').textContent='SE CONNECTER AVEC DISCORD';
 document.querySelector('.access-code-entry').hidden=true;
 document.querySelector('#access-code-login-form').addEventListener('submit',event=>event.preventDefault());
 note.textContent='Préparation de la connexion Discord…';showEntry();
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);
 try{
  const response=await fetch(new URL('site-config.json',document.baseURI),{cache:'no-store',signal:controller.signal});
  if(!response.ok)throw Error('Configuration publique indisponible.');
  const config=await response.json();
  if(!config||typeof config!=='object'||Array.isArray(config))throw Error('Configuration publique invalide.');
  if(config.mode==='preview'&&!config.backendUrl){delete window.heritageLogin;return 'preview';}
  if(config.mode&&config.mode!=='connected')throw Error('Mode de connexion invalide.');
  if(!config.backendUrl){note.textContent='La connexion au domaine est en attente de configuration.';return false;}
  if(typeof config.backendUrl!=='string')throw Error('Adresse de connexion invalide.');
  const target=new URL(config.backendUrl);
  if(target.protocol!=='https:'||target.username||target.password||target.pathname!=='/'||target.search||target.hash)throw Error('Adresse de connexion invalide.');
  if(target.origin===location.origin||target.hostname.endsWith('.github.io'))throw Error('Le serveur de connexion doit être distinct de GitHub Pages.');
  loginURL=new URL('/auth/start',target.origin).href;
  button.disabled=false;note.textContent='Connecte-toi avec ton compte Discord pour accéder au domaine.';
  let codeLink=document.querySelector('#connected-access-code');
  if(!codeLink){codeLink=document.createElement('a');codeLink.id='connected-access-code';codeLink.className='connected-access-code';codeLink.textContent='J’ai un code d’accès';note.after(codeLink);}
  codeLink.href=new URL('/#welcome',target.origin).href;
  return true;
 }catch(error){
  window.heritageFeedback?.show({title:'Connexion au domaine indisponible',message:'La configuration du serveur du site n’a pas pu être chargée. Réessaie dans quelques instants.',key:'site-connection'});
  note.textContent='La connexion n’a pas pu être préparée. Utilise « Réessayer ».';
  return null;
 }finally{clearTimeout(timer);window.heritageRetry=()=>location.reload();}
};
