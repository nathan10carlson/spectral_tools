'use strict';
// Both views share a center in source pixels and one CSS-pixels-per-image-pixel scale.
const V={centerX:0,centerY:0,zoom:1,mode:'pan',selection:null,cursor:null,drag:null,image:null,imageRequest:0,palette:'false',exporting:false,boundsDirty:false};
const viewer=document.createElement('dialog');viewer.id='unmixViewer';viewer.setAttribute('aria-labelledby','viewerTitle');
viewer.innerHTML=`<div class="modal-head"><div><h2 id="viewerTitle">Linked scene comparison</h2><p class="micro">Pan or zoom either image. Both views stay on the same pixels.</p></div><button id="closeUnmixViewer" aria-label="Close comparison viewer">×</button></div>
<div class="viewer-toolbar"><div class="segmented"><button id="viewerPan" class="active">Pan</button><button id="viewerRectangle">Select rectangle</button></div><button id="viewerFit" class="button">Fit both</button><button id="viewerZoomOut" class="button" aria-label="Zoom both views out">−</button><button id="viewerZoomIn" class="button" aria-label="Zoom both views in">+</button><span id="viewerZoom" class="micro"></span><label>Original image<select id="viewerPalette"><option value="false">False color</option><option value="true">True color</option></select></label><label>Material channel<select id="viewerChannel"></select></label><label>Display maximum<input id="viewerMaximum" type="number" min=".000001" step=".1" value="1"></label></div>
<div class="linked-panes"><section><h3>Original image</h3><canvas id="linkedOriginal" aria-label="Linked original image. Drag to pan or select a rectangle." tabindex="0"></canvas></section><section><h3 id="linkedMaterialTitle">Material abundance</h3><canvas id="linkedAbundance" aria-label="Linked abundance image. Drag to pan or select a rectangle." tabindex="0"></canvas></section></div>
<div class="viewer-legend"><span>Abundance</span><span>0</span><i></i><span id="viewerScale">1</span><span>Gray = unavailable · above maximum = saturated</span></div>
<p id="viewerReadout" class="reference-info">Hover over either image for linked pixel values.</p>
<div class="viewer-export"><div><h3>Save a rectangle</h3><p id="viewerSelection" class="micro">Choose Select rectangle and drag in either image. Bounds include both endpoints.</p><div class="rectangle-fields"><label>First row<input id="cropRow0" type="number" min="0" value="0"></label><label>Last row<input id="cropRow1" type="number" min="0" value="0"></label><label>First column<input id="cropCol0" type="number" min="0" value="0"></label><label>Last column<input id="cropCol1" type="number" min="0" value="0"></label><button id="applyCropBounds" class="button">Apply bounds</button></div></div><div class="export-actions"><button id="clearCrop" class="button">Clear rectangle</button><button id="exportCrop" class="button violet" disabled>Save images + abundances + spectra</button><p id="cropExportStatus" class="micro" role="status">Downloads one ZIP with PNG images, two CSVs, and analysis metadata.</p></div></div>`;
document.body.append(viewer);
const linkedCanvases=[$('linkedOriginal'),$('linkedAbundance')];
function closeUnmixViewer(){V.imageRequest++;V.selection=null;V.cursor=null;V.drag=null;if(viewer.open)viewer.close()}
$('closeUnmixViewer').onclick=closeUnmixViewer;
viewer.addEventListener('cancel',()=>{V.drag=null});
function openUnmixViewer(){
 if(!abundanceRun)return toast('Run scene unmixing first.',true);
 $('viewerChannel').innerHTML=$('abundanceChannel').innerHTML;$('viewerChannel').value=$('abundanceChannel').value;
 $('viewerMaximum').value=$('abundanceMaximum').value;V.palette=S.palette;$('viewerPalette').value=V.palette;
 for(const id of ['cropRow0','cropRow1'])$(id).max=abundanceRun.meta.rows-1;
 for(const id of ['cropCol0','cropCol1'])$(id).max=abundanceRun.meta.cols-1;
 viewer.showModal();fitLinkedViews();loadLinkedOriginal();renderCropSelection();
}
$('openUnmixViewer').onclick=openUnmixViewer;
function loadLinkedOriginal(){
 const request=++V.imageRequest,img=new Image();V.image=null;
 img.onload=()=>{if(request!==V.imageRequest)return;V.image=img;drawLinkedViews()};
 img.onerror=()=>{if(request===V.imageRequest)$('viewerReadout').textContent='Original preview could not be loaded. Try switching its palette.'};
 img.src='/api/rgb?palette='+V.palette+'&v='+abundanceRun.meta.version;drawLinkedViews();
}
function fitLinkedViews(){
 if(!abundanceRun)return;const rect=linkedCanvases[0].getBoundingClientRect(),m=abundanceRun.meta;
 V.centerX=m.cols/2;V.centerY=m.rows/2;V.zoom=Math.min(128,Math.min(rect.width/m.cols,rect.height/m.rows)*.94);drawLinkedViews();
}
function sourcePoint(canvas,e){return UnmixGeometry.point(V,canvas.getBoundingClientRect(),e.clientX,e.clientY)}
function drawLinkedViews(){
 if(!viewer.open||!abundanceRun)return;const m=abundanceRun.meta;
 $('viewerChannel').value=$('abundanceChannel').value;$('viewerMaximum').value=$('abundanceMaximum').value;
 const name=abundanceRun.materials[Number($('abundanceChannel').value)].name;
 $('linkedMaterialTitle').textContent=name+' · abundance';$('linkedMaterialTitle').title=name;$('viewerScale').textContent=Number($('abundanceMaximum').value).toPrecision(4);$('viewerZoom').textContent=Math.round(V.zoom*100)+'%';
 for(const [i,canvas] of linkedCanvases.entries()){
  const [w,h]=resizeCanvas(canvas),c=canvas.getContext('2d'),x=w/2-V.centerX*V.zoom,y=h/2-V.centerY*V.zoom;
  c.fillStyle='#090f19';c.fillRect(0,0,w,h);c.imageSmoothingEnabled=false;
  const source=i?$('abundanceCanvas'):V.image;if(source)c.drawImage(source,x,y,m.cols*V.zoom,m.rows*V.zoom);
  else{c.fillStyle='#a5b1c2';c.fillText('Loading original image…',20,30)}
  const box=V.selection;if(box){c.fillStyle='#ac89ff25';c.strokeStyle='#d8c3ff';c.lineWidth=2;const bx=x+box.column_start*V.zoom,by=y+box.row_start*V.zoom,bw=(box.column_end-box.column_start+1)*V.zoom,bh=(box.row_end-box.row_start+1)*V.zoom;c.fillRect(bx,by,bw,bh);c.strokeRect(bx,by,bw,bh)}
  if(V.cursor){const px=x+(V.cursor.column+.5)*V.zoom,py=y+(V.cursor.row+.5)*V.zoom;c.strokeStyle='#ffffff';c.lineWidth=1;c.beginPath();c.moveTo(px-9,py);c.lineTo(px+9,py);c.moveTo(px,py-9);c.lineTo(px,py+9);c.stroke()}
 }
}
function rectangleFromPoints(a,b,m){return UnmixGeometry.rectangle(a,b,m)}
function zoomLinked(f,canvas=null,e=null){
 const next=UnmixGeometry.zoom(V,f,canvas?.getBoundingClientRect(),e?.clientX,e?.clientY);
 V.zoom=next.zoom;V.centerX=next.centerX;V.centerY=next.centerY;drawLinkedViews();
}

for(const canvas of linkedCanvases){
 canvas.onwheel=e=>{e.preventDefault();zoomLinked(Math.exp(-e.deltaY*.002),canvas,e)};
 canvas.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();canvas.focus();canvas.setPointerCapture(e.pointerId);V.drag={canvas,start:sourcePoint(canvas,e),clientX:e.clientX,clientY:e.clientY,centerX:V.centerX,centerY:V.centerY,pan:V.mode==='pan'||e.shiftKey};};
 canvas.onpointermove=e=>{
  if(!abundanceRun)return;const d=V.drag;
  if(d&&d.canvas===canvas){if(d.pan){V.centerX=d.centerX-(e.clientX-d.clientX)/V.zoom;V.centerY=d.centerY-(e.clientY-d.clientY)/V.zoom}else{V.selection=rectangleFromPoints(d.start,sourcePoint(canvas,e),abundanceRun.meta);renderCropSelection()}}
  const p=sourcePoint(canvas,e),row=Math.floor(p.y),column=Math.floor(p.x),m=abundanceRun.meta;
  if(row>=0&&column>=0&&row<m.rows&&column<m.cols){V.cursor={row,column};readAbundance(row,column);$('viewerReadout').textContent=$('abundanceReadout').textContent}else V.cursor=null;
  drawLinkedViews();
 };
 canvas.onpointerup=e=>{const d=V.drag;if(!d||d.canvas!==canvas)return;if(!d.pan){V.selection=rectangleFromPoints(d.start,sourcePoint(canvas,e),abundanceRun.meta);renderCropSelection()}V.drag=null;drawLinkedViews()};
 canvas.onpointercancel=()=>{V.drag=null};canvas.onlostpointercapture=()=>{V.drag=null};
 canvas.onkeydown=e=>{const moves={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};if(moves[e.key]){e.preventDefault();V.centerX+=moves[e.key][0]*40/V.zoom;V.centerY+=moves[e.key][1]*40/V.zoom;drawLinkedViews()}else if(e.key==='+'||e.key==='=')zoomLinked(1.25);else if(e.key==='-')zoomLinked(.8)};
}
for(const [id,mode] of [['viewerPan','pan'],['viewerRectangle','rectangle']])$(id).onclick=()=>{V.mode=mode;V.drag=null;$('viewerPan').classList.toggle('active',mode==='pan');$('viewerRectangle').classList.toggle('active',mode==='rectangle');linkedCanvases.forEach(c=>c.style.cursor=mode==='pan'?'grab':'crosshair')};
$('viewerFit').onclick=fitLinkedViews;$('viewerZoomIn').onclick=()=>zoomLinked(1.25);$('viewerZoomOut').onclick=()=>zoomLinked(.8);
$('viewerChannel').onchange=()=>{$('abundanceChannel').value=$('viewerChannel').value;$('abundanceChannel').onchange();if(V.cursor){readAbundance(V.cursor.row,V.cursor.column);$('viewerReadout').textContent=$('abundanceReadout').textContent}};
$('viewerMaximum').oninput=()=>{const value=Number($('viewerMaximum').value);if(Number.isFinite(value)&&value>0){$('abundanceMaximum').value=value;drawAbundances()}};
$('viewerPalette').onchange=()=>{V.palette=$('viewerPalette').value;loadLinkedOriginal()};
$('clearCrop').onclick=()=>{V.selection=null;renderCropSelection();drawLinkedViews()};
for(const id of ['cropRow0','cropRow1','cropCol0','cropCol1'])$(id).oninput=()=>{V.boundsDirty=true;$('exportCrop').disabled=true;$('viewerSelection').textContent='Apply the edited bounds to update the rectangle before exporting.'};
$('applyCropBounds').onclick=()=>{
 if(!abundanceRun)return;const b={row_start:Number($('cropRow0').value),row_end:Number($('cropRow1').value),column_start:Number($('cropCol0').value),column_end:Number($('cropCol1').value)},m=abundanceRun.meta;
 if(['cropRow0','cropRow1','cropCol0','cropCol1'].some(id=>$(id).value==='')||Object.values(b).some(v=>!Number.isInteger(v))||b.row_start<0||b.column_start<0||b.row_end<b.row_start||b.column_end<b.column_start||b.row_end>=m.rows||b.column_end>=m.cols){V.selection=null;renderCropSelection();drawLinkedViews();$('viewerSelection').textContent='Enter increasing, zero-based bounds within the image.';return}
 V.selection=b;renderCropSelection();drawLinkedViews();
};
function renderCropSelection(){
 V.boundsDirty=false;const b=V.selection,run=abundanceRun;$('exportCrop').disabled=!b||V.exporting;
 if(!b||!run){$('viewerSelection').textContent='Choose Select rectangle and drag in either image. Bounds include both endpoints.';return}
 for(const [id,k] of [['cropRow0','row_start'],['cropRow1','row_end'],['cropCol0','column_start'],['cropCol1','column_end']])$(id).value=b[k];
 const n=(b.row_end-b.row_start+1)*(b.column_end-b.column_start+1),samples=n*run.meta.bands,estimate=(samples*65+n*(run.materials.length*22+140))/1048576;
 $('viewerSelection').textContent=`${b.column_end-b.column_start+1} × ${b.row_end-b.row_start+1} pixels · ${n.toLocaleString()} pixels · ${samples.toLocaleString()} spectral samples · approximately ${estimate.toFixed(1)} MB before ZIP compression. Original coordinates are preserved.`;
 if(samples>5000000){$('exportCrop').disabled=true;$('viewerSelection').textContent+=' Select a smaller area: maximum 5 million spectral samples per export.'}
}
$('exportCrop').onclick=async()=>{
 if(!abundanceRun||!V.selection||V.exporting||V.boundsDirty)return;
 const run=abundanceRun,b={...V.selection},pixels=[];
 for(let r=b.row_start;r<=b.row_end;r++)for(let c=b.column_start;c<=b.column_end;c++)pixels.push(run.pixels[r*run.meta.cols+c]||{row:r,column:c,status:'unprocessed',coefficients:null});
 const payload={run_started_utc:run.startedAt,version:run.meta.version,bounds:b,pixels,materials:run.materials,settings:run.settings,processing:{accuracy:run.accuracy,device:run.actual_device},retry:run.retry,channel:Number($('abundanceChannel').value),maximum:Number($('abundanceMaximum').value),palette:V.palette};
 const body=JSON.stringify(payload);if(new Blob([body]).size>20000000){$('cropExportStatus').textContent='The abundance data exceeds the 20 MB request limit. Select a smaller rectangle.';return}
 V.exporting=true;renderCropSelection();$('cropExportStatus').textContent='Preparing images, measured spectra, and abundance results…';
 try{
  const response=await fetch('/api/region/export',{method:'POST',headers:{'Content-Type':'application/json'},body});
  if(!response.ok){const data=await response.json();throw Error(data.error||'Export failed')}
  const blob=await response.blob();download(`HELMET-rows-${b.row_start}-${b.row_end}-cols-${b.column_start}-${b.column_end}.zip`,blob,'application/zip');
  $('cropExportStatus').textContent='Saved ZIP: original.png, abundance.png, abundances.csv, spectra.csv, analysis.json.';
 }catch(e){$('cropExportStatus').textContent=e.message}
 finally{V.exporting=false;renderCropSelection()}
};
new ResizeObserver(()=>{if(viewer.open)drawLinkedViews()}).observe($('linkedOriginal'));

// Reuse the linked source-coordinate rectangle tool for a preflight ROI.
const usePreview=Object.assign(document.createElement('button'),{id:'usePreviewBounds',className:'button',textContent:'Use rectangle for region preview'});
$('clearCrop').before(usePreview);
usePreview.onclick=()=>{if(!V.selection||V.boundsDirty){$('cropExportStatus').textContent='Select a valid rectangle first.';return}for(const [id,k] of [['previewRow0','row_start'],['previewRow1','row_end'],['previewCol0','column_start'],['previewCol1','column_end']])$(id).value=V.selection[k];closeUnmixViewer();document.querySelector('.preview-controls').open=true;$('runUnmixPreview').scrollIntoView({block:'center',behavior:'smooth'})};
$('pickPreviewRegion').onclick=()=>{
 if(!S.meta)return toast('Open a dataset first.',true);
 if(!abundanceRun){const materials=[...S.selected].map(entry).filter(Boolean);if(!materials.length)return toast('Select candidates first.',true);renderRun({meta:{...S.meta},materials,settings:fitSettings(),accuracy:$('unmixAccuracy').value,key:unmixKey(),pixels:new Array(S.meta.rows*S.meta.cols),preview:true,selectionOnly:true,cancelled:false})}
 openUnmixViewer();$('viewerRectangle').click();
};
