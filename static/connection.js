'use strict';
// This file only receives a PUBLIC server address. No credential belongs here.
window.heritageOpenConnectedSite=async(existingConfig)=>{
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
 const codeEntry=document.querySelector('.access-code-entry');
 const codeForm=document.querySelector('#access-code-login-form');
 codeEntry.hidden=true;
 note.textContent='Préparation de la connexion Discord…';showEntry();
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);
 try{
  let config=existingConfig;
  if(!config){
   const response=await fetch(new URL('site-config.json',document.baseURI),{cache:'no-store',signal:controller.signal});
   if(!response.ok)throw Error('Configuration publique indisponible.');
   config=await response.json();
  }
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
  codeEntry.hidden=false;
  if(!codeForm.dataset.connectedLoginReady){
   codeForm.dataset.connectedLoginReady='true';
   codeForm.addEventListener('submit',async event=>{
    event.preventDefault();if(codeForm.dataset.busy)return;
    codeForm.dataset.busy='true';
    const submit=codeForm.querySelector('[type=submit]'),status=document.querySelector('#access-code-login-status');
    submit.disabled=true;status.hidden=false;status.textContent='Vérification de ton accès…';
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);
    try{
     const fields=new FormData(codeForm);
     const response=await fetch(new URL('/auth/access-code',target.origin),{
      method:'POST',credentials:'omit',cache:'no-store',signal:controller.signal,
      headers:{'Content-Type':'application/json',...(/\.ngrok(?:-free)?\.(?:dev|app)$/.test(target.hostname)?{'ngrok-skip-browser-warning':'true'}:{})},
      body:JSON.stringify({loginName:fields.get('loginName'),accessCode:fields.get('accessCode')})});
     const result=await response.json();
     if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'La connexion a échoué. Réessaie.');
     if(!/^[A-Za-z0-9_-]{40,80}$/.test(result.token||''))throw Error('Réponse de connexion invalide.');
     sessionStorage.setItem('heritage.backend-token',result.token);
     codeForm.reset();
     history.replaceState(null,'',location.pathname+location.search+'#'+(result.landing==='overview'?'overview':'profile'));
     location.reload();
    }catch(error){status.textContent=error.name==='AbortError'?'Le serveur met trop de temps à répondre. Réessaie.':error instanceof TypeError?'Impossible de joindre le serveur. Vérifie ta connexion.':error.message;}
    finally{clearTimeout(timeout);submit.disabled=false;delete codeForm.dataset.busy;}
   });
  }
  return true;
 }catch(error){
  window.heritageFeedback?.show({title:'Connexion au domaine indisponible',message:'La configuration du serveur du site n’a pas pu être chargée. Réessaie dans quelques instants.',key:'site-connection'});
  note.textContent='La connexion n’a pas pu être préparée. Utilise « Réessayer ».';
  return null;
 }finally{clearTimeout(timer);window.heritageRetry=()=>location.reload();}
};
