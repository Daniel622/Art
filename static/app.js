const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
const api = async (url, opts={}) => {
  const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...opts});
  const data = await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(data.error || '请求失败');
  return data;
};
const post = (url, body={}) => api(url, {method:'POST', body:JSON.stringify(body)});
const del = url => api(url, {method:'DELETE'});
const state = {me:null, config:null, refs:[], tasks:[], history:[], presets:JSON.parse(localStorage.getItem('studio.presets')||'[]')};
const app = $('#app');
const styleNames = {photography:'写实摄影',illustration:'动漫插画',poster:'电影海报',brand:'Logo/品牌视觉',product:'产品摄影',concept:'梦幻艺术',character:'角色设计',advertising:'商业广告'};
const stages = ['接收请求','校验参数','排队','准备素材','生成图像','优化结果','保存作品','完成'];
const ratioList = ['1:1','16:9','9:16','4:3','3:4','3:2','2:3'];

function route(){
  if(location.pathname.startsWith('/admin')) return renderAdmin();
  api('/api/me').then(d=>{state.me=d.authenticated?d.code:null; state.me ? renderStudio() : renderHome();}).catch(renderHome);
}
function renderHome(msg=''){
  app.innerHTML = `<section class="hero page"><div class="hero-copy"><div><div class="brand">Obscura Studio</div></div><div><h1>为私域创作保留一间安静的 AI 影像工作室</h1><p>访问凭证、额度、模型、Provider 和历史作品全部由你掌控。适合内部概念探索、品牌视觉试验、产品图和角色方向验证。</p><form class="login-strip"><input name="code" placeholder="输入访问码 / 邀请码 / 体验码" autocomplete="one-time-code"><button class="btn primary">进入工作台</button><a class="btn ghost" href="/admin">后台</a></form><div class="msg">${msg}</div></div><div class="quota"><span class="pill">私密访问</span><span class="pill">多模型 Provider</span><span class="pill">作品历史</span><span class="pill">额度控制</span></div></div><div class="hero-art"><div class="shot one"></div><div class="shot two"></div><div class="shot three"></div></div></section>`;
  $('form').onsubmit = async e => {e.preventDefault(); try{await post('/api/login',{code:e.target.code.value}); await loadConfig(); renderStudio();}catch(err){renderHome(err.message)}};
}
async function loadConfig(){state.config = await api('/api/config'); const me = await api('/api/me'); state.me = me.code;}
async function renderStudio(){
  await loadConfig(); await loadHistory();
  app.innerHTML = `<div class="shell studio-shell"><aside class="side"><div class="brand">Obscura Studio</div><div class="quota"><span class="pill">${state.me.label||state.me.code}</span><span class="pill">剩余 ${state.me.remaining}/${state.me.total_quota}</span></div><div class="nav"><button id="savePreset">保存配方</button><button id="clearRefs">清空参考图</button><a href="/">首页</a><button id="logout">退出</button></div><p class="small">默认访问码：PRIVATE-STUDIO。生产环境请在后台停用或修改。</p></aside><section class="content studio-content"><div class="topbar studio-topbar"><div><h1>图像生成</h1><div class="small">按风格、质量、清晰度和比例下单生成，模型由后台自动路由。</div></div></div><div class="grid studio-grid"><div>${composerHtml()}</div><div><section class="panel studio-output"><h2>生成任务</h2><div id="tasks"></div></section><section class="panel studio-output" style="margin-top:20px"><h2>作品历史</h2><div class="history" id="history"></div></section></div></div></section></div><div class="modal" id="modal"><img alt="preview"></div>`;
  bindStudio(); drawRefs(); drawTasks(); drawHistory();
}
function composerHtml(){
  const presets = state.presets.map((p,i)=>`<button class="chip" data-preset="${i}">${p.name}</button>`).join('') || '<div class="small">还没有保存的设定</div>';
  const ratios = ratioList.filter(r=>state.config.ratios.includes(r));
  return `<section class="panel gen-panel"><div class="field"><label>参考图 (图生图)</label><div class="ref-wrap"><label class="ref-add"><input id="file" type="file" accept="image/*" multiple><span>＋</span><b>添加</b></label><div class="ref-grid dark-refs" id="refs"></div></div><div class="small">最多 ${state.config.maxReferences} 张，点击缩略图可预览大图。</div></div><div class="field"><label>风格 (Style)</label><div class="style-grid" id="styles">${Object.keys(styleNames).slice(0,8).map((k,i)=>`<button class="style-card ${i===0?'active':''}" data-style="${k}">${styleNames[k]}</button>`).join('')}</div></div><div class="field prompt-field"><label><span>图像提示词 (Prompt)</span><span class="prompt-tools"><button id="inlineSavePreset" type="button">▣ 保存配方</button><button id="myPresets" type="button">▰ 我的配方</button></span></label><textarea id="prompt" maxlength="1600" placeholder="请详细描述您想生成的画面..."></textarea></div><div class="field"><label>输出质量 (Quality) — API 原生参数</label><div class="pill-row" id="qualities"><button class="param-pill" data-quality="low">低 (Low)</button><button class="param-pill active" data-quality="medium">中 (Medium)</button><button class="param-pill" data-quality="high">高 (High)</button><button class="param-pill" data-quality="auto">自动 (Auto)</button></div></div><div class="field"><label>清晰度 (Resolution) — 当前模型支持 4K</label><div class="pill-row" id="resolutions"><button class="param-pill active" data-resolution="1k">标准 1K</button><button class="param-pill" data-resolution="2k">2K 高清</button><button class="param-pill" data-resolution="4k">4K 超清</button></div></div><div class="field"><label id="ratioLabel">画面比例 (Aspect Ratio) 当前: 1024×1024</label><div class="ratio-grid compact" id="ratios">${ratios.map((r,i)=>`<button class="ratio ${i===0?'active':''}" data-ratio="${r}"><span class="ratio-icon ratio-${r.replace(':','-')}"></span><span>${r}</span></button>`).join('')}</div></div><div class="field"><label>反向提示词 (Negative Prompt)</label><input id="negative" placeholder="排除的元素..."></div><button class="btn order-btn" id="generate" type="button">🪄 下单</button><div class="field saved-presets"><label>我的配方</label><div class="seg">${presets}</div></div></section>`;
}
function bindStudio(){
  $('#logout').onclick = async()=>{await post('/api/logout'); state.me=null; renderHome();};
  $('#clearRefs').onclick = ()=>{state.refs=[]; drawRefs();};
  $('#file').onchange = async e => {for(const f of e.target.files){if(state.refs.length>=state.config.maxReferences) break; state.refs.push(await fileData(f));} e.target.value=''; drawRefs();};
  $$('#styles .style-card').forEach(b=>b.onclick=()=>activate('#styles .style-card', b));
  $$('#ratios .ratio').forEach(b=>b.onclick=()=>activate('#ratios .ratio', b));
  $$('#qualities .param-pill').forEach(b=>b.onclick=()=>activate('#qualities .param-pill', b));
  $$('#resolutions .param-pill').forEach(b=>b.onclick=()=>activate('#resolutions .param-pill', b));
  $('[data-preset]') && $$('[data-preset]').forEach(b=>b.onclick=()=>applyPreset(state.presets[+b.dataset.preset]));
  $('#inlineSavePreset').onclick = ()=>savePreset();
  $('#myPresets').onclick = ()=>$('.saved-presets').scrollIntoView({behavior:'smooth', block:'center'});
  $('#savePreset').onclick = ()=>savePreset();
  $('#generate').onclick = ()=>generate();
  $('#modal').onclick = ()=>$('#modal').classList.remove('open');
  updateRatioLabel();
  $$('#ratios .ratio,#resolutions .param-pill').forEach(b=>b.addEventListener('click', updateRatioLabel));
}
function activate(sel,b){$$(sel).forEach(x=>x.classList.remove('active')); b.classList.add('active');}
function currentParams(){const ratio=$('#ratios .active').dataset.ratio; const resolution=$('#resolutions .active').dataset.resolution; return {prompt:$('#prompt').value.trim(),negative_prompt:$('#negative').value.trim(),style:$('#styles .active').dataset.style,ratio,quality:$('#qualities .active').dataset.quality,resolution,size:sizeFor(ratio,resolution),references:state.refs.map(r=>r.data)}}
function sizeFor(ratio,resolution){const map={ '1k':{'1:1':'1024x1024','16:9':'1536x864','9:16':'864x1536','4:3':'1344x1008','3:4':'1008x1344','3:2':'1536x1024','2:3':'1024x1536'}, '2k':{'1:1':'2048x2048','16:9':'2048x1152','9:16':'1152x2048','4:3':'2048x1536','3:4':'1536x2048','3:2':'2048x1360','2:3':'1360x2048'}, '4k':{'1:1':'2880x2880','16:9':'3840x2160','9:16':'2160x3840','4:3':'3840x2880','3:4':'2880x3840','3:2':'3840x2560','2:3':'2560x3840'} }; return map[resolution]?.[ratio] || '1024x1024'}
function updateRatioLabel(){const label=$('#ratioLabel'); if(label) label.textContent=`画面比例 (Aspect Ratio) 当前: ${sizeFor($('#ratios .active').dataset.ratio, $('#resolutions .active').dataset.resolution).replace('x','×')}`}
function fileData(file){return new Promise((ok,fail)=>{const r=new FileReader(); r.onload=()=>ok({name:file.name,data:r.result}); r.onerror=fail; r.readAsDataURL(file);});}
function drawRefs(){const box=$('#refs'); if(!box)return; box.innerHTML=state.refs.map((r,i)=>`<div class="ref"><img src="${r.data}" alt="${escapeHtml(r.name||'reference')}" data-preview="${i}"><button data-rm="${i}" aria-label="删除参考图">×</button></div>`).join(''); $$('[data-rm]').forEach(b=>b.onclick=e=>{e.stopPropagation(); const removed=state.refs.splice(+b.dataset.rm,1)[0]; const modal=$('#modal'); if(modal?.classList.contains('open') && $('#modal img').src===removed?.data){modal.classList.remove('open'); $('#modal img').removeAttribute('src')} drawRefs();}); $$('[data-preview]').forEach(img=>img.onclick=()=>preview(img.src));}
function preview(src){$('#modal img').src=src; $('#modal').classList.add('open');}
function savePreset(params=currentParams(), name=prompt('设定名称','我的创作设定')){if(!name)return; state.presets.unshift({name,...params,references:[]}); state.presets=state.presets.slice(0,24); localStorage.setItem('studio.presets',JSON.stringify(state.presets)); renderStudio();}
function applyPreset(p){$('#prompt').value=p.prompt||''; $('#negative').value=p.negative_prompt||''; $(`[data-quality="${p.quality||'medium'}"]`)?.click(); $(`[data-resolution="${p.resolution||'1k'}"]`)?.click(); $(`[data-style="${p.style}"]`)?.click(); $(`[data-ratio="${p.ratio}"]`)?.click(); updateRatioLabel();}
async function generate(){
  const params=currentParams(); if(!params.prompt){alert('请输入图像提示词。');return}
  const task={id:Date.now(),params,stage:0,progress:8,status:'running',started:Date.now()}; state.tasks.unshift(task); drawTasks();
  const timer=setInterval(()=>{if(task.status!=='running')return clearInterval(timer); task.stage=Math.min(stages.length-2,task.stage+1); task.progress=Math.min(88,task.progress+Math.random()*14); drawTasks();},900);
  try{const res=await post('/api/generate',params); task.status='success'; task.progress=100; task.stage=stages.length-1; task.result=res; await loadConfig(); await loadHistory();}
  catch(err){task.status='failed'; task.error=err.message; task.progress=100;}
  drawTasks(); drawHistory();
}
function drawTasks(){const box=$('#tasks'); if(!box)return; box.innerHTML=state.tasks.map(t=>`<div class="card task"><div class="task-head"><b>${t.status==='success'?'完成':t.status==='failed'?'失败':stages[t.stage]}</b><span class="small">${Math.round((Date.now()-t.started)/1000)}s</span></div><div class="bar"><span style="width:${t.progress}%"></span></div><div class="small">${t.result?.model || '后台默认模型'} · ${styleNames[t.params.style]} · ${t.params.ratio} · 参考图 ${t.params.references.length}</div><p>${escapeHtml(t.params.prompt).slice(0,160)}</p>${t.error?`<p class="error">${escapeHtml(t.error)}</p>`:''}${t.result?`<img class="result" src="${t.result.image_url}"><div class="actions"><a class="btn light" download href="${t.result.image_url}">下载</a><button class="btn light" data-reuse-task="${t.id}">复用参数</button><button class="btn light" data-save-task="${t.id}">保存配置</button></div>`:''}</div>`).join('') || '<div class="small">生成后会在这里显示阶段、进度、耗时和结果。</div>';
  $$('[data-reuse-task]').forEach(b=>b.onclick=()=>applyPreset(state.tasks.find(t=>t.id==b.dataset.reuseTask).params));
  $$('[data-save-task]').forEach(b=>b.onclick=()=>savePreset(state.tasks.find(t=>t.id==b.dataset.saveTask).params));
}
async function loadHistory(){const h=await api('/api/history').catch(()=>({items:[]})); state.history=h.items||[];}
function drawHistory(){const box=$('#history'); if(!box)return; box.innerHTML=state.history.map(x=>`<div class="card"><img src="${x.image_url||''}" onerror="this.style.display='none'" data-open="${x.image_url||''}"><b>${x.status}</b><div class="small">${x.model||''} · ${x.ratio||''}</div><p class="small">${escapeHtml(x.original_prompt||'').slice(0,90)}</p><div class="actions"><button class="btn light" data-reuse-gen="${x.id}">复用</button>${x.image_url?`<a class="btn light" href="${x.image_url}" download>下载</a>`:''}</div></div>`).join('') || '<div class="small">暂无历史作品。</div>';
  $$('[data-open]').forEach(i=>i.onclick=()=>i.dataset.open&&preview(i.dataset.open));
  $$('[data-reuse-gen]').forEach(b=>b.onclick=()=>{const g=state.history.find(x=>x.id==b.dataset.reuseGen); applyPreset(JSON.parse(g.params_json||'{}'));});
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));}

async function renderAdmin(){
  const ok = await api('/api/admin/me').then(()=>true).catch(()=>false);
  if(!ok) return renderAdminLogin();
  const [stats,codes,providers,gens]=await Promise.all([api('/api/admin/stats'),api('/api/admin/codes'),api('/api/admin/providers'),api('/api/admin/generations')]);
  app.innerHTML=`<div class="shell"><aside class="side"><div class="brand">后台管理</div><div class="nav"><a href="/">返回首页</a><button id="adminLogout">退出后台</button></div></aside><section class="content"><div class="topbar"><h1>运营控制台</h1><button class="btn primary" onclick="location.reload()">刷新</button></div><div class="statgrid">${Object.entries({访问凭证:stats.codes,成功生成:stats.success,今日生成:stats.today,Provider:stats.providers,失败:stats.failed}).map(([k,v])=>`<div class="panel stat"><div class="small">${k}</div><b>${v}</b></div>`).join('')}</div><section class="panel" style="margin-top:20px"><h2>访问凭证</h2>${codeForm()}<div class="table">${codes.items.map(codeRow).join('')}</div></section><section class="panel" style="margin-top:20px"><h2>API Provider 与模型</h2>${providerForm()}<div class="table">${providers.items.map(providerRow).join('')}</div></section><section class="panel" style="margin-top:20px"><h2>生成记录</h2><div class="table">${gens.items.map(genRow).join('')}</div></section></section></div>`;
  bindAdmin(codes.items,providers.items);
}
function renderAdminLogin(msg=''){app.innerHTML=`<section class="hero page"><div class="hero-copy"><div class="brand">Obscura Studio Admin</div><div><h1>管理访问、模型与生成记录</h1><p>默认管理员：admin / ChangeMe123!。首次部署后请立刻修改环境变量或数据库中的密码。</p><form class="login-strip"><input name="username" placeholder="管理员账号"><input name="password" type="password" placeholder="密码"><button class="btn primary">登录</button><a class="btn ghost" href="/">返回首页</a></form><div class="msg">${msg}</div></div></div><div class="hero-art"><div class="shot one"></div><div class="shot three"></div></div></section>`; $('form').onsubmit=async e=>{e.preventDefault();try{await post('/api/admin/login',{username:e.target.username.value,password:e.target.password.value}); renderAdmin();}catch(err){renderAdminLogin(err.message)}}}
function codeForm(c={active:true,total_quota:20,used_quota:0}){return `<form class="admin-form" id="codeForm"><input type="hidden" name="id" value="${c.id||''}"><div class="field"><label>凭证</label><input name="code" value="${c.code||''}" required></div><div class="field"><label>标签</label><input name="label" value="${c.label||''}"></div><div class="field"><label>总额度</label><input name="total_quota" type="number" value="${c.total_quota}"></div><div class="field"><label>已用</label><input name="used_quota" type="number" value="${c.used_quota}"></div><div class="field"><label>备注</label><input name="note" value="${c.note||''}"></div><label><input name="active" type="checkbox" ${c.active?'checked':''}> 启用</label><button class="btn primary">保存凭证</button></form>`}
function normalizeModels(models){return (models||[]).map(m=>typeof m==='string'?{id:m,name:m,enabled:false,supports_reference:false}:{id:(m.id||m.name||'').trim(),name:(m.name||m.id||'').trim(),enabled:!!m.enabled,supports_reference:!!m.supports_reference}).filter(m=>m.id).filter((m,i,arr)=>arr.findIndex(x=>x.id===m.id)===i)}
function modelToolbarHtml(models){const list=normalizeModels(models);const enabled=list.filter(m=>m.enabled).length;const refs=list.filter(m=>m.supports_reference).length;return `<div class="model-toolbar"><span class="pill">共 ${list.length} 个模型</span><span class="pill">启用 ${enabled}</span><span class="pill">参考图 ${refs}</span></div>`}
function modelFetchState(models, existingModels, defaultModel, providerSupportsReference){
  const saved = new Map(normalizeModels(existingModels).map(model=>[model.id, model]));
  const merged = normalizeModels(models).map(model=>{
    const current = saved.get(model.id);
    return current ? {...model, enabled:current.enabled, supports_reference:current.supports_reference, name:current.name||model.name} : {...model, enabled:false, supports_reference:providerSupportsReference && model.supports_reference};
  });
  return {models:merged, defaultModel:merged.some(model=>model.id===defaultModel && model.enabled)?defaultModel:(merged.find(model=>model.enabled)?.id||'')};
}
function modelFetchModalHtml(state){
  const list = state.models;
  return `<div class="modal model-fetch-modal open" id="modelFetchModal"><div class="modal-card"><div class="modal-head"><div><h3>拉取模型</h3><p class="small">勾选需要启用的模型，再决定哪些模型支持参考图。</p></div><button class="btn light" type="button" id="closeModelFetchModal">关闭</button></div><div class="modal-body">${!list.length?'<div class="model-empty">没有拉取到任何模型。</div>':`<div class="modal-actions inline"><button class="btn light" type="button" id="selectAllFetchedModels">全选</button><button class="btn light" type="button" id="clearFetchedModels">清空</button></div><div class="fetched-model-list">${list.map(model=>`<div class="fetched-model-item" data-fetched-model-row data-model-id="${escapeHtml(model.id)}"><div class="model-main"><div class="model-title"><b>${escapeHtml(model.name)}</b><span>${escapeHtml(model.id)}</span></div><div class="model-badges">${model.enabled?'<span class="badge ok">已选择</span>':''}${state.defaultModel===model.id?'<span class="badge accent">当前默认</span>':''}${model.supports_reference?'<span class="badge warm">支持参考图</span>':''}</div></div><div class="model-controls"><label class="model-toggle"><input type="checkbox" data-fetched-enabled ${model.enabled?'checked':''}> 启用</label><label class="model-toggle"><input type="radio" name="fetched_default_model" value="${escapeHtml(model.id)}" ${state.defaultModel===model.id?'checked':''} ${model.enabled?'':'disabled'}> 默认调用</label><label class="model-toggle"><input type="checkbox" data-fetched-ref ${model.supports_reference?'checked':''}> 参考图</label></div></div>`).join('')}</div>`}</div><div class="modal-actions"><button class="btn light" type="button" id="cancelModelFetchModal">取消</button><button class="btn primary" type="button" id="applyFetchedModels">应用选择</button></div></div></div>`;
}
function openModelFetchModal(models, existingModels, defaultModel, providerSupportsReference){
  const form = $('#providerForm');
  if(!form) return;
  const existing = $('#modelFetchModal');
  if(existing) existing.remove();
  const state = modelFetchState(models, existingModels, defaultModel, providerSupportsReference);
  form.insertAdjacentHTML('beforeend', modelFetchModalHtml(state));
  bindModelFetchModal();
}
function bindModelFetchModal(){
  const modal = $('#modelFetchModal');
  if(!modal) return;
  const close = ()=>modal.remove();
  const sync = ()=>{
    const rows = $$('[data-fetched-model-row]', modal);
    rows.forEach(row=>{
      const enabled = $('[data-fetched-enabled]', row).checked;
      const radio = $('[name="fetched_default_model"]', row);
      radio.disabled = !enabled;
      if(!enabled) radio.checked = false;
    });
    const chosen = $('[name="fetched_default_model"]:checked', modal);
    if(!chosen){
      const fallbackRow = rows.find(row=> $('[data-fetched-enabled]', row).checked);
      const fallbackRadio = fallbackRow && $('[name="fetched_default_model"]', fallbackRow);
      if(fallbackRadio) fallbackRadio.checked = true;
    }
  };
  $('#closeModelFetchModal').onclick = close;
  $('#cancelModelFetchModal').onclick = close;
  $('#selectAllFetchedModels').onclick = ()=>{$$('[data-fetched-enabled]', modal).forEach(input=>input.checked=true); sync();};
  $('#clearFetchedModels').onclick = ()=>{$$('[data-fetched-enabled]', modal).forEach(input=>input.checked=false); sync();};
  $$('[data-fetched-enabled]', modal).forEach(input=>input.onchange=sync);
  $$('[name="fetched_default_model"]', modal).forEach(input=>input.onchange=e=>{const row=e.target.closest('[data-fetched-model-row]'); if(row){const enabled=$('[data-fetched-enabled]', row); if(enabled && !enabled.checked) enabled.checked=true;} sync();});
  $('#applyFetchedModels').onclick = ()=>{
    const rows = $$('[data-fetched-model-row]', modal);
    const selected = rows.map(row=>({id:row.dataset.modelId,name:$('.model-title b', row).textContent,enabled:$('[data-fetched-enabled]', row).checked,supports_reference:$('[data-fetched-ref]', row).checked}));
    const current = normalizeModels(JSON.parse($('[name=models]', $('#providerForm')).value||'[]'));
    const keepExisting = current.filter(model=>!selected.some(next=>next.id===model.id));
    const merged = normalizeModels([...selected, ...keepExisting]);
    const chosen = $('[name="fetched_default_model"]:checked', modal);
    const defaultModel = chosen?.value && merged.some(model=>model.id===chosen.value && model.enabled) ? chosen.value : (merged.find(model=>model.enabled)?.id || '');
    setModelPicker(merged, defaultModel);
    close();
  };
  modal.onclick = e=>{if(e.target===modal) close();};
  sync();
}
function modelPickerHtml(models, defaultModel=''){
  const list = normalizeModels(models);
  if(!list.length) return '<div class="model-empty">还没有模型。输入 Base URL 和 API Key 后点击“拉取模型”，或手动添加模型 ID。</div>';
  return `${modelToolbarHtml(list)}<div class="model-list">${list.map(m=>`<div class="model-item ${m.enabled?'is-enabled':'is-disabled'}" data-model-row data-model-id="${escapeHtml(m.id)}" data-model-name="${escapeHtml(m.name)}"><div class="model-main"><div class="model-title"><b>${escapeHtml(m.name)}</b><span>${escapeHtml(m.id)}</span></div><div class="model-badges">${m.enabled?'<span class="badge ok">已启用</span>':'<span class="badge muted">未启用</span>'}${defaultModel===m.id?'<span class="badge accent">默认调用</span>':''}${m.supports_reference?'<span class="badge warm">支持参考图</span>':''}</div></div><div class="model-controls"><label class="model-toggle"><input type="checkbox" data-model-enabled ${m.enabled?'checked':''}> 启用</label><label class="model-toggle"><input type="radio" name="default_model_choice" value="${escapeHtml(m.id)}" ${defaultModel===m.id?'checked':''} ${m.enabled?'':'disabled'}> 默认调用</label><label class="model-toggle"><input type="checkbox" data-model-ref ${m.supports_reference?'checked':''}> 参考图</label></div></div>`).join('')}</div>`;
}
function providerForm(p={active:true,is_default:false,supports_reference:true,priority:100,models:[{id:'mock-vision-xl',name:'Vision XL Mock',enabled:true,supports_reference:true}],default_model:'mock-vision-xl'}){
  const models = normalizeModels(p.models||[]);
  return `<form class="admin-provider-form" id="providerForm"><input type="hidden" name="id" value="${p.id||''}"><input type="hidden" name="models" value="${escapeHtml(JSON.stringify(models))}"><input type="hidden" name="default_model" value="${escapeHtml(p.default_model||'')}"><section class="panel provider-section"><h3>连接信息</h3><div class="admin-form provider-top"><div class="field"><label>Provider 名称</label><input name="name" value="${p.name||''}" required placeholder="例如 OpenAI Compatible"></div><div class="field"><label>API URL / Base URL</label><input name="base_url" value="${p.base_url||'mock://local'}" required placeholder="https://api.example.com/v1"></div><div class="field"><label>API Key</label><input name="api_key" value="${p.api_key||''}" placeholder="留空则保持原值"></div><div class="field"><label>优先级</label><input name="priority" type="number" value="${p.priority}"><div class="small helper">数字越小优先级越高。默认 Provider 会排在最前。</div></div></div></section><section class="panel provider-section"><h3>调用路由</h3><div class="provider-flags"><label><input name="active" type="checkbox" ${p.active?'checked':''}> 启用 Provider</label><label><input name="is_default" type="checkbox" ${p.is_default?'checked':''}> 默认 Provider</label><label><input name="supports_reference" type="checkbox" ${p.supports_reference?'checked':''}> Provider 支持参考图</label></div><div class="small helper">默认 Provider 会优先参与自动路由；如果某模型支持参考图，生成参考图任务时会优先选择对应能力的 Provider。</div></section><div class="provider-actions"><button class="btn light" type="button" id="fetchModels">拉取模型</button><button class="btn light" type="button" id="addModel">手动添加模型</button><button class="btn light" type="button" id="testProvider">测试</button><button class="btn primary" type="submit">保存 Provider</button></div><section class="panel provider-section"><div class="field model-field"><label>模型列表</label><div class="small helper">先勾选要启用的模型，再选择一个默认调用模型。未启用模型不能作为默认调用。</div><div class="model-picker" id="modelPicker">${modelPickerHtml(models,p.default_model||'')}</div></div></section></form>`
}
function codeRow(c){return `<div class="row"><b>${escapeHtml(c.code)}</b><span>${escapeHtml(c.label||'')}</span><span>${c.used_quota}/${c.total_quota}</span><span>${c.active?'启用':'停用'}</span><span class="actions"><button class="btn light" data-edit-code="${c.id}">编辑</button><button class="btn light" data-del-code="${c.id}">删除</button></span></div>`}
function providerRow(p){return `<div class="row provider" title="归档后会停用并从列表隐藏，历史生成记录仍保留"><b>${escapeHtml(p.name)}</b><span>${escapeHtml(p.base_url)}</span><span>${p.call_count}/${p.fail_count}</span><span>${p.active?'启用':'停用'}</span><span class="actions"><button class="btn light" data-edit-provider="${p.id}">编辑</button><button class="btn light danger" data-del-provider="${p.id}">删除/归档</button></span></div>`}
function genRow(g){return `<div class="row gen"><span>${escapeHtml(g.access_code||'')}</span><span>${escapeHtml(g.model||'')}</span><span>${escapeHtml(g.provider_name||'')}</span><b class="${g.status==='failed'?'error':'ok'}">${g.status}</b><span>${escapeHtml(g.original_prompt||'').slice(0,90)}</span><span>${g.image_url?`<a href="${g.image_url}" target="_blank"><img class="preview-thumb" src="${g.image_url}"></a>`:''}</span></div>`}
function bindModelPicker(){
  const form = $('#providerForm');
  if(!form) return;
  const sync = (rerender=true)=>{
    const rows = $$('[data-model-row]', form);
    const models = rows.map(row=>({id:row.dataset.modelId,name:row.dataset.modelName,enabled:$('[data-model-enabled]',row).checked,supports_reference:$('[data-model-ref]',row).checked}));
    const radios = $$('[name=default_model_choice]', form);
    radios.forEach(radio=>{
      const row = radio.closest('[data-model-row]');
      const enabled = !!row && $('[data-model-enabled]', row).checked;
      radio.disabled = !enabled;
      if(!enabled) radio.checked = false;
    });
    const chosen = $('[name=default_model_choice]:checked', form);
    const firstEnabled = models.find(m=>m.enabled);
    const defaultModel = chosen?.value || firstEnabled?.id || '';
    if(defaultModel && !chosen){
      const fallback = $(`[name="default_model_choice"][value="${CSS.escape(defaultModel)}"]`, form);
      if(fallback) fallback.checked = true;
    }
    $('[name=models]', form).value = JSON.stringify(models);
    $('[name=default_model]', form).value = defaultModel;
    if(rerender){
      $('#modelPicker').innerHTML = modelPickerHtml(models, defaultModel);
      bindModelPicker();
    }
  };
  $$('#modelPicker [data-model-enabled]', form).forEach(input=>input.onchange=()=>sync());
  $$('#modelPicker [data-model-ref]', form).forEach(input=>input.onchange=()=>sync());
  $$('#modelPicker [name="default_model_choice"]', form).forEach(input=>input.onchange=e=>{const row=e.target.closest('[data-model-row]'); if(row){const enabled=$('[data-model-enabled]',row); if(enabled && !enabled.checked) enabled.checked=true;} sync();});
  sync(false);
}
function mergeFetchedModels(existing,incoming){
  const current = new Map(normalizeModels(existing).map(model=>[model.id, model]));
  const next = normalizeModels(incoming).map(model=>{
    const saved = current.get(model.id);
    return saved ? {...model, enabled:saved.enabled, supports_reference:saved.supports_reference, name:saved.name||model.name} : model;
  });
  return next.concat(normalizeModels(existing).filter(model=>!next.some(candidate=>candidate.id===model.id)));
}
function setModelPicker(models, defaultModel=''){
  $('#modelPicker').innerHTML = modelPickerHtml(models, defaultModel);
  const form = $('#providerForm');
  if(form){
    $('[name=models]', form).value = JSON.stringify(normalizeModels(models));
    $('[name=default_model]', form).value = defaultModel;
  }
  bindModelPicker();
}
function bindAdmin(codes,providers){
  $('#adminLogout').onclick=async()=>{await post('/api/admin/logout'); renderAdminLogin();};
  $('#codeForm').onsubmit=async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.target));f.active=e.target.active.checked;try{await post('/api/admin/codes',f);renderAdmin()}catch(err){alert(err.message)}};
  bindModelPicker();
  $('#providerForm').onsubmit=async e=>{
    e.preventDefault();
    const form=e.target;
    const f=Object.fromEntries(new FormData(form));
    try{
      f.models=JSON.parse(f.models);
      f.active=form.active.checked;
      f.is_default=form.is_default.checked;
      f.supports_reference=form.supports_reference.checked;
      await post('/api/admin/providers',f);
      renderAdmin();
    }catch(err){alert(err.message)}
  };
  $$('[data-edit-code]').forEach(b=>b.onclick=()=>{$('#codeForm').outerHTML=codeForm(codes.find(x=>x.id==b.dataset.editCode)); bindAdmin(codes,providers)});
  $$('[data-del-code]').forEach(b=>b.onclick=async()=>{if(confirm('删除该凭证？')){await del('/api/admin/codes/'+b.dataset.delCode);renderAdmin()}});
  $$('[data-edit-provider]').forEach(b=>b.onclick=()=>{$('#providerForm').outerHTML=providerForm(providers.find(x=>x.id==b.dataset.editProvider)); bindAdmin(codes,providers)});
  $$('[data-del-provider]').forEach(b=>b.onclick=async()=>{
    if(confirm('归档该 Provider？归档后会停用并从列表隐藏，历史记录仍保留。')){
      await del('/api/admin/providers/'+b.dataset.delProvider);
      renderAdmin();
    }
  });
  $('#testProvider').onclick=async()=>{
    const f=Object.fromEntries(new FormData($('#providerForm')));
    const r=await post('/api/admin/providers/test',f).catch(e=>({message:e.message}));
    alert(r.message||'完成');
  };
  $('#fetchModels').onclick=async()=>{
    const form=$('#providerForm');
    const button=$('#fetchModels');
    const f=Object.fromEntries(new FormData(form));
    const originalText=button.textContent;
    button.disabled=true;
    button.textContent='拉取中...';
    try{
      const r=await post('/api/admin/providers/models',f);
      const existing=JSON.parse($('[name=models]',form).value||'[]');
      const currentDefault=$('[name=default_model]',form).value;
      openModelFetchModal(r.models||[], existing, currentDefault, form.supports_reference.checked);
    }catch(err){
      alert(err.message);
    }finally{
      button.disabled=false;
      button.textContent=originalText;
    }
  };
  $('#addModel').onclick=()=>{
    const form=$('#providerForm');
    const raw=prompt('输入模型 ID，例如 gpt-image-1');
    const id=(raw||'').trim();
    if(!id)return;
    const current=normalizeModels(JSON.parse($('[name=models]',form).value||'[]'));
    if(current.some(m=>m.id===id)) return alert('该模型已在列表中。');
    const next=[...current,{id,name:id,enabled:true,supports_reference:form.supports_reference.checked}];
    const currentDefault=$('[name=default_model]',form).value;
    setModelPicker(next, currentDefault || id);
  };
}
route();
