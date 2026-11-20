import {jobs,retests} from '../api/entities.js';
import {downloadVoucher} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';

const canWrite=()=>session.user.role==='admin'||session.user.role==='analyst';
const isAdmin=()=>session.user.role==='admin';

export async function retestPage(originId){
 const [allJobs,batches,vouchers]=await Promise.all([jobs.list(),retests.batches(),retests.vouchers()]);
 workspace.jobs=allJobs;
 const approved=allJobs.filter(j=>j.approved&&j.status==='completed');
 const preselect=originId?Number(originId):(approved[0]?.id??'');
 return heading('06 / INDEPENDENT RE-TEST','独立复测与签发','换一张观察日表复测已批准结论：沿用原权重，只对照两队加权差值方向；按日/队/区域辨认，与原分析撞批的日表不能参评。','<button class="button" id="refresh-retests">刷新复测台 ↻</button>')
 +'<div class="report-grid"><section class="panel"><div class="section-title"><h2>① 选择已获批分析</h2><span>'+approved.length+' 个可选</span></div>'
 +(approved.length?'<label>原分析（权重沿用，不可改）<select id="retest-origin">'+approved.map(j=>'<option value="'+j.id+'" '+(j.id===preselect?'selected':'')+'>'+esc(j.name)+'</option>').join('')+'</select></label>':'<p class="empty">尚无已批准分析，先到结果复核页批准。</p>')
 +'<div class="section-title" style="margin-top:24px"><h2>② 接入复测日表</h2><span>'+batches.length+' 批</span></div>'
 +'<form id="batch-form"><label>日表批次名称<input name="name" required minlength="2" placeholder="例如：11 月独立复测日表"></label><label>上传 CSV 或 JSON<input type="file" id="retest-file" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="5" placeholder="粘贴 JSON 数组，或选择上方文件" required></textarea></label><button type="submit" class="primary" '+(canWrite()?'':'disabled')+'>校验并接入复测日表</button><p class="hint">与正式分析同一套服务端校验。改几个数重新上传不会通过重叠辨认：与原分析同 日/队/区域 的批次直接拒评。</p></form>'
 +'<div class="batch-list" style="margin-top:18px">'+batches.map(b=>'<div class="delivery"><div><strong>'+esc(b.name)+'</strong><p>'+b.rows+' 行 · '+(b.occupied?'已被凭证 V'+fmt(b.occupied_by)+' 占用':'未占用')+'</p><small>SHA256 '+esc(b.checksum.slice(0,18))+'…</small></div><label class="radio-pick"><input type="radio" name="pick-batch" value="'+b.id+'" '+(b.occupied?'disabled':'')+'>选用</label></div>').join('')+'</div>'
 +'</section>'
 +'<section><div class="section-title"><h2>③ 重叠试算与签发</h2><span>试算不占用日表</span></div>'
 +'<div class="method-sheet compact" id="trial-box"><p class="hint">选择左侧未占用的复测日表后点击试算。重叠候选可各自试算对比；签发时同一原分析的复测日表只用一次。</p></div>'
 +'<div style="display:flex;gap:12px;margin:16px 0"><button class="button" id="run-trial" '+(canWrite()&&approved.length?'':'disabled')+'>试算（沿用原权重）</button><button class="primary" id="issue-voucher" disabled>签发复测凭证</button></div>'
 +'<p class="hint">签发由负责人执行；日表占用与凭证在同一事务生效，请求编号保证中断重试不重复占用。</p>'
 +'<div class="section-title" style="margin-top:28px"><h2>④ 凭证（待签与已签可查）</h2><span>'+vouchers.length+' 张</span></div>'
 +'<div class="schedule-list">'+vouchers.map(voucherCard).join('')+(vouchers.length?'':'<p class="empty">签发后凭证会出现在这里，简报含原分析与复测两份结论及批次指纹。</p>')+'</div>'
 +'</section></div>';
}

function voucherCard(v){
 const origin=workspace.jobs.find(j=>j.id===v.origin_job_id);
 const d=v.direction||{};
 const issued=v.status==='issued';
 return '<article><div><strong>凭证 V'+fmt(v.id)+' · '+esc(origin?origin.name:('原分析#'+v.origin_job_id))+'</strong><p>'+(issued?'已签发 · '+date(v.issued_at):'待签发（中断后将自动恢复） · 尝试 '+fmt(v.attempts))+'</p><p>复测批次 #'+v.retest_batch_id+' · 原方向 '+esc(d.origin_direction||'-')+' / 复测方向 '+esc(d.retest_direction||'-')+' · '+(d.same_direction?'<span class="approval">方向一致</span>':'<span class="warning" style="display:inline-block;padding:2px 8px">方向不一致</span>')+'</p><small>请求编号 '+esc(v.request_key)+' · SHA256 '+esc((v.checksum||'').slice(0,18))+'…</small></div>'
 +(issued?'<div style="display:flex;flex-direction:column;gap:6px"><button class="text-button" data-voucher="'+v.id+'" data-format="csv">简报 CSV ↓</button><button class="text-button" data-voucher="'+v.id+'" data-format="json">JSON ↓</button></div>':'<button class="button small" disabled>待签</button>')+'</article>';
}

export function bindRetests(refresh){
 document.querySelector('#refresh-retests').onclick=refresh;
 let batchSource='manual.json';
 const fileInput=document.querySelector('#retest-file');
 fileInput?.addEventListener('change',async e=>{
  try{
   const file=e.target.files[0];if(!file)return;
   batchSource=file.name;
   const text=await file.text();
   const records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);
   document.querySelector('[name=records]').value=JSON.stringify(records,null,2);
  }catch(error){notify(error.message,true);}
 });
 submit(document.querySelector('#batch-form'),async f=>{
  await retests.createBatch({name:f.get('name'),source:batchSource,records:JSON.parse(f.get('records'))});
  notify('复测日表已接入并通过校验');await refresh();
 });
 let trialCache=null;
 let requestKey=null;
 const newKey=()=>'rt-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,8);
 document.querySelector('#run-trial')?.addEventListener('click',async()=>{
  const origin=Number(document.querySelector('#retest-origin')?.value);
  const picked=document.querySelector('input[name=pick-batch]:checked')?.value;
  if(!origin)return notify('请先选择已获批分析',true);
  if(!picked)return notify('请选择一个未占用的复测日表',true);
  try{
   const t=await retests.trial({origin_job_id:origin,retest_batch_id:Number(picked)});
   trialCache=t;
   requestKey=t.eligible?newKey():null;  // 新候选换号；同候选重试沿用此号，保证幂等
   const ov=t.overlap||{};
   const d=t.direction||{};
   document.querySelector('#trial-box').innerHTML='<p class="eyebrow">TRIAL / 未占用日表</p>'
    +'<p>'+esc(t.retest_summary||'')+'</p>'
    +'<p>原分析加权A−B：<strong>'+fmt(d.origin_weighted_delta)+'</strong> 百分点（'+esc(d.origin_direction)+'）<br>复测加权A−B：<strong>'+fmt(d.retest_weighted_delta)+'</strong> 百分点（'+esc(d.retest_direction)+'）<br>方向对照：<strong>'+(d.same_direction?'一致':'不一致')+'</strong></p>'
    +(ov.has_overlap?'<p class="warning">重叠辨认未通过：'+ov.matched_observations.length+' 条观察与原分析同 日/队/区域，该批次不能参评。</p>':'<p class="approval">重叠辨认通过：两批无共同 日/队/区域 观察。</p>')
    +(t.occupied?'<p class="warning">该日表已被占用，不能签发。</p>':'')
    +(requestKey?'<p class="hint">本次签发请求编号：<code>'+esc(requestKey)+'</code>，中断后点同一按钮重试不会重复占用。</p>':'');
   const btn=document.querySelector('#issue-voucher');
   btn.disabled=!(t.eligible&&isAdmin());
   btn.title=!isAdmin()?'仅业务负责人可签发':(t.eligible?'':'该候选不具备签发资格');
  }catch(error){notify(error.message,true);}
 });
 document.querySelector('#issue-voucher')?.addEventListener('click',async()=>{
  if(!trialCache?.eligible)return notify('当前试算候选不具备签发资格',true);
  if(!requestKey)requestKey=newKey();
  const btn=document.querySelector('#issue-voucher');
  btn.disabled=true;
  try{
   const v=await retests.issue({origin_job_id:trialCache.origin_job_id,retest_batch_id:trialCache.retest_batch_id,request_key:requestKey});
   notify('凭证 V'+v.id+' 已签发，日表占用已生效');
   requestKey=null;
   await refresh();
  }catch(error){
   notify(error.message+'（可直接重试，请求编号不变且不会重复占用）',true);
   btn.disabled=false;
  }
 });
 document.querySelectorAll('[data-voucher]').forEach(b=>b.onclick=()=>downloadVoucher(b.dataset.voucher,b.dataset.format).catch(e=>notify(e.message,true)));
}
