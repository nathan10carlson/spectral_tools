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
sceneRun.innerHTML=`<h3>Unmix every pixel</h3><p class="micro">Uses the selected candidates and fitting settings above. Sparse coefficients retain their scale and may exceed 1.</p><label class="checkbox-inline"><input id="retrySparse" type="checkbox" checked>Retry nonconverged sparse fits</label><label>Maximum retry sparsity<input id="retryCeiling" type="number" min="0" max="1" step=".001" value=".1"></label><p class="micro">Retries increase sparsity ×10 up to this limit. Higher sparsity does not guarantee a better reconstruction.</p><button id="unmixScene" class="button violet full">Unmix entire scene</button><button id="cancelUnmix" class="button full" hidden>Stop after current batch</button><progress id="unmixProgress" value="0" max="1" aria-label="Scene unmixing progress"></progress><p id="unmixStatus" role="status" class="micro">Ready to process all pixels.</p>`;
$('candidateList').after(sceneRun);
const pixelFitDetails=document.createElement('details');pixelFitDetails.className='pixel-fit-details';pixelFitDetails.innerHTML='<summary>Fit a single pixel from Explore</summary>';
pixelFitDetails.append($('fitCoverage'),$('fitPixel'),$('fitResults'));$('fitPanel').append(pixelFitDetails);
const abundancePanel=document.createElement('article');abundancePanel.className='panel abundance-panel';abundancePanel.hidden=true;
abundancePanel.innerHTML=`<div class="panel-head"><h2>Material abundance map</h2><button id="openUnmixViewer" class="button violet">Open comparison viewer</button><button id="exportAbundances" class="button subtle">Download pixel CSV</button></div><div class="abundance-controls"><label>Material channel<select aria-label="Material channel" id="abundanceChannel"></select></label><label>Display maximum<input aria-label="Display maximum" id="abundanceMaximum" type="number" min=".000001" step=".1" value="1"></label><button id="abundanceAuto" class="button">Fit channel range</button></div><p id="abundanceContext" class="micro"></p><div class="abundance-viewport"><canvas id="abundanceCanvas" aria-label="Per-pixel material abundance map"></canvas></div><div class="abundance-legend"><span>0</span><i></i><span id="abundanceMaxLabel">1</span><span>Gray = invalid, failed, or unprocessed</span></div><p id="abundanceReadout" class="reference-info">Hover or click the map to inspect a pixel.</p><div class="abundance-controls"><label>Row<input id="abundanceRow" type="number" min="0" value="0"></label><label>Column<input id="abundanceColumn" type="number" min="0" value="0"></label><button id="inspectAbundance" class="button">Inspect abundance</button></div>`;
$('unmixMaps').append(abundancePanel);
let abundanceRun=null;
function unmixKey(){return JSON.stringify({version:S.meta?.version,ids:[...S.selected],settings:fitSettings(),retry:$('retrySparse').checked,ceiling:$('retryCeiling').value})}
function clearAbundances(){if(abundanceRun)abundanceRun.cancelled=true;abundanceRun=null;abundancePanel.hidden=true;$('unmixEmpty').hidden=false;if(typeof closeUnmixViewer==='function')closeUnmixViewer();$('unmixProgress').value=0;$('unmixStatus').textContent='Inputs changed. Run scene unmixing again.'}
const abundanceChart=renderExploreChart;renderExploreChart=function(){abundanceChart();if(abundanceRun&&abundanceRun.key!==unmixKey())clearAbundances()};
const abundanceLibrary=loadLibrary;loadLibrary=async function(){await abundanceLibrary();clearAbundances()};
for(const id of ['retrySparse','retryCeiling'])$(id).onchange=clearAbundances;
$('cancelUnmix').onclick=()=>{if(abundanceRun){abundanceRun.cancelled=true;$('unmixStatus').textContent='Stopping after current batch…'}};
$('unmixScene').onclick=()=>busy($('unmixScene'),async()=>{
 if(!S.meta)throw Error('Open a dataset first.');
 const ids=[...S.selected];if(!ids.length)throw Error('Select at least one candidate.');
 const settings=fitSettings(),ceiling=Number($('retryCeiling').value),retry=$('retrySparse').checked;
 if(retry&&settings.mode==='sparse'&&(!Number.isFinite(ceiling)||ceiling<settings.strength||ceiling>1))throw Error('Maximum retry sparsity must be between the initial sparsity and 1.');
 const run={startedAt:new Date().toISOString(),key:unmixKey(),meta:{...S.meta},settings,materials:ids.map(id=>({...entry(id)})),pixels:new Array(S.meta.rows*S.meta.cols),done:0,ok:0,retried:0,failed:0,invalid:0,cancelled:false,retry:{enabled:retry,ceiling},palette:S.palette};
 if(typeof closeUnmixViewer==='function')closeUnmixViewer();abundanceRun=run;abundancePanel.hidden=false;$('unmixEmpty').hidden=true;
 $('abundanceChannel').innerHTML=run.materials.map((e,i)=>`<option value="${i}">${esc(e.name)}</option>`).join('');
 $('abundanceRow').max=run.meta.rows-1;$('abundanceColumn').max=run.meta.cols-1;
 $('abundanceContext').textContent=`${run.meta.name} · ${settings.mode==='sparse'?'Raw sparse coefficients':'Sum-to-one fractions'} · zero-based rows and columns. Values above the display maximum saturate; CSV retains exact values.`;
 $('abundanceReadout').textContent='Hover or click the map to inspect a pixel.';
 $('unmixStatus').textContent=`Processing ${run.pixels.length.toLocaleString()} pixels…`;$('cancelUnmix').hidden=false;$('unmixProgress').max=run.pixels.length;$('unmixProgress').value=0;
 drawAbundances();
 try{
  while(run.done<run.pixels.length&&!run.cancelled){
   const data=await api('fit/scene',{version:run.meta.version,ids,settings,start:run.done,count:64,retry,ceiling:retry&&settings.mode==='sparse'?ceiling:Math.max(settings.strength,1)});
   if(abundanceRun!==run||run.key!==unmixKey())break;
   for(const p of data.pixels){run.pixels[p.row*run.meta.cols+p.column]=p;run[p.status]++}
   const previous=run.done;run.done=data.next;$('unmixProgress').value=run.done;
   $('unmixStatus').textContent=`${run.done.toLocaleString()} / ${run.pixels.length.toLocaleString()} pixels · ${run.retried} retried · ${run.failed} failed · ${run.invalid} invalid`;
   drawAbundances(previous,run.done);
  }
  if(abundanceRun===run)$('unmixStatus').textContent=(run.done===run.pixels.length?'Complete. ':'Stopped. ')+$('unmixStatus').textContent;
 }catch(error){if(abundanceRun===run)$('unmixStatus').textContent=`Stopped at ${run.done} pixels: ${error.message}. Partial results can be exported.`;throw error}
 finally{$('cancelUnmix').hidden=true}
});
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
