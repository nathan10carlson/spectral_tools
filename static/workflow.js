'use strict';
// Library browsing controls and contextual batch actions.
const libraryToolbar=document.querySelector('.library-toolbar');
const grouping=document.createElement('label');grouping.className='grouping-control';grouping.innerHTML='Group by<select id="libraryGrouping"><option value="category">Category</option><option value="none">None</option></select>';libraryToolbar.append(grouping);
$('groupCategories').parentElement.hidden=true;
$('libraryGrouping').onchange=()=>{$('groupCategories').checked=$('libraryGrouping').value==='category';$('groupCategories').onchange()};
const manage=document.createElement('details');manage.className='library-manage';manage.innerHTML='<summary class="button subtle">Manage library ▾</summary><div class="manage-options"></div>';libraryToolbar.append(manage);
for(const id of ['newCategory','reviewDuplicates'])manage.querySelector('div').append($(id));
const reviewArchived=document.createElement('button');reviewArchived.className='quiet';reviewArchived.textContent='Review archived';reviewArchived.id='reviewArchived';manage.querySelector('div').append(reviewArchived);
manage.addEventListener('click',e=>{if(e.target.closest('button'))manage.open=false});
const selectionBar=document.querySelector('.library-actions');selectionBar.classList.add('selection-bar');libraryToolbar.after(selectionBar);selectionBar.prepend(Object.assign(document.createElement('strong'),{id:'librarySelectionCount'}));
const clearSelection=Object.assign(document.createElement('button'),{className:'quiet',textContent:'Clear selection'});selectionBar.append(clearSelection);clearSelection.onclick=()=>{S.compare.clear();renderLibrary()};
function renderSelectionBar(){const count=[...S.compare].filter(id=>entry(id)&&!entry(id).archived).length;selectionBar.hidden=!count;$('librarySelectionCount').textContent=count+' spectra selected';$('averageSelected').disabled=count<2;$('bulkCategory').disabled=!count}
const selectionChart=renderLibraryChart;renderLibraryChart=function(){selectionChart();renderSelectionBar()};
const groupedLibrary=renderLibrary;renderLibrary=function(){groupedLibrary();for(const group of document.querySelectorAll('.category-group')){const ids=[...group.querySelectorAll('.material-card')].map(card=>card.dataset.id);const actions=document.createElement('details');actions.className='category-actions';actions.innerHTML='<summary aria-label="Category actions">•••</summary>';for(const [label,callback]of [['Select category',()=>{ids.forEach(id=>S.compare.add(id));renderLibrary()}],['Review duplicates',()=>{S.compare=new Set(ids);renderLibrary();$('reviewDuplicates').click()}]]){const button=Object.assign(document.createElement('button'),{className:'quiet',textContent:label});button.disabled=label==='Review duplicates'&&ids.length<2;button.onclick=callback;actions.append(button)}group.querySelector('summary').after(actions)}renderSelectionBar()};
function archivedReview(){
 const archived=S.library.filter(e=>e.archived);
 modal('Review archived',`<p>Restore archived spectra or permanently remove them from this library.</p><div class="archive-list">${archived.map(e=>`<label class="archive-entry"><input type="checkbox" value="${e.spectrum_id}" aria-label="Select archived ${esc(e.name)}"><span><b>${esc(e.name)}</b><small>${esc(e.category)} · ${e.values.length} bands</small></span></label><button class="quiet archive-edit" data-id="${e.spectrum_id}">Edit ${esc(e.name)}</button>`).join('')||'<p>No archived spectra.</p>'}</div><div class="pair"><button id="restoreArchived" class="button" disabled>Restore selected</button><button id="deleteArchived" class="button danger" disabled>Delete permanently…</button></div>`);
 for(const button of $('modalBody').querySelectorAll('.archive-edit'))button.onclick=()=>{const e=entry(button.dataset.id);$('modal').close();editDialog(e)};
 const selected=()=>[...$('modalBody').querySelectorAll('.archive-entry input:checked')].map(e=>e.value);
 for(const cb of $('modalBody').querySelectorAll('.archive-entry input'))cb.onchange=()=>{$('restoreArchived').disabled=$('deleteArchived').disabled=!selected().length};
 $('restoreArchived').onclick=()=>busy($('restoreArchived'),async()=>{await api('library/archived',{ids:selected(),action:'restore'});await loadLibrary();$('modal').close();archivedReview();toast('Selected spectra restored.')});
 $('deleteArchived').onclick=()=>{const ids=selected(),names=ids.map(id=>entry(id).name);$('modal').close();modal('Permanently delete spectra',`<p>These ${ids.length} spectra will be removed from the running CSV library. This cannot be undone.</p><ul>${names.map(n=>`<li>${esc(n)}</li>`).join('')}</ul><label>Type DELETE to confirm<input id="deleteConfirmation" autocomplete="off"></label><div class="pair"><button id="cancelDeletion" class="button">Cancel</button><button id="confirmDeletion" class="button danger" disabled>Delete permanently</button></div>`);$('deleteConfirmation').oninput=()=>{$('confirmDeletion').disabled=$('deleteConfirmation').value!=='DELETE'};$('cancelDeletion').onclick=()=>{$('modal').close();archivedReview()};$('confirmDeletion').onclick=()=>busy($('confirmDeletion'),async()=>{await api('library/archived',{ids,action:'delete',confirmation:$('deleteConfirmation').value});await loadLibrary();$('modal').close();archivedReview();toast('Selected archived spectra deleted.')})};
}
reviewArchived.onclick=archivedReview;
// Explicit scene roles: clicks can never silently replace a locked reference.
function renderSceneSelection(){
 const purpose=S.selectionPurpose,locked=!!S.reference;
 $('sceneSelectionStatus').textContent=purpose==='reference'?'Choose reference · click the scene or enter coordinates, then Set reference.':purpose==='comparison'?'Choose comparison · click the scene or enter coordinates.':('Reference locked · '+(S.reference?.name||''));
 $('pixelForm').hidden=!purpose;$('referenceSelect').parentElement.hidden=purpose!=='reference';$('lockReference').hidden=purpose!=='reference';
 $('changeReference').hidden=!locked;$('compareAnotherPixel').hidden=!locked;$('clearComparison').hidden=!S.comparison;
 $('goIndex').textContent=purpose==='comparison'?'Select comparison pixel':'Preview reference pixel';
 $('compareAnotherPixel').textContent=S.comparison?'Change comparison pixel':'Compare another pixel';
 $('savePixel').textContent=purpose==='comparison'?'＋ Save comparison spectrum':'＋ Save reference spectrum';
 $('spectrumLabel').textContent=S.comparison?'Reference + comparison':locked?'Reference spectrum':'Reference preview';
 $('referenceInfo').textContent=locked?'Reference · '+S.reference.name:'No reference locked yet.';
}
function chooseSceneRole(role){S.pixelRequest++;S.selectionPurpose=role;S.pixel=null;invalidateFit();$('toolinspect').click();renderSceneSelection();drawScene()}
$('changeReference').onclick=()=>{chooseSceneRole('reference');$('referenceSelect').value='pixel'};
$('compareAnotherPixel').onclick=()=>chooseSceneRole('comparison');
$('clearComparison').onclick=()=>{S.pixelRequest++;S.comparison=null;S.pixel=S.reference;S.selectionPurpose=null;invalidateFit();renderSceneSelection();drawScene();$('selectedScore').textContent=''};
// Give the explorer reference its own visual hierarchy and category filter.
const targetLabel=$('materialTarget').parentElement;
const referenceCard=document.createElement('article');referenceCard.className='panel explorer-reference';referenceCard.innerHTML='<div class="panel-head"><h2><i class="reference-swatch"></i> Reference spectrum</h2><span class="micro">Compared against library matches</span></div><div class="reference-picker"><label>Target category<select id="targetCategory"><option value="">All categories</option></select></label></div><div id="referenceMetadata" class="reference-metadata"></div>';
$('materials').prepend(referenceCard);referenceCard.querySelector('.reference-picker').append(targetLabel);
const targetText=targetLabel.firstChild;if(targetText.nodeType===3)targetText.textContent='Target spectrum';
$('materialScope').parentElement.firstChild.textContent='Search for matches in';
const explorerRender=renderMaterialExplorer;renderMaterialExplorer=function(){const selected=$('targetCategory').value;$('targetCategory').innerHTML='<option value="">All categories</option>'+categoryNames().map(c=>`<option>${esc(c)}</option>`).join('');$('targetCategory').value=selected;explorerRender();renderReferenceMetadata()};
function renderReferenceMetadata(){const e=materialTarget();$('referenceMetadata').innerHTML=e?`<strong>${esc(e.name)}</strong><span>${esc(e.category||'Scene spectrum')} · ${Math.round(e.wavelengths[0])}–${Math.round(e.wavelengths.at(-1))} nm · ${e.values.filter(v=>v!==null).length} valid bands</span>`:'Choose the reference you want to compare.'}
const materialCharts=renderMaterialCharts;renderMaterialCharts=function(){materialCharts();renderReferenceMetadata()};
$('targetCategory').onchange=()=>{renderMaterialExplorer();invalidateComparison()};
renderSelectionBar();renderSceneSelection();
// The coverage preview uses the same alignment path as the abundance solver.
let coverageKey='',coverageRequest=0,coverageTimer;
function refreshFitCoverage(){
 const target=S.pixel,ids=[...S.selected],settings=fitSettings();
 const key=JSON.stringify({target,ids,settings});if(key===coverageKey)return;coverageKey=key;const request=++coverageRequest;clearTimeout(coverageTimer);
 if(!target||!ids.length){$('fitCoverage').innerHTML='<p class="micro">Choose a target pixel and candidates to preview coverage.</p>';return}
 $('fitCoverage').innerHTML='<p class="micro">Checking shared wavelength coverage…</p>';
 coverageTimer=setTimeout(async()=>{try{const d=await api('fit/preview',{target,ids,settings});if(request!==coverageRequest)return;
 const colors={'usable':'#40cba3','target excluded':'#465266','candidate unavailable':'#f5b76a'};
 const min=d.wavelengths[0],max=d.wavelengths.at(-1),width=260;
 const marks=d.wavelengths.map((w,i)=>`<line x1="${5+(w-min)/(max-min)*250}" x2="${5+(w-min)/(max-min)*250}" y1="4" y2="24" stroke="${colors[d.status[i]]}" stroke-width="2"><title>${w.toFixed(1)} nm · ${d.status[i]}</title></line>`).join('');
 $('fitCoverage').innerHTML=`<h3>Wavelength coverage</h3><p class="micro">Fitting ${esc(target.name)}<br>Target: ${d.target_bands} bands · Analysis: ${d.analysis_bands}<br><strong>${d.used_bands} shared usable bands</strong></p><svg viewBox="0 0 ${width} 30" role="img" aria-label="Shared wavelength coverage">${marks}</svg><div class="coverage-legend"><span style="color:#40cba3">● Usable</span><span style="color:#8a97ac">● Target excluded</span><span style="color:#f5b76a">● Candidate missing</span></div><p class="micro">${Math.round(min)}–${Math.round(max)} nm · no extrapolation</p><details><summary>Candidate coverage (${d.candidates.length})</summary>${d.candidates.map(c=>`<div class="coverage-candidate"><b>${esc(c.name)}</b><span>${c.source_bands} source bands → ${c.overlap_bands}/${d.target_valid_bands} valid target bands${c.limited?' · limited overlap':''}</span></div>`).join('')}</details>${d.message?`<p class="warning">${esc(d.message)}</p>`:''}`;
 }catch(e){if(request===coverageRequest)$('fitCoverage').innerHTML=`<p class="warning">${esc(e.message)}</p>`}},120);
}
const coverageChart=renderExploreChart;renderExploreChart=function(){coverageChart();refreshFitCoverage()};
refreshFitCoverage();
