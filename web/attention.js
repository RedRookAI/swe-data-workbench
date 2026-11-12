const node=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
try{
 const response=await fetch('./attention.json',{credentials:'omit',cache:'no-store'});if(!response.ok)throw new Error('The selected attention snapshot is unavailable.');
 const data=await response.json();if(data.schema!=='swe-workbench-attention/v1'||!Array.isArray(data.changes))throw new Error('Unsupported attention snapshot.');
 function render(){const list=document.getElementById('attention-list');list.replaceChildren();for(const c of data.changes){if(document.getElementById('attention-filter').value==='attention'&&!c.needs_attention)continue;const card=node('section','');card.className='card';card.append(node('h2',c.title),node('p','Package: '+c.decision+' · '+(c.needs_attention?'Needs attention':'No attention flag recorded')),node('p','Responsible party: '+(c.responsible_party||'Unassigned')),node('p','Next action: '+c.next_action));if(/^change-[a-f0-9]{20}\/$/.test(c.view)){const link=node('a','Inspect source and results');link.href='./'+c.view;card.append(link);}list.append(card);}if(!list.children.length)list.append(node('p','No selected changes match this view.'));}
 document.getElementById('attention-filter').addEventListener('change',render);render();
 const prior=await fetch('./evaluation-demo/index.html',{method:'HEAD',credentials:'omit'});if(prior.ok)document.getElementById('evaluation-link').hidden=false;
}catch(error){const e=document.getElementById('attention-error');e.hidden=false;e.textContent=error.message;}
