'use strict';
(() => {
 const assetRoot=new URL('.',document.currentScript.src).href;
 const notice=document.querySelector('#site-error');
 const title=notice.querySelector('h2'),message=notice.querySelector('p');
 const retry=notice.querySelector('[data-error-retry]');
 window.heritageFinishLoading=()=>{
  clearTimeout(window.heritageStartupTimer);
  const loader=document.querySelector('#initial-loading');if(loader)loader.hidden=true;
  document.body.setAttribute('aria-busy','false');
 };
 window.heritageLoadingMarkup=(label='Chargement des informations…')=>`<div class="loading-state" role="status"><span class="loading-spinner" aria-hidden="true"></span><span>${label}</span><div class="loading-skeleton" aria-hidden="true"><i></i><i></i><i></i></div></div>`;
 let currentKey=null,dismissedKey=null,dismissedUntil=0;
 function show({title:heading='Un problème est survenu',message:detail='Le site n’a pas pu terminer cette demande.',key='unexpected'}={}){
  if(key===dismissedKey&&Date.now()<dismissedUntil)return;
  window.heritageFinishLoading();
  const parent=[...document.querySelectorAll('dialog[open]')].at(-1)||document.body;
  if(notice.parentElement!==parent)parent.append(notice);
  currentKey=key;
  title.textContent=heading;message.textContent=detail;notice.hidden=false;
 }
 function clear(){notice.hidden=true;currentKey=null;}
 window.heritageFeedback={show,clear,recovered:key=>{if(currentKey===key)clear();}};
 notice.querySelector('[data-error-dismiss]').addEventListener('click',()=>{
  dismissedKey=currentKey;dismissedUntil=Date.now()+30000;clear();
 });
 retry.addEventListener('click',async()=>{
  retry.disabled=true;retry.textContent='Vérification…';
  try{
   if(window.heritageRetry)await window.heritageRetry();
   else location.reload();
  }catch{show({message:'Le site ne répond toujours pas. Attends quelques instants, puis réessaie.',key:currentKey||'retry'});}
  finally{retry.disabled=false;retry.textContent='Réessayer';}
 });
 document.addEventListener('close',()=>{
  if(notice.closest('dialog')&&!notice.closest('dialog').open)document.body.append(notice);
 },true);
 window.addEventListener('offline',()=>{window.heritageReportError?.('offline');show({title:'Connexion interrompue',message:'Le navigateur n’a plus de connexion. Tes champs restent remplis. Réessaie lorsque la connexion revient.',key:'offline'});});
 window.addEventListener('error',event=>{
  // Une photo ou une vidéo manquante ne doit pas annoncer une panne du site.
  if(event.target!==window&&event.target?.tagName!=='SCRIPT')return;
  if(event.target?.tagName==='SCRIPT'&&!event.target.src.startsWith(assetRoot))return;
  if(event.target===window&&event.filename&&!event.filename.startsWith(assetRoot))return;
  window.heritageReportError?.('script');
  show({message:'Une partie du site n’a pas pu fonctionner correctement. Réessaie ou actualise la page si le problème persiste.',key:'script'});
 },true);
 window.addEventListener('unhandledrejection',()=>{window.heritageReportError?.('unexpected');show({message:'Une action n’a pas pu se terminer. Vérifie l’historique avant de refaire une opération.',key:'unexpected'});});
})();
