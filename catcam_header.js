/* One shared header for Dashboard, Settings, Gallery, Bird Activity and capture details. */
(function(){
  'use strict';
  const root=document.getElementById('catcam-header');
  if(!root)return;
  const path=location.pathname;
  const onHome=path==='/'||path==='/index.html';
  const onActivity=path==='/bird-activity';
  const onGallery=path==='/gallery'||path==='/bird-gallery'||path==='/event';
  const darkId=onHome||path==='/event'?'darkToggle':'dark';
  const brand=document.createElement('a');brand.className='catcam-brand';brand.href='/?tab=dashboard';
  brand.innerHTML='<span class="catcam-brand-mark">🐦</span><span class="catcam-brand-name">CatCam</span><span class="catcam-brand-caption">Wildlife Camera</span>';
  const status=document.createElement('div');status.className='catcam-status';
  const camera=document.createElement('span');camera.id='cameraState';camera.textContent='● Checking…';
  const bird=document.createElement('span');bird.innerHTML='<strong>●</strong> Bird detection';
  status.append(camera,bird);
  const nav=document.createElement('nav');nav.className='catcam-nav';nav.setAttribute('aria-label','Main navigation');
  const entries=[['Dashboard','/','dashboard'],['Gallery','/gallery','gallery'],['Bird Activity','/bird-activity','activity'],['Settings','/?tab=settings','settings']];
  for(const [label,url,key] of entries){
    const el=document.createElement(onHome&&(key==='dashboard'||key==='settings')?'button':'a');
    el.textContent=label;
    if(el.tagName==='A')el.href=url;
    if(onHome&&(key==='dashboard'||key==='settings')){el.type='button';el.dataset.tab=key;}
    if((onGallery&&key==='gallery')||(onActivity&&key==='activity')){el.classList.add('active');el.setAttribute('aria-current','page');}
    nav.append(el);
  }
  const mode=document.createElement('label');mode.className='catcam-mode';mode.textContent='☾ Dark mode ';
  const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.id=darkId;mode.append(checkbox);
  root.append(brand,status,nav,mode);
  // The dashboard and capture-detail pages retain their existing dark-mode handlers.
  // Other pages likewise retain their handlers, including their existing storage conventions.
  try{const value=localStorage.getItem('catcam-dark');if(value==='1'||value==='true'){checkbox.checked=true;document.body.classList.add('dark');}}catch(e){}
  if(!onHome){
    // The status endpoint confirms the CatCam web service is reachable; it does not
    // prove the camera stream is active, so do not label this indicator "Live".
    async function updateStatus(){try{const res=await fetch('/api/status',{cache:'no-store'});if(!res.ok) throw new Error('Status unavailable'); const data=await res.json(); camera.textContent=data.camera_live?'● Live':'● Offline';}catch(e){camera.textContent='● Offline';}}
    updateStatus();setInterval(updateStatus,30000);
  }
})();
