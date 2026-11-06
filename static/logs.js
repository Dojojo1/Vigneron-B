'use strict';
(() => {
 window.heritageLogs=({data})=>{
  const empty=Array.isArray(data?.entries)&&data.entries.length===0;
  document.querySelector('#content').innerHTML=`<section class="panel journal-panel logs-panel"><p class="eyebrow">LE REGISTRE DU BOT</p><h2>Logs</h2><p class="form-note">Cette rubrique accueillera les logs envoyés par le bot lorsqu’il sera raccordé.</p><p class="empty">${empty?'Aucun log du bot pour le moment.':'Les logs du bot ne sont pas encore disponibles.'}</p></section>`;
 };
})();
