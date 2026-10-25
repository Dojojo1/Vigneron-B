'use strict';
// Local test data only. Never makes a network request or changes Discord data.
window.heritageLocalBusiness=()=>{
 const key='heritage.local-business.v1';
 const fields=['sales','machines','tombolaRecords','events','salesWeek'];
 let loadFailed=false;
 try{
  const saved=JSON.parse(localStorage.getItem(key));
  if(saved){if(saved.version!==1||!['sales','machines','tombolaRecords','events'].every(name=>Array.isArray(saved[name]))||!Array.isArray(saved.salesWeek?.archives))throw Error('Données locales invalides');for(const name of fields)state[name]=saved[name];}
 }catch(error){loadFailed=true;toast('Les essais enregistrés n’ont pas pu être chargés. Ils ne seront pas effacés automatiquement.');}
 const record=(list,id)=>{const item=list.find(v=>v.id===id);if(!item)throw Error('Fiche introuvable.');return item;};
 const person=name=>{if(!Object.hasOwn(BOT_RULES.employees,name))throw Error('Choisis un employé du domaine.');return name;};
 const nextId=(list,start)=>String(Math.max(start,...list.map(v=>Number(v.id)||0))+1).padStart(3,'0');
 const summary=()=>{
  let pool=state.machines.filter(m=>m.recovered&&!m.cancelled).reduce((n,m)=>n+m.amount,0);state.allocations={};
  for(const s of [...state.sales].sort((a,b)=>a.created-b.created)){
   const treated=s.status==='cancelled'?0:Math.min(s.amount,(s.baseTreated||0)+pool);state.allocations[s.id]=treated;pool=Math.max(0,pool-Math.max(0,treated-(s.baseTreated||0)));
  }
  const gross=state.sales.filter(s=>s.status!=='cancelled').reduce((n,s)=>n+s.amount,0),treated=Object.values(state.allocations).reduce((n,a)=>n+a,0);
  state.summary={gross,treated,pending:gross-treated,company:gross*.15};
 };
 summary();
 return async(action,id,values={})=>{
  if(loadFailed)throw Error('Les essais existants sont illisibles ou inaccessibles. Aucune nouvelle sauvegarde ne les remplacera. Vérifie le stockage de ce site dans ton navigateur.');
  const next=structuredClone(state),now=Date.now();
  if(action==='raffle-record'){
   const previous=id?record(next.tombolaRecords,id):null,vehicles=[];
   for(let i=0;i<50&&Object.hasOwn(values,'vehicle'+i);i++){
    const name=String(values['vehicle'+i]||'').trim(),type=values['type'+i]||'voiture',raw=String(values['price'+i]??'').trim();
    if(!name||name.length>100||!['voiture','moto'].includes(type))throw Error('Renseigne un modèle et un type pour chaque véhicule.');
    const old=previous?.vehicles[i];vehicles.push({name,type,price:raw?parseAmount(raw,{allowZero:true}):null,bought:old?.bought||false,paid:old?.paid||false});
   }
   if(vehicles.length<2)throw Error('Renseigne au moins deux véhicules pour la tombola.');
   const week=weekKey(values.weekDate||'');
   if(previous)Object.assign(previous,{week,vehicles});else next.tombolaRecords.push({id:localId(),week,vehicles});
  }else if(['vehicle-buy','vehicle-pay','pay-all','reset-payments'].includes(action)){
   const [rid,index]=String(id).split('|'),r=record(next.tombolaRecords,rid);
   if(action==='vehicle-buy'||action==='vehicle-pay'){
    if(!/^\d+$/.test(index||'')||!r.vehicles[Number(index)])throw Error('Véhicule introuvable.');
    const v=r.vehicles[Number(index)],flag=action==='vehicle-buy'?'bought':'paid';v[flag]=!v[flag];
   }else for(const v of r.vehicles){v.paid=action==='pay-all';if(action==='reset-payments')v.bought=false;}
  }else if(action==='add-sale'||action==='sale-detail'){
   const old=id?record(next.sales,id):null,group=String(values.group||'').trim(),giver=String(values.giver||'').trim();
   if(!group||group.length>60||!/^\d{1,20}$/.test(giver))throw Error('Vérifie le groupe et l’identifiant du joueur.');
   if(old?.status==='cancelled')throw Error('Ce dossier est annulé.');
   const data={group,giver,employee:person(values.employee),amount:parseAmount(values.amount,{fallback:old?undefined:BOT_RULES.saleDefault}),receivedDate:saleDate(values.receivedDate)};
   if(old)Object.assign(old,data);else next.sales.push({...data,id:nextId(next.sales,41),created:now,baseTreated:0,status:'active',manualStatus:'waiting',archive:null});
  }else if(['finish-sale','cancel-sale','sale-progress','sale-waiting'].includes(action)){
   const s=record(next.sales,id);if(s.status==='cancelled')throw Error('Ce dossier est annulé.');
   if(action==='finish-sale')Object.assign(s,{status:'finished',receiver:person(values.receiver),returnedDate:saleDate(values.returnedDate)});
   else if(action==='cancel-sale')s.status='cancelled';else Object.assign(s,{status:'active',manualStatus:action==='sale-progress'?'progress':'waiting'});
  }else if(action==='confirm-sales-reset'){
   const p=brusselsParts(),date=new Date(Date.UTC(Number(p.year),Number(p.month)-1,Number(p.day)));date.setUTCDate(date.getUTCDate()+4-(date.getUTCDay()||7));
   const year=date.getUTCFullYear(),week=Math.ceil(((date-new Date(Date.UTC(year,0,1)))/86400000+1)/7),base=`${year}-s${String(week).padStart(2,'0')}`;
   let name=base,sequence=1;while(next.salesWeek.archives.some(a=>a.name===name))name=base+'-'+(++sequence);
   for(const s of next.sales)if(!s.archive)s.archive=name;
   next.salesWeek.archives.push({name,year,week,sequence,closedAt:now,mode:'manual'});next.salesWeek.lastResetDate=`${p.year}-${p.month}-${p.day}`;
  }else if(action==='add-machine'){
   if(next.machines.some(m=>!m.recovered&&!m.cancelled))throw Error('Récupère le lot en cours avant d’en lancer un autre.');
   next.machines.push({id:nextId(next.machines,23),launchedBy:person(values.launcher),amount:parseAmount(values.amount,{fallback:BOT_RULES.machineDefault,maximum:BOT_RULES.machineMaximum}),start:now,recovered:false,machineCount:BOT_RULES.machineCount,nominalUnitAmount:BOT_RULES.machineUnitAmount});
  }else if(['recover','unrecover','cancel-machine','edit-machine-time'].includes(action)){
   const m=record(next.machines,id);if(m.cancelled)throw Error('Ce lot est annulé.');
   if(action==='recover'){if(now<m.start+BOT_RULES.machineDurationMinutes*60000)throw Error('Le cycle de 4 h 45 n’est pas terminé.');Object.assign(m,{recovered:true,recoveredBy:'Visiteur',recoveredAt:now});}
   else if(action==='unrecover'){if(next.machines.some(other=>other.id!==id&&!other.recovered&&!other.cancelled))throw Error('Un autre lot est déjà actif.');m.recovered=false;delete m.recoveredAt;delete m.recoveredBy;}
   else if(action==='cancel-machine')m.cancelled=true;else m.start=correctedLaunch(m.start,String(values.launchTime||''));
  }else throw Error('Cette action n’est pas encore disponible pour les essais locaux.');
  const titles={'raffle-record':'Fiche tombola enregistrée','vehicle-buy':'Achat du véhicule modifié','vehicle-pay':'Paiement du véhicule modifié','pay-all':'Véhicules payés','reset-payments':'Paiements remis en attente','add-sale':'Dossier ajouté','sale-detail':'Dossier modifié','finish-sale':'Dossier restitué','cancel-sale':'Dossier annulé','add-machine':'Lot lancé','recover':'Lot récupéré','unrecover':'Récupération annulée','cancel-machine':'Lot annulé','edit-machine-time':'Heure du lot modifiée','confirm-sales-reset':'Semaine archivée'};
  next.events.unshift({id:localId(),title:titles[action]||'Dossier actualisé',detail:'Essai local · '+action,author:'Visiteur',created:now});
  const saved={version:1};for(const name of fields)saved[name]=next[name];
  try{localStorage.setItem(key,JSON.stringify(saved));}catch{throw Error('Sauvegarde impossible dans ce navigateur. Libère de l’espace ou autorise le stockage ; la modification n’a pas été enregistrée.');}
  state=next;summary();
  if(action==='raffle-record')tombolaWeek=weekKey(values.weekDate||'');
  if(action==='add-sale'||action==='confirm-sales-reset'){salesScope='current';search='';}
  await window.heritageNavigate();toast('Enregistré dans ce navigateur.');
 };
};
