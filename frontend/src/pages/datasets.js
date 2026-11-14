import {datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,fmt,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';

const MONEY_KEYS=['gross','refunds','discount','recognized_net'];

function batchMeta(d){
 if(d.kind!=='supplement')return '';
 const m=d.merge||{};
 return '<small class="supplement-tag">补账 · 原批次 #'+esc(d.parent_id)+' · 替换 '+esc(m.replaced_rows??'—')+' 行 · 新增 '+esc(m.added_rows??'—')+' 行</small>';
}

function mergePanel(d){
 if(!d.merge_detail||d.kind!=='supplement')return '';
 const m=d.merge_detail;
 const replaced=m.replaced||[],added=m.added||[];
 const replacedRows=replaced.map(r=>({day:r.day,channel:r.channel,
   previous:MONEY_KEYS.map(k=>fmt(r.previous?.[k])).join(' / ')+' / '+fmt(r.previous?.visits),
   current:MONEY_KEYS.map(k=>fmt(r.current?.[k])).join(' / ')+' / '+fmt(r.current?.visits)}));
 const addedRows=added.map(r=>({day:r.day,channel:r.channel,...r.record}));
 return '<section class="panel"><div class="section-title"><h2>补账溯源</h2><span>原批次 '+esc(m.parent_name||('#'+m.parent_id))+' 保持不变</span></div>'+
  '<div class="merge-summary"><div><span>原批次行数</span><strong>'+esc(m.base_rows)+'</strong></div><div><span>补账提交行数</span><strong>'+esc(m.supplement_rows)+'</strong></div><div><span>同日同渠道整行替换</span><strong>'+esc(m.replaced_rows)+'</strong></div><div><span>新日期补入</span><strong>'+esc(m.added_rows)+'</strong></div><div><span>其余源账保留</span><strong>'+esc(m.retained_rows)+'</strong></div><div><span>补账后批次行数</span><strong>'+esc(m.merged_rows)+'</strong></div></div>'+
  '<p class="hint">补账源账 SHA256 '+esc(m.supplement_checksum||'')+'；原批次 SHA256 '+esc(m.parent_checksum||'')+'。相同补账重复提交不会再生成第二份。</p>'+
  '<h3>被替换的记录（'+replaced.length+'）</h3>'+table([{key:'day',label:'日期'},{key:'channel',label:'渠道'},{key:'previous',label:'原记录 毛额/退款/折扣/认可净额/访问'},{key:'current',label:'补账记录 毛额/退款/折扣/认可净额/访问'}],replacedRows,'本次补账没有替换原批次记录。')+
  '<h3>新增的记录（'+added.length+'）</h3>'+table(workspace.meta.columns,addedRows,'本次补账没有新增日期。')+'</section>';
}

function supplementsPanel(d){
 const list=d.supplements||[];
 if(d.kind==='supplement')return '';
 return '<section class="panel"><div class="section-title"><h2>该原批次的补账批次</h2><span>'+list.length+' 份</span></div>'+
  (list.length?'<div class="supplement-list">'+list.map(s=>'<button class="batch-item" data-dataset="'+s.id+'"><strong>'+esc(s.name)+'</strong><small>#'+esc(s.id)+' · '+esc(s.rows)+' 条 · '+esc(s.source)+'</small>'+batchMeta(s)+'</button>').join('')+'</div>':'<p class="empty">尚无补账。可在左侧选定本批次后提交补账源账。</p>')+'</section>';
}

export async function dataPage(){
 workspace.datasets=await datasets.list();let selected=workspace.datasets[0]?await datasets.get(workspace.datasets[0].id):null,m=workspace.meta;
 const baseOptions=workspace.datasets.map(d=>'<option value="'+d.id+'">'+esc(d.name)+' · #'+d.id+' · '+d.rows+' 条'+(d.kind==='supplement'?'（补账）':'')+'</option>').join('');
 return heading('02 / DATA INTAKE','数据接入与批次追溯','保留原始业务字段、来源和内容指纹。分析任务始终绑定一个不可变数据批次；补账会生成新的批次，原批次和既有结果保持原样。')+'<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>业务批次</h2><span>'+workspace.datasets.length+' 批</span></div><div class="batch-list">'+workspace.datasets.map(d=>'<button class="batch-item'+(selected&&d.id===selected.id?' active':'')+'" data-dataset="'+d.id+'"><strong>'+esc(d.name)+'</strong><span>'+d.rows+' 条 · '+esc(d.source)+'</span><small>SHA256 '+esc(d.checksum.slice(0,18))+'…</small>'+batchMeta(d)+'</button>').join('')+'</div><div class="section-title"><h2>接入新数据</h2></div><form id="dataset-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月复测批次"></label><label>上传 CSV 或 JSON<input type="file" id="file-input" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="6" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label><p class="hint">字段：'+m.columns.map(c=>esc(c.key)+' / '+esc(c.label)).join('，')+'。5–5,000 条记录。</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>校验并接入批次</button></form><div class="section-title supplement-title"><h2>对选定原批次补账</h2></div><form id="supplement-form"><label>原批次<select name="parent_id" required>'+baseOptions+'</select></label><label>补账批次名称（可选）<input name="name" maxlength="160" placeholder="留空则自动命名为「原批次 · 补账 指纹」"></label><label>上传补账 CSV 或 JSON<input type="file" id="supplement-file" accept=".json,.csv"></label><label>补账记录 JSON<textarea name="records" rows="5" placeholder="1–5,000 条。同日同渠道整行替换，新日期补入，其余保留" required></textarea></label><p class="hint">含重复键、坏字段、非CNY或非整数访问时整批拒绝，不写入任何记录。相同内容重复补发只保留第一份。</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>校验并生成补账批次</button></form></section><section class="panel"><div class="section-title"><h2 id="preview-name">'+esc(selected?.name||'尚无批次')+'</h2><span id="preview-kind">'+(selected?.kind==='supplement'?'补账批次 · 预览前 30 条':'预览前 30 条')+'</span></div><div id="data-preview">'+table(m.columns,selected?.records.slice(0,30)||[])+'</div><div id="merge-panel">'+(selected?mergePanel(selected)+supplementsPanel(selected):'')+'</div></section></div>';
}

async function showDataset(id){
 const d=await datasets.get(id);
 document.querySelectorAll('[data-dataset]').forEach(b=>b.classList.toggle('active',Number(b.dataset.dataset)===d.id));
 const selected=workspace.datasets.find(x=>x.id===d.id);
 if(selected){selected.merge=d.merge;selected.kind=d.kind;selected.parent_id=d.parent_id;selected.rows=d.rows;}
 document.querySelector('#preview-name').textContent=d.name;
 document.querySelector('#preview-kind').textContent=d.kind==='supplement'?'补账批次 · 预览前 30 条':'预览前 30 条';
 document.querySelector('#data-preview').innerHTML=table(workspace.meta.columns,d.records.slice(0,30));
 document.querySelector('#merge-panel').innerHTML=mergePanel(d)+supplementsPanel(d);
 document.querySelectorAll('#merge-panel [data-dataset]').forEach(bindBatchButton);
}

function bindBatchButton(button){
 button.onclick=async()=>{try{await showDataset(Number(button.dataset.dataset));}catch(error){notify(error.message,true);}};
}

export function bindData(refresh){
 let source='manual.json',supplementSource='supplement.json';
 document.querySelector('#file-input').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;source=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('[name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 document.querySelector('#supplement-file').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;supplementSource=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('#supplement-form [name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 document.querySelectorAll('[data-dataset]').forEach(bindBatchButton);
 submit(document.querySelector('#dataset-form'),async f=>{await datasets.create({name:f.get('name'),source,records:JSON.parse(f.get('records'))});notify('数据已接入，可前往工作台执行分析');await refresh();});
 submit(document.querySelector('#supplement-form'),async f=>{const d=await datasets.supplement(Number(f.get('parent_id')),{name:(f.get('name')||'').trim(),source:supplementSource,records:JSON.parse(f.get('records'))});notify(d.duplicate?'相同补账已存在，返回原补账批次 #'+d.id+'，未生成第二份':'补账批次已生成：'+d.name+'（替换 '+(d.merge?.replaced_rows??0)+' 行，新增 '+(d.merge?.added_rows??0)+' 行）');await refresh();});
}
