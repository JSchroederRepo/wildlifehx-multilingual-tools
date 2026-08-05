function escapeHtml(s){ return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function cap(s){ return s? s.charAt(0).toUpperCase()+s.slice(1):s; }

// Remembers the last eBird trip report URL/ID entered, shared between the
// "eBird Trip Report" and "Trip Report by Date" tabs so switching tabs (or
// coming back later) keeps it pre-filled.
const LAST_TRIP_KEY = 'wildlifehx_last_trip';
function getLastTrip(){ try{ return localStorage.getItem(LAST_TRIP_KEY) || ''; }catch(e){ return ''; } }
function setLastTrip(v){ try{ if(v) localStorage.setItem(LAST_TRIP_KEY, v); }catch(e){} }
/* ====================== contact (click-to-reveal, bot-resistant) ====================== */
(function(){
  // address stored only as char codes — never appears as readable text or a mailto: in the page source
  const _c=[106,117,108,105,97,46,115,99,104,114,111,101,100,101,114,43,119,105,108,100,108,105,102,101,104,120,97,112,112,64,103,109,97,105,108,46,99,111,109];
  const btn=document.getElementById('contact_btn');
  if(!btn) return;
  btn.addEventListener('click', function(){
    const addr=_c.map(c=>String.fromCharCode(c)).join('');
    const wrap=btn.parentElement;
    wrap.innerHTML='<a class="contact_addr" href="mailto:'+encodeURIComponent(addr)+'?subject='+encodeURIComponent('WildlifeHX species tools')+'">'+addr+'</a><button class="copybtn" type="button">copy</button>';
    const cb=wrap.querySelector('.copybtn');
    cb.addEventListener('click', function(){
      try{ navigator.clipboard.writeText(addr); }catch(e){}
      this.textContent='copied';
    });
  });
})();


/* ====================== tool tabs (used on pages with >1 tab) ====================== */
function initTabs(){
  document.querySelectorAll('.tab').forEach(t => {
    t.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      document.getElementById('panel-' + t.dataset.tab).classList.add('active');
    });
  });
}
