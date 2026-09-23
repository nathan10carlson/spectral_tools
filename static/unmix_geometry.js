'use strict';
const UnmixGeometry={
 point(view,rect,clientX,clientY){return{x:view.centerX+(clientX-rect.left-rect.width/2)/view.zoom,y:view.centerY+(clientY-rect.top-rect.height/2)/view.zoom}},
 rectangle(a,b,m){
  const left=Math.min(a.x,b.x),right=Math.max(a.x,b.x),top=Math.min(a.y,b.y),bottom=Math.max(a.y,b.y);
  if((right<=0&&left<0)||(bottom<=0&&top<0)||left>=m.cols||top>=m.rows)return null;
  return{row_start:Math.max(0,Math.min(m.rows-1,Math.floor(top))),column_start:Math.max(0,Math.min(m.cols-1,Math.floor(left))),row_end:Math.max(0,Math.min(m.rows-1,Math.max(Math.floor(top),Math.ceil(bottom)-1))),column_end:Math.max(0,Math.min(m.cols-1,Math.max(Math.floor(left),Math.ceil(right)-1)))};
 },
 zoom(view,f,rect,clientX,clientY){
  const next={...view,zoom:Math.min(128,Math.max(.00001,view.zoom*f))};
  if(rect){const before=this.point(view,rect,clientX,clientY),after=this.point(next,rect,clientX,clientY);next.centerX+=before.x-after.x;next.centerY+=before.y-after.y}
  return next;
 }
};
if(typeof module!=='undefined')module.exports=UnmixGeometry;
