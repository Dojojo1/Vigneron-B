'use strict';
// Loaded before the application so missing resources cannot leave a silent spinner.
(() => {
 const message='Certains fichiers du site ne sont pas disponibles. Actualise la page pour réessayer.';
 const assetRoot=new URL('.',document.currentScript.src).href;
 let failure=null;
 function showFailure(){
  if(!failure||!document.body)return;
  window.heritageStartupFailed=true;
  document.body.setAttribute('aria-busy','false');
  const loader=document.querySelector('#initial-loading');if(loader)loader.hidden=true;
  const notice=document.querySelector('#site-error');if(!notice)return;
  notice.querySelector('h2').textContent='Chargement interrompu';
  notice.querySelector('p').textContent=failure;
  notice.hidden=false;
 }
 window.addEventListener('error',event=>{
  const target=event.target;
  if(target?.tagName==='SCRIPT'&&!target.src.startsWith(assetRoot))return;
  if(target?.tagName==='LINK'&&!target.href.startsWith(assetRoot))return;
  // A failed optional font import still leaves the local stylesheet usable.
  if(target?.tagName==='LINK'&&target.sheet?.cssRules.length)return;
  if(target===window&&event.filename&&!event.filename.startsWith(assetRoot))return;
  if(target?.tagName==='SCRIPT'||target?.tagName==='LINK'&&target.rel==='stylesheet'||target===window&&document.body?.getAttribute('aria-busy')==='true'){
   failure=message;showFailure();
  }
 },true);
 document.addEventListener('DOMContentLoaded',showFailure,{once:true});
 document.addEventListener('click',event=>{
  if(window.heritageStartupFailed&&event.target.closest('[data-error-retry]')){
   event.preventDefault();event.stopImmediatePropagation();location.reload();
  }
 },true);
 window.heritageStartupTimer=setTimeout(()=>{
  if(document.body?.getAttribute('aria-busy')==='true'){
   failure='Le chargement prend trop de temps. Actualise la page pour réessayer.';showFailure();
  }
 },30000);
})();
