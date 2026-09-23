'use strict';
let regionRequest=0;
async function previewRegion(start,end){
 const version=S.meta.version,request=++regionRequest;
 const x0=(Math.min(start.x,end.x)-S.ox)/S.z,x1=(Math.max(start.x,end.x)-S.ox)/S.z,y0=(Math.min(start.y,end.y)-S.oy)/S.z,y1=(Math.max(start.y,end.y)-S.oy)/S.z;
 if(x1<=0||y1<=0||x0>=S.meta.cols||y0>=S.meta.rows)return toast('Draw the region inside the image.',true);
 const bounds={row_start:Math.max(0,Math.floor(y0)),column_start:Math.max(0,Math.floor(x0)),row_end:Math.min(S.meta.rows-1,Math.ceil(y1)-1),column_end:Math.min(S.meta.cols-1,Math.ceil(x1)-1)};
 toast('Calculating region average…');
 try{
  const result=await api('region/average',{bounds,version});if(request!==regionRequest||version!==S.meta.version)return;
  modal('Region average',`<p>${result.pixel_count.toLocaleString()} pixels · rows ${bounds.row_start}–${bounds.row_end}, columns ${bounds.column_start}–${bounds.column_end}</p><div id="regionAverageChart" class="chart" data-height="250"></div><p class="micro">Mean with ±1 sample standard deviation across valid pixels at each band. This shows spatial variability, not uncertainty in the mean. Missing pixels are excluded per band; original band centers are retained.</p><details><summary>Valid pixels per band</summary><div class="region-counts">${result.wavelengths.map((w,i)=>`<span>${w.toFixed(1)} nm <b>${result.valid_counts[i]}</b></span>`).join('')}</div></details><div class="pair"><button id="saveRegionAverage" class="button violet">Name and save average</button><button id="referenceRegionAverage" class="button">Set as reference</button></div>`);
  chart('regionAverageChart',[{...result,color:'#ac89ff',bold:true},...[-1,1].map(sign=>({...result,name:sign<0?'Mean − SD':'Mean + SD',color:'#8498bd',dash:true,values:result.values.map((v,i)=>v===null||result.standard_deviation[i]===null?null:v+sign*result.standard_deviation[i])}))]);
  $('saveRegionAverage').onclick=()=>{$('modal').close();saveDialog(result)};
  $('referenceRegionAverage').onclick=()=>{S.pixelRequest++;S.reference=structuredClone(result);S.pixel=S.reference;S.comparison=null;S.selectionPurpose=null;invalidateFit();clearSceneMatches();renderSceneSelection();renderExploreChart();$('toolinspect').click();$('modal').close();toast('Region mean set as reference. Run Find matches when ready.')};
 }catch(e){if(request===regionRequest)toast(e.message,true)}
}
