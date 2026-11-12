import {loadVerifiedHandoff,attentionFromRecord} from './handoff-verify.js';
const node=(tag,text)=>{const element=document.createElement(tag);element.textContent=text;return element;};
const safeView=value=>typeof value==='string'&&/^change-[a-f0-9]{20}\/$/.test(value);
try {
  const response=await fetch('./attention.json',{credentials:'omit',cache:'no-store',redirect:'error'});
  if(!response.ok)throw new Error('The selected attention snapshot is unavailable.');
  const data=await response.json();
  if(data.schema!=='swe-workbench-attention/v1'||!Array.isArray(data.changes))throw new Error('Unsupported attention snapshot.');
  const changes=[];
  for(const selected of data.changes) {
    try {
      if(!safeView(selected.view))throw new Error(selected.problem?.message||'No verifiable package is available for this selected change.');
      const record=await loadVerifiedHandoff('./'+selected.view+'handoff/');
      if(!record)throw new Error('The selected package is missing.');
      const verified=attentionFromRecord(record);
      for(const key of ['change_id','title','decision','needs_attention','responsible_party','next_action','revision','material_digest']) {
        if(verified[key]!==selected[key])throw new Error('Overview differs from its verified package: '+key+'. Inspect the selected detail.');
      }
      changes.push({...verified,view:selected.view});
    } catch(error) {
      changes.push({title:typeof selected.title==='string'?selected.title:'Unavailable change',decision:'unavailable',needs_attention:true,responsible_party:null,next_action:'Inspect the named evidence problem.',problem:error.message,view:safeView(selected.view)?selected.view:null});
    }
  }
  function render() {
    const list=document.getElementById('attention-list');list.replaceChildren();
    for(const c of changes) {
      if(document.getElementById('attention-filter').value==='attention'&&!c.needs_attention)continue;
      const card=node('section','');card.className='card';
      card.append(node('h2',c.title),node('p',c.problem?'Could not verify this selected change: '+c.problem:'Content matches the selected package · unsigned external evidence'));
      if(c.goal)card.append(node('p',c.goal));
      if(c.source_scope)card.append(node('p',c.source_scope.files+' changed files · '+c.source_scope.text+' captured text paths · '+c.source_scope.metadata_only+' metadata-only paths'));
      for(const report of c.reports||[]) {
        card.append(node('p',report.status==='reported'?report.attachment+' · '+report.binding+': '+Object.entries(report.counts).map(([k,v])=>v+' '+k).join(' · '):report.attachment+': invalid supported report'));
      }
      if(c.reports?.length===0)card.append(node('p','No supported check projection; inspect retained observations.'));
      for(const finding of [...(c.findings||[]),...(c.unknowns||[])])card.append(node('p','Needs review: '+finding));
      card.append(node('p','Package: '+c.decision+' · '+(c.needs_attention?'Needs attention':'No attention flag recorded')),node('p','Responsible party: '+(c.responsible_party||'Unassigned')),node('p','Next action: '+c.next_action));
      if(safeView(c.view)) {const link=node('a','Inspect source and results');link.href='./'+c.view;card.append(link);}
      list.append(card);
    }
    if(!list.children.length)list.append(node('p','No selected changes match this view.'));
  }
  document.getElementById('attention-filter').addEventListener('change',render);render();
  const prior=await fetch('./evaluation-demo/index.html',{method:'HEAD',credentials:'omit'});
  if(prior.ok)document.getElementById('evaluation-link').hidden=false;
} catch(error) {const element=document.getElementById('attention-error');element.hidden=false;element.textContent=error.message;}
