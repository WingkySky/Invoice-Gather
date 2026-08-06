/* ======================================================== 票归集 · 公共脚本（所有页面共享）
 * 放置跨页面复用的基础能力：API 封装、格式化、后台任务轮询、顶部导航。
 * 各独立页面（invoices.html / companies.html / index.html）先加载本文件，再加载自己的业务脚本。
 */
const API = (p, opt) => fetch(p, opt).then(r => r.json());

function escapeHtml(s){ return (s||'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function fmtMoney(v){
  const n = parseFloat(v);
  if (isNaN(n)) return v || '';
  return '¥' + n.toLocaleString('zh-CN', {minimumFractionDigits:2, maximumFractionDigits:2});
}

// 日期格式化：把后端 ISO 字符串（含 T00:00:00）或日期对象截成 YYYY-MM-DD
function fmtDate(v){
  if(!v) return '';
  const s = String(v);
  const m = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
  if(m){ return m[1] + '-' + m[2].padStart(2,'0') + '-' + m[3].padStart(2,'0'); }
  return s;
}

function stripEmpty(o){ const r={}; for(const k in o) if(o[k]!=='' && o[k]!=null) r[k]=o[k]; return r; }

// 列表「发票文件」单元格：根据 pdf_path 后缀决定展示与行为
function pdfCell(r){
  const p = r.pdf_path || '';
  if (!p) return '<span style="color:#bbb">仅标题</span>';
  const isOfd = p.toLowerCase().endsWith('.ofd');
  const label = isOfd ? '下载OFD' : '查看';
  return `<a href="/api/pdf/${r.id}" target="_blank"${isOfd ? ' download' : ''}>${label}</a>`;
}

// 归属状态徽章：已归类=绿、未归类=红、歧义=橙；悬停显示结构化原因（用户+开发者可见）
function attrBadge(r){
  const s = r.attribution_status || 'unclassified';
  const reason = r.attribution_reason || '';
  const map = { classified:['已归类','on'], unclassified:['未归类','off'], ambiguous:['歧义','warn'] };
  const [label, cls] = map[s] || [s, 'off'];
  const tip = reason ? ' title="'+escapeHtml(reason)+'"' : '';
  return `<span class="badge ${cls}"${tip}>${label}</span>`;
}

/* ---------- 后台任务进度（删除/上传/导出/回填 通用） ---------- */
function setExp(t){ const e=document.getElementById('expMsg'); if(e) e.textContent=t; }
function showJobBar(){ const b=document.getElementById('jobBar'); if(b) b.style.display='block'; updateJobBar({done:0,total:1}); }
function hideJobBar(){ const b=document.getElementById('jobBar'); if(b) b.style.display='none'; }
function updateJobBar(j){
  const f=document.getElementById('jobBarFill'); if(!f) return;
  const t=+j.total||0, d=+j.done||0;
  f.style.width = t>0 ? Math.min(100, Math.round(d/t*100))+'%' : '0%';
}
// 轮询后台任务：onProgress(job) 每次收到状态调用；onDone(job) 任务结束（含失败）调用。最多约 14 分钟。
async function pollJob(jid, onProgress, onDone){
  for(let k=0; k<2400; k++){
    let j;
    try { j = await API('/api/jobs/'+jid); }
    catch(e){ await new Promise(r=>setTimeout(r,400)); continue; }
    if(j.error){ j.running=false; if(onProgress) onProgress(j); if(onDone) onDone(j); return; }
    if(onProgress) onProgress(j);
    if(!j.running){ if(onDone) onDone(j); return; }
    await new Promise(r=>setTimeout(r,350));
  }
}

/* ---------- 顶部导航（跨页面复用） ----------
 * active: 'invoices' | 'companies' | 'console'
 * 发票台账 / 公司管理 为独立页面；邮箱账号、抓取、模板匹配统一收进「操作台」(index.html)。
 * 避免同一组功能在顶部导航和页面内子 tab 重复出现。
 */
function renderNav(active){
  const nav = document.getElementById('topnav');
  if(!nav) return;
  const items = [
    {k:'invoices', label:'发票台账', href:'invoices.html'},
    {k:'companies', label:'公司管理', href:'companies.html'},
    {k:'console',  label:'操作台',   href:'index.html'},
  ];
  nav.innerHTML = items.map(it=>
    `<a class="nav-link${it.k===active?' active':''}" href="${it.href}">${it.label}</a>`
  ).join('');
}

/* ---------- 缓存失效（写成功后调用） ---------- */
// 清本地 CacheStore 指定命名空间（或命名空间列表），并向本 tab + 其他 tab 广播失效。
function invalidateCache(ns){
  if(!window.CacheStore) return;
  var list = Array.isArray(ns) ? ns : [ns];
  list.forEach(function(n){ CacheStore.purge(n); });
  if(list.length) CacheStore.broadcast(list[0], null);
}

// 写操作薄封装：成功 → 按命名空间失效缓存 + 轻提示"已更新"。
// invalidateNs: 字符串或数组（见缓存命名空间 NS）。保留现有 API() 调用习惯。
async function postWithInvalidate(url, body, invalidateNs){
  const nsList = invalidateNs ? (Array.isArray(invalidateNs) ? invalidateNs : [invalidateNs]) : [];
  const r = await API(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
  if(r && r.ok){
    invalidateCache(nsList);
    toast('已更新');
  }
  return r;
}

// P1·E SPA 哈希导航占位（P0 不启用，保持兼容保留）。
function renderNavSpa(active){ /* TODO(P1): 哈希链接导航 + 无整页重载 */ }

/* ---------- 顶部细进度条 / "更新中"角标 / 陈旧标注 / 轻提示 ---------- */
function showTopProgress(){ const e=document.getElementById('topProgress'); if(e) e.classList.add('active'); }
function hideTopProgress(){ const e=document.getElementById('topProgress'); if(e) e.classList.remove('active'); }
function showUpdating(){
  const e=document.getElementById('updatingBadge'); if(e) e.hidden=false;
  showTopProgress();
}
function hideUpdating(){
  const e=document.getElementById('updatingBadge'); if(e) e.hidden=true;
  hideTopProgress();
}
function showStale(ts){
  const e=document.getElementById('staleBadge'); if(!e) return;
  const mins = Math.max(1, Math.round((Date.now() - (ts||Date.now()))/60000));
  e.textContent = '显示的是 '+mins+' 分钟前数据';
  e.hidden = false;
}
function hideStale(){ const e=document.getElementById('staleBadge'); if(e) e.hidden=true; }

// 轻提示 toast（写操作成功后的非阻塞反馈）。
function toast(msg){
  let t = document.getElementById('__toast');
  if(!t){
    t = document.createElement('div'); t.id='__toast'; t.className='toast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._tm);
  t._tm = setTimeout(()=>t.classList.remove('show'), 1800);
}
