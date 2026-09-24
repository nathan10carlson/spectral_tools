'use strict';
// Keep target selection visible regardless of which analysis tab is open.
const targetControls=document.createElement('div');targetControls.className='target-controls';
targetControls.innerHTML='<h3>Select a target</h3><p class="micro">Click a scene pixel or choose a library spectrum, then set the reference.</p>';
targetControls.append($('referenceSelect').parentElement,$('lockReference'));
$('sceneSelectionStatus').before(targetControls);
$('lockReference').className='button violet full';
$('changeReference').className=$('compareAnotherPixel').className='button target-action';
$('goIndex').classList.add('target-action');

const unmixPage=document.createElement('section');unmixPage.id='unmix';unmixPage.className='page';
unmixPage.innerHTML='<div class="unmix-grid"><aside class="panel"><div class="panel-head"><h2>Unmixing settings</h2></div><div id="unmixSettings"></div></aside><div id="unmixMaps"><article id="unmixEmpty" class="panel empty-state"><h2>Map the materials in your scene</h2><p>Select candidates, then run Unmix entire scene. Open the comparison viewer to inspect both images and save a rectangle.</p></article></div></div>';
$('explore').after(unmixPage);$('unmixSettings').append($('fitPanel'));$('fitPanel').hidden=false;
for(const b of document.querySelectorAll('[data-inspector]'))b.onclick=()=>{if(b.dataset.inspector==='fit')setPage('unmix');else $('matchPanel').hidden=false};
for(const id of ['explore','unmix']){const empty=document.createElement('article');empty.className='panel dataset-empty';empty.innerHTML='<div class="empty-state"><h2>Open your hyperspectral dataset</h2><p>Load an ENVI image and its matching header to explore spectra and map material abundances.</p><button class="button violet">Open dataset</button></div>';empty.querySelector('button').onclick=()=>$('openDataset').click();$(id).prepend(empty)}
const sceneRun=document.createElement('div');sceneRun.className='scene-unmix-controls';
sceneRun.innerHTML=`<h3>Unmix every pixel</h3><label>Accuracy<select id="unmixAccuracy"><option value="fast">Fast · exploratory</option><option value="balanced" selected>Balanced</option><option value="precise">Precise · reference tolerance</option></select></label><label>Processing device<select id="unmixDevice"><option value="auto">Auto · benchmark available devices</option><option value="cpu">Batched CPU</option><option value="mps">Apple GPU (MPS)</option><option value="cuda">NVIDIA GPU (CUDA)</option></select></label><p id="backendInfo" class="micro">Checking available devices…</p><p class="micro">Accuracy profiles and GPU acceleration apply to sparse regression. Fractions retain the existing constrained CPU solver.</p><p class="micro">Uses the selected candidates and fitting settings above. Sparse coefficients retain their scale and may exceed 1.</p><label class="checkbox-inline"><input id="retrySparse" type="checkbox" checked>Retry nonconverged sparse fits</label><label>Maximum retry sparsity<input id="retryCeiling" type="number" min="0" max="1" step=".001" value=".1"></label><p class="micro">Retries increase sparsity ×10 up to this limit. Higher sparsity does not guarantee a better reconstruction.</p><button id="unmixScene" class="button violet full">Unmix entire scene</button><button id="cancelUnmix" class="button full" hidden>Pause and keep checkpoint</button><button id="resumeUnmix" class="button full" hidden>Resume saved run</button><progress id="unmixProgress" value="0" max="1" aria-label="Scene unmixing progress"></progress><p id="unmixStatus" role="status" class="micro">Ready to process all pixels.</p>`;
$('candidateList').after(sceneRun);
const previewControls=document.createElement('details');previewControls.className='preview-controls';previewControls.innerHTML='<summary>Preview a region before the full scene</summary><p class="micro">Enter zero-based, inclusive bounds or draw on the original image. The preview estimates full-scene runtime; other regions may converge differently.</p><div class="pair"><label>First row<input id="previewRow0" type="number" min="0" value="0"></label><label>Last row<input id="previewRow1" type="number" min="0" value="63"></label><label>First column<input id="previewCol0" type="number" min="0" value="0"></label><label>Last column<input id="previewCol1" type="number" min="0" value="63"></label></div><button id="pickPreviewRegion" class="button full">Draw preview rectangle</button><button id="runUnmixPreview" class="button full">Run region preview</button>';
$('unmixScene').before(previewControls);
const savedRuns=document.createElement('article');savedRuns.className='panel saved-runs';savedRuns.innerHTML='<div class="panel-head"><h2>Saved analyses</h2><button id="refreshUnmixRuns" class="button subtle">Refresh</button></div><p class="micro">Finished tiles are saved automatically. Runs continue if you close the browser. Resume interrupted runs after restarting HELMET.</p><div id="savedUnmixRuns"></div>';$('unmix').append(savedRuns);
$('fitGrid').value='configured';

const pixelFitDetails=document.createElement('details');pixelFitDetails.className='pixel-fit-details';pixelFitDetails.innerHTML='<summary>Fit a single pixel from Explore</summary>';
pixelFitDetails.append($('fitCoverage'),$('fitPixel'),$('fitResults'));$('fitPanel').append(pixelFitDetails);
const abundancePanel=document.createElement('article');abundancePanel.className='panel abundance-panel';abundancePanel.hidden=true;
abundancePanel.innerHTML=`<div class="panel-head"><h2>Material abundance map</h2><button id="openUnmixViewer" class="button violet">Open comparison viewer</button><button id="exportAbundances" class="button subtle">Download pixel CSV</button></div><div class="abundance-controls"><label>Material channel<select aria-label="Material channel" id="abundanceChannel"></select></label><label>Display maximum<input aria-label="Display maximum" id="abundanceMaximum" type="number" min=".000001" step=".1" value="1"></label><button id="abundanceAuto" class="button">Fit channel range</button></div><p id="abundanceContext" class="micro"></p><div class="abundance-viewport"><canvas id="abundanceCanvas" aria-label="Per-pixel material abundance map"></canvas></div><div class="abundance-legend"><span>0</span><i></i><span id="abundanceMaxLabel">1</span><span>Gray = invalid, failed, or unprocessed</span></div><p id="abundanceReadout" class="reference-info">Hover or click the map to inspect a pixel.</p><div class="abundance-controls"><label>Row<input id="abundanceRow" type="number" min="0" value="0"></label><label>Column<input id="abundanceColumn" type="number" min="0" value="0"></label><button id="inspectAbundance" class="button">Inspect abundance</button></div>`;
$('unmixMaps').append(abundancePanel);
let abundanceRun=null;
function unmixKey(){return JSON.stringify({version:S.meta?.version,ids:[...S.selected],settings:fitSettings(),accuracy:$('unmixAccuracy').value,device:$('unmixDevice').value,retry:$('retrySparse').checked,ceiling:$('retryCeiling').value})}
function clearAbundances(){if(abundanceRun){abundanceRun.cancelled=true;if(abundanceRun.id&&abundanceRun.state==='running')api('unmix/pause',{id:abundanceRun.id}).then(refreshUnmixRuns).catch(e=>toast(e.message,true))}abundanceRun=null;abundancePanel.hidden=true;$('unmixEmpty').hidden=false;if(typeof closeUnmixViewer==='function')closeUnmixViewer();$('unmixProgress').value=0;$('cancelUnmix').hidden=true;$('resumeUnmix').hidden=true;$('unmixScene').disabled=false;$('runUnmixPreview').disabled=false;$('unmixStatus').textContent='Ready. Previous runs are available in Saved analyses.'}
const abundanceChart=renderExploreChart;renderExploreChart=function(){abundanceChart();if(abundanceRun&&abundanceRun.key!==unmixKey())clearAbundances()};
const abundanceLibrary=loadLibrary;loadLibrary=async function(){await abundanceLibrary();clearAbundances()};
for(const id of ['retrySparse','retryCeiling','unmixAccuracy','unmixDevice'])$(id).onchange=clearAbundances;
function renderRun(run){
 if(typeof closeUnmixViewer==='function')closeUnmixViewer();abundanceRun=run;abundancePanel.hidden=false;$('unmixEmpty').hidden=true;
 $('abundanceChannel').innerHTML=run.materials.map((e,i)=>`<option value="${i}">${esc(e.name)}</option>`).join('');
 $('abundanceRow').max=run.meta.rows-1;$('abundanceColumn').max=run.meta.cols-1;
 $('abundanceContext').textContent=`${run.meta.name} · ${run.preview?'Region preview · ':''}${run.settings.mode==='sparse'?'Raw sparse coefficients':'Sum-to-one fractions'} · ${run.accuracy||'balanced'} · source coordinates preserved. Original spectra remain available for export.`;
 $('abundanceReadout').textContent='Hover or click the map to inspect a pixel.';drawAbundances();
}
function durationText(seconds){return seconds<60?Math.ceil(seconds)+'s':seconds<3600?Math.ceil(seconds/60)+' min':(seconds/3600).toFixed(1)+' hr'}
function updateRunProgress(run,record){
 Object.assign(run,{state:record.state,done:record.done,ok:record.counts.ok,retried:record.counts.retried,invalid:record.counts.invalid,failed:record.counts.failed,actual_device:record.actual_device});
 const rate=record.seconds>0?record.done/record.seconds:0;
 const eta=rate?durationText((record.total-record.done)/rate):'estimating';
 $('unmixProgress').max=record.total;$('unmixProgress').value=record.done;
 $('unmixStatus').textContent=`${record.state.toUpperCase()} · ${record.done.toLocaleString()} / ${record.total.toLocaleString()} pixels · ${rate?rate.toFixed(0)+' pixels/s':'preparing first tile'} · remaining ${record.state==='complete'?'0s':eta} · ${record.counts.retried} retried · ${record.counts.failed} failed · ${record.counts.invalid} invalid. ${record.analysis_bands} analysis bands. ${record.device_message}. Cache: ${record.cache_hits} reused, ${record.cache_misses} prepared. ${record.message}`+(record.preview&&rate?` Estimated full scene: ${durationText(run.meta.rows*run.meta.cols/rate)} (approximate).`:'');
 $('cancelUnmix').hidden=record.state!=='running';$('resumeUnmix').hidden=!['paused','error'].includes(record.state)||record.done>=record.total;
 $('unmixScene').disabled=$('runUnmixPreview').disabled=record.state==='running';
}
async function followUnmix(run){
 try{
  while(abundanceRun===run&&!run.cancelled){
   const data=await api(`unmix/status?id=${run.id}&after=${run.cursor}&limit=2048`);
   if(abundanceRun!==run||run.cancelled)return;
   let first=Infinity,last=0;
   for(const p of data.pixels){const index=p.row*run.meta.cols+p.column;run.pixels[index]=p;first=Math.min(first,index);last=Math.max(last,index+1)}
   run.cursor=data.cursor;updateRunProgress(run,data.run);
   if(data.pixels.length)drawAbundances(first,last);
   if(run.cursor>=data.run.done&&data.run.state!=='running'){await refreshUnmixRuns();break}
   if(run.cursor>=data.run.done)await new Promise(resolve=>setTimeout(resolve,600));
  }
 }catch(e){if(abundanceRun===run){$('unmixStatus').textContent='Connection interrupted. Finished tiles are saved. Load the run from Saved analyses to reconnect. '+e.message;$('resumeUnmix').hidden=false;$('unmixScene').disabled=$('runUnmixPreview').disabled=false;}}
}
function showSavedRecord(record){
 if(abundanceRun)abundanceRun.cancelled=true;abundanceRun=null;
 S.meta=record.meta;S.settings={...record.settings};S.selected=new Set(record.materials.map(e=>e.spectrum_id));
 $('fitGrid').value=record.settings.fit_grid||'configured';$('fitMode').value=record.settings.mode||'sparse';$('fitStrength').value=record.settings.strength??.001;$('fitLimit').value=record.settings.max_materials||0;
 $('unmixAccuracy').value=record.accuracy;$('unmixDevice').value=record.device;$('retrySparse').checked=record.retry.enabled;$('retryCeiling').value=record.retry.ceiling;
 $('strengthLabel').hidden=$('fitMode').value==='fractions';$('limitLabel').hidden=$('fitMode').value!=='fractions';
 S.pixelRequest++;S.pixel=null;S.reference=null;S.comparison=null;S.selectionPurpose='reference';S.scores=null;invalidateFit();renderSceneSelection();renderMeta();renderCandidates();reloadImage(true);setPage('unmix');
 const run={...record,startedAt:record.created,key:unmixKey(),pixels:new Array(record.meta.rows*record.meta.cols),cursor:0,cancelled:false,palette:S.palette};
 renderRun(run);updateRunProgress(run,record);followUnmix(run);
}
async function startUnmix(preview=false){
 if(!S.meta)throw Error('Open a dataset first.');const ids=[...S.selected];if(!ids.length)throw Error('Select candidates first.');
 let bounds=null;
 if(preview){bounds={row_start:Number($('previewRow0').value),row_end:Number($('previewRow1').value),column_start:Number($('previewCol0').value),column_end:Number($('previewCol1').value)};if(['previewRow0','previewRow1','previewCol0','previewCol1'].some(id=>$(id).value===''))throw Error('Enter all preview bounds.');}
 const settings=fitSettings();
 const record=await api('unmix/start',{version:S.meta.version,ids,settings,accuracy:$('unmixAccuracy').value,device:$('unmixDevice').value,retry:$('retrySparse').checked,ceiling:Number($('retryCeiling').value),bounds,preview});
 showSavedRecord(record);await refreshUnmixRuns();
}
$('unmixScene').onclick=()=>busy($('unmixScene'),()=>startUnmix(false)).then(()=>{if(abundanceRun?.state==='running')$('unmixScene').disabled=true});
$('runUnmixPreview').onclick=()=>busy($('runUnmixPreview'),()=>startUnmix(true)).then(()=>{if(abundanceRun?.state==='running')$('runUnmixPreview').disabled=true});
$('cancelUnmix').onclick=()=>busy($('cancelUnmix'),async()=>{if(abundanceRun?.id){await api('unmix/pause',{id:abundanceRun.id});$('unmixStatus').textContent='Pausing; completed tiles are already saved…'}});
$('resumeUnmix').onclick=()=>busy($('resumeUnmix'),async()=>{if(!abundanceRun?.id)return;showSavedRecord(await api('unmix/resume',{id:abundanceRun.id}));await refreshUnmixRuns()});
async function refreshUnmixRuns(){
 const records=await api('unmix/runs');$('savedUnmixRuns').innerHTML=records.map(r=>`<div class="saved-run"><div><strong>${esc(r.label)}</strong><small>${esc(new Date(r.created).toLocaleString())} · ${esc(r.state)} · ${r.done.toLocaleString()} / ${r.total.toLocaleString()} pixels</small></div><button class="button" data-run-id="${r.id}">Open saved run</button></div>`).join('')||'<p class="micro">No saved analyses yet.</p>';
 for(const button of $('savedUnmixRuns').querySelectorAll('button'))button.onclick=()=>busy(button,async()=>showSavedRecord(await api('unmix/load',{id:button.dataset.runId})));
}
$('refreshUnmixRuns').onclick=()=>busy($('refreshUnmixRuns'),refreshUnmixRuns);
(async()=>{try{const data=await api('unmix/backends');$('backendInfo').textContent=data.devices.map(v=>v.toUpperCase()).join(' + ')+'. '+data.message;for(const option of $('unmixDevice').options)if(!['auto','cpu'].includes(option.value)&&!data.devices.includes(option.value))option.disabled=true;await refreshUnmixRuns()}catch(e){$('backendInfo').textContent=e.message}})();
function drawAbundances(start=0,end=abundanceRun?.pixels.length){
 const run=abundanceRun;if(!run)return;
 const canvas=$('abundanceCanvas'),channel=Number($('abundanceChannel').value),max=Number($('abundanceMaximum').value);
 if(!Number.isFinite(max)||max<=0)return;
 if(canvas.width!==run.meta.cols||canvas.height!==run.meta.rows){canvas.width=run.meta.cols;canvas.height=run.meta.rows;}
 const firstRow=Math.floor(start/run.meta.cols),lastRow=Math.ceil(end/run.meta.cols),offset=firstRow*run.meta.cols;
 const context=canvas.getContext('2d'),pixels=context.createImageData(canvas.width,lastRow-firstRow);
 for(let i=offset;i<lastRow*run.meta.cols;i++){
  const v=run.pixels[i]?.coefficients?.[channel];
  if(v===undefined||v===null){pixels.data.set([81,87,99,255],(i-offset)*4);continue}
  const t=Math.max(0,Math.min(1,v/max));pixels.data.set([Math.round(12+52*t),Math.round(20+183*t),Math.round(40+123*t),255],(i-offset)*4);
 }
 context.putImageData(pixels,0,firstRow);$('abundanceMaxLabel').textContent=max.toPrecision(4);if(typeof drawLinkedViews==='function')drawLinkedViews();
}
function readAbundance(row,column){
 const run=abundanceRun;if(!run)return;
 if(!Number.isInteger(row)||!Number.isInteger(column)||row<0||column<0||row>=run.meta.rows||column>=run.meta.cols)return;
 const p=run.pixels[row*run.meta.cols+column],channel=Number($('abundanceChannel').value),material=run.materials[channel];
 $('abundanceRow').value=row;$('abundanceColumn').value=column;
 $('abundanceReadout').textContent=`Row ${row}, column ${column} · ${material.name}: ${p?.coefficients?p.coefficients[channel].toPrecision(6):'unavailable'} · ${p?.status||'unprocessed'}${p?.rmse!=null?' · RMSE '+p.rmse.toPrecision(4):''}${p?.strength!=null?' · sparsity '+p.strength:''}${p?.message?' · '+p.message:''}`;
}
$('abundanceCanvas').onpointermove=$('abundanceCanvas').onclick=e=>{const run=abundanceRun;if(!run)return;const rect=e.currentTarget.getBoundingClientRect();readAbundance(Math.floor((e.clientY-rect.top)/rect.height*run.meta.rows),Math.floor((e.clientX-rect.left)/rect.width*run.meta.cols))};
$('inspectAbundance').onclick=()=>readAbundance(Number($('abundanceRow').value),Number($('abundanceColumn').value));
$('abundanceChannel').onchange=()=>{drawAbundances();$('inspectAbundance').click()};$('abundanceMaximum').oninput=()=>drawAbundances();
$('abundanceAuto').onclick=()=>{if(!abundanceRun)return;let max=0;const channel=Number($('abundanceChannel').value);for(const p of abundanceRun.pixels)max=Math.max(max,p?.coefficients?.[channel]||0);$('abundanceMaximum').value=max||1;drawAbundances()};
$('exportAbundances').onclick=()=>{
 const run=abundanceRun;if(!run)return;
 const lines=[['dataset','row','column','status','mode','sparsity_used','attempts','used_bands','rmse','relative_error','message',...run.materials.map(e=>e.name+' ['+e.spectrum_id+']')].map(cell).join(',')];
 for(let i=0;i<run.pixels.length;i++){
  const p=run.pixels[i];lines.push([run.meta.name,Math.floor(i/run.meta.cols),i%run.meta.cols,p?.status||'unprocessed',run.settings.mode,p?.strength,p?.attempts,p?.used_bands,p?.rmse,p?.relative_error,p?.message,...run.materials.map((_,j)=>p?.coefficients?.[j])].map(cell).join(','));
 }
 download('HELMET-pixel-abundances.csv',lines.join('\n'));
};

const unmixRenderMeta=renderMeta;renderMeta=function(){unmixRenderMeta();if(!S.meta)return;for(const [id,max] of [['previewRow0',S.meta.rows-1],['previewRow1',S.meta.rows-1],['previewCol0',S.meta.cols-1],['previewCol1',S.meta.cols-1]]){$(id).max=max;$(id).value=Math.min(Number($(id).value),max)}};
if(S.meta)renderMeta();
