'use strict';
// Searchable catalogue shared by the public interface and the Python site.
(() => {
 let active=null,items=[],position=-1;
 const normalize=value=>value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('fr').trim();
 function close(){
  if(!active)return;
  const menu=active.querySelector('.vehicle-picker-menu');
  if(menu.matches(':popover-open'))menu.hidePopover();menu.hidden=true;
  const input=active.querySelector('[data-vehicle-picker]');
  input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');
  active=null;items=[];position=-1;
 }
 function prepare(input){
  let wrapper=input.closest('.vehicle-picker');if(wrapper)return wrapper;
  const focused=document.activeElement===input;
  const label=input.closest('.field');
  wrapper=document.createElement('div');wrapper.className='vehicle-picker';
  // Keep the existing label association while moving the input into its control.
  input.id='catalogue-'+input.name;label.htmlFor=input.id;
  label.after(wrapper);wrapper.append(label);
  const control=document.createElement('div');control.className='vehicle-picker-control';
  const toggle=document.createElement('button');toggle.type='button';toggle.className='vehicle-picker-toggle';toggle.setAttribute('aria-label','Afficher les modèles');toggle.innerHTML='<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m6 8 4 4 4-4"/></svg>';
  control.append(input,toggle);wrapper.append(control);
  const menu=document.createElement('div');menu.className='vehicle-picker-menu';menu.hidden=true;
  if(typeof menu.showPopover==='function')menu.setAttribute('popover','manual');
  const heading=document.createElement('div');heading.className='vehicle-picker-heading';
  const list=document.createElement('div');list.className='vehicle-picker-options';list.id=input.id+'-options';list.setAttribute('role','listbox');list.setAttribute('aria-label','Modèles du catalogue');
  const status=document.createElement('div');status.className='vehicle-picker-status';status.setAttribute('role','status');
  menu.append(heading,list,status);wrapper.append(menu);
  input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');input.setAttribute('aria-controls',list.id);input.setAttribute('spellcheck','false');
  if(focused)input.focus({preventScroll:true});
  return wrapper;
 }
 function place(){
  if(!active)return;
  const menu=active.querySelector('.vehicle-picker-menu');if(!menu.hasAttribute('popover'))return;
  const rect=active.querySelector('.vehicle-picker-control').getBoundingClientRect();
  const below=innerHeight-rect.bottom-14,above=rect.top-14,up=below<230&&above>below;
  const room=Math.max(120,up?above:below);
  menu.style.width=Math.min(rect.width,innerWidth-24)+'px';
  menu.querySelector('.vehicle-picker-options').style.maxHeight=Math.min(224,room-90)+'px';
  menu.style.left=Math.max(12,Math.min(rect.left,innerWidth-rect.width-12))+'px';
  menu.style.top=(up?Math.max(12,rect.top-menu.getBoundingClientRect().height-7):rect.bottom+7)+'px';
 }
 function open(input){
  const wrapper=prepare(input);if(active!==wrapper)close();active=wrapper;position=-1;
  const type=wrapper.closest('.vehicle-fields').querySelector('input[type=radio]:checked')?.value;
  const catalogue=type==='moto'?state.catalog.motos:state.catalog.voitures;
  const query=normalize(input.value),matches=[...new Set(catalogue||[])].filter(name=>normalize(name).includes(query));
  matches.sort((a,b)=>Number(normalize(b).startsWith(query))-Number(normalize(a).startsWith(query))||a.localeCompare(b,'fr'));
  items=matches.slice(0,60);
  const list=wrapper.querySelector('.vehicle-picker-options');list.replaceChildren();
  for(const [index,name] of items.entries()){
   const option=document.createElement('button');option.type='button';option.tabIndex=-1;option.className='vehicle-picker-option';option.id=list.id+'-'+index;option.setAttribute('role','option');option.setAttribute('aria-selected','false');option.dataset.vehicleOption=String(index);
   const mark=document.createElement('span');mark.className='vehicle-picker-option-mark';mark.innerHTML=vehicleMark(type);
   const text=document.createElement('span');text.textContent=name;
   const arrow=document.createElement('span');arrow.className='vehicle-picker-option-arrow';arrow.textContent='↗';arrow.setAttribute('aria-hidden','true');
   option.append(mark,text,arrow);list.append(option);
  }
  wrapper.querySelector('.vehicle-picker-heading').textContent=type==='moto'?'CATALOGUE · MOTOS':'CATALOGUE · VOITURES';
  wrapper.querySelector('.vehicle-picker-status').textContent=matches.length===0?'Aucun modèle trouvé. Essaie un autre nom.':matches.length>60?`${matches.length} modèles · affine ta recherche`:`${matches.length} modèle${matches.length>1?'s':''} disponible${matches.length>1?'s':''}`;
  const menu=wrapper.querySelector('.vehicle-picker-menu');menu.hidden=false;
  if(menu.hasAttribute('popover')&&!menu.matches(':popover-open'))menu.showPopover();
  input.setAttribute('aria-expanded','true');list.scrollTop=0;place();
 }
 function highlight(index){
  if(!active||!items.length)return;
  position=(index+items.length)%items.length;
  const options=[...active.querySelectorAll('[role=option]')];
  for(const [i,option] of options.entries())option.setAttribute('aria-selected',String(i===position));
  const option=options[position];active.querySelector('input').setAttribute('aria-activedescendant',option.id);option.scrollIntoView({block:'nearest'});
 }
 function choose(index){
  if(!active||!items[index])return;
  const input=active.querySelector('input');input.value=items[index];input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));close();input.focus({preventScroll:true});
 }
 document.addEventListener('focusin',event=>{if(event.target.matches('[data-vehicle-picker]'))open(event.target);});
 document.addEventListener('input',event=>{if(event.target.matches('[data-vehicle-picker]'))open(event.target);});
 document.addEventListener('change',event=>{if(active&&event.target.matches('.vehicle-type-picker input'))close();});
 document.addEventListener('pointerdown',event=>{if(event.target.closest('.vehicle-picker-option,.vehicle-picker-toggle'))event.preventDefault();else if(active&&!active.contains(event.target))close();});
 document.addEventListener('click',event=>{
  const option=event.target.closest('[data-vehicle-option]');if(option){choose(Number(option.dataset.vehicleOption));return;}
  const toggle=event.target.closest('.vehicle-picker-toggle');if(toggle){const input=toggle.closest('.vehicle-picker').querySelector('input');if(active===toggle.closest('.vehicle-picker'))close();else{input.focus();open(input);}}
 });
 document.addEventListener('keydown',event=>{
  if(!event.target.matches('[data-vehicle-picker]'))return;
  if(event.key==='Escape'){if(active){event.preventDefault();event.stopPropagation();close();}return;}
  if(event.key==='Tab'){close();return;}
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();if(!active)open(event.target);highlight(position+(event.key==='ArrowDown'?1:-1));}
  if(event.key==='Enter'&&active&&position>=0){event.preventDefault();choose(position);}
 },true);
 document.addEventListener('focusout',event=>{if(active&&active.contains(event.target)&&!active.contains(event.relatedTarget))close();});
 document.addEventListener('close',close,true);
 window.addEventListener('resize',place);
 document.addEventListener('scroll',event=>{if(active&&!event.target.closest?.('.vehicle-picker-options'))place();},true);
 const fields=document.querySelector('#form-fields');
 new MutationObserver(()=>fields.querySelectorAll('[data-vehicle-picker]').forEach(prepare)).observe(fields,{childList:true,subtree:true});
})();
