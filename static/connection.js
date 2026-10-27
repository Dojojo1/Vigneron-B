'use strict';
// This file only receives a PUBLIC server address. No credential belongs here.
window.heritageOpenConnectedSite=async()=>{
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);
 try{
  const response=await fetch(new URL('site-config.json',document.baseURI),{cache:'no-store',signal:controller.signal});
  if(!response.ok)throw Error('Configuration publique indisponible.');
  const config=await response.json();
  if(!config.backendUrl)return false;
  const target=new URL(config.backendUrl);
  if(target.protocol!=='https:'||target.username||target.password||target.pathname!=='/'||target.search||target.hash)throw Error('Adresse de connexion invalide.');
  if(target.origin===location.origin||target.hostname.endsWith('.github.io'))throw Error('Le serveur de connexion doit être distinct de GitHub Pages.');
  target.hash=location.hash||'#welcome';
  location.replace(target.href);return true;
 }catch(error){
  window.heritageFeedback?.show({title:'Connexion au domaine indisponible',message:'La configuration du serveur du site n’a pas pu être chargée. Réessaie dans quelques instants.',key:'site-connection'});
  return null;
 }finally{clearTimeout(timer);}
};
