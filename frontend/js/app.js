const map=L.map('map').setView([-7.25,112.75],11);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles © Esri — Source: Esri, DeLorme, NAVTEQ, USGS, and other contributors'}).addTo(map);
map.pm.addControls({position:'topleft',drawPolygon:true,drawRectangle:true,drawCircle:false,drawMarker:false,drawCircleMarker:false,drawPolyline:false,editMode:true,dragMode:false,cutPolygon:false,removalMode:true});
let aoiLayer=null,aoiGeometry=null,resultLayer=null,lastRequest=null,chartInstance=null,aoiVisible=true,resultVisible=true;
const $=id=>document.getElementById(id);
const cfg={SO2:{name:'Sulfur Dioxide (SO2)',unit:'µg/m³'},NO2:{name:'Nitrogen Dioxide (NO2)',unit:'µg/m³'},CO:{name:'Carbon Monoxide (CO)',unit:'µg/m³'},CH4:{name:'Methane (CH4)',unit:'ppm'}};
function errorMessage(detail,fallback='Request failed'){
  if(detail instanceof Error&&detail.message)return detail.message;
  if(typeof detail==='string'&&detail.trim())return detail;
  if(detail&&typeof detail==='object'){
    if(typeof detail.message==='string'&&detail.message.trim())return detail.message;
    if(typeof detail.error==='string'&&detail.error.trim())return detail.error;
    if(detail.error&&typeof detail.error==='object'&&typeof detail.error.message==='string')return detail.error.message;
    try{return JSON.stringify(detail)}catch(_){return fallback}
  }
  return fallback;
}
async function responseError(r,fallback){let d=null;try{d=await r.json()}catch(_){ }return new Error(errorMessage(d?.detail??d,`${fallback} (HTTP ${r.status})`));}
function setAOI(geometry,zoom=true){
  if(!geometry||!['Polygon','MultiPolygon'].includes(geometry.type))throw new Error('AOI must be a Polygon or MultiPolygon.');
  if(aoiLayer)map.removeLayer(aoiLayer);
  aoiGeometry=geometry;
  aoiVisible=true;
  aoiLayer=L.geoJSON({type:'Feature',properties:{},geometry},{style:{color:'#1687ff',weight:3,fillOpacity:.12}}).addTo(map);
  if(zoom)map.fitBounds(aoiLayer.getBounds(),{padding:[30,30]});
  $('toggle-aoi').textContent='HIDE AOI';
  $('toggle-aoi').disabled=false;
  $('status').textContent='AOI ready. Click RUN ANALYSIS.';
}
map.on('pm:create',e=>{try{setAOI(e.layer.toGeoJSON().geometry)}catch(err){$('status').textContent=errorMessage(err.message,'Invalid AOI.')}});
function requestBody(){
  if(!aoiGeometry)throw new Error('Please draw an AOI or upload one first.');
  return {module:$('module').value,variable:$('variable').value,aoi:aoiGeometry,start_date:$('start').value,end_date:$('end').value,aggregation:$('aggregation').value,interval:$('interval').value};
}
function validateDates(){const start=$('start').value,end=$('end').value;if(!start||!end)return'Start and end dates are required.';if(end<start)return'End date must be on or after start date.';const diff=(new Date(end)-new Date(start))/86400000;if(diff>=366)return'Maximum analysis period is 365 days. Please select a shorter period.';return null}
function openChart(){$('chart-panel').hidden=false}
function closeChart(){$('chart-panel').hidden=true}
function drawChart(series){
  openChart();
  const v=lastRequest.variable,c=cfg[v],labels=series.map(x=>x.date),values=series.map(x=>x.value);
  $('chart-title').textContent=`${c.name} time series`;$('chart-subtitle').textContent=`${$('aggregation').selectedOptions[0].text} over selected AOI · ${c.unit}`;$('chart-empty').hidden=values.length>0;$('chart-period').textContent=`${lastRequest.start_date} → ${lastRequest.end_date}`;$('chart-method').textContent=`${$('aggregation').selectedOptions[0].text} · ${$('interval').selectedOptions[0].text}`;
  if(chartInstance)chartInstance.destroy();
  if(!values.length){$('chart-empty').textContent='No time-series data available for the selected period.';return;}
  chartInstance=new Chart($('timeseries-chart'),{type:'line',data:{labels,datasets:[{label:`${v} (${c.unit})`,data:values,tension:.25,pointRadius:2.5,pointHoverRadius:5,borderWidth:2,fill:true,backgroundColor:'rgba(45,126,247,.16)',borderColor:'#58a6ff'}]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:'#d9e4f3'}},tooltip:{callbacks:{label:x=>` ${Number(x.raw).toExponential(4)} ${c.unit}`}}},scales:{x:{ticks:{color:'#8fa2bc',maxRotation:0},grid:{color:'rgba(255,255,255,.07)'}},y:{ticks:{color:'#8fa2bc',callback:x=>Number(x).toExponential(2)},grid:{color:'rgba(255,255,255,.07)'}}}}});
}
async function loadChart(){
  if(!lastRequest)return;
  openChart();$('chart-empty').textContent='Loading time-series data…';$('chart-empty').hidden=false;
  try{const r=await fetch('/api/chart',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(lastRequest)});if(!r.ok)throw await responseError(r,'Time series failed');const d=await r.json();drawChart(d.series||[])}
  catch(e){$('chart-empty').textContent=errorMessage(e,'Time series failed');$('chart-empty').hidden=false}
}
$('run').onclick=async()=>{
  if(!aoiGeometry){$('status').textContent='Please draw an AOI or upload one first.';return}
  const validation=validateDates();if(validation){$('status').textContent=validation;return}
  let body;try{body=requestBody()}catch(err){$('status').textContent=errorMessage(err,'Invalid request');return}
  lastRequest=body;const c=cfg[body.variable];$('status').textContent=`Processing Sentinel-5P ${body.variable} in Google Earth Engine…`;$('run').disabled=true;
  try{const r=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw await responseError(r,'Analysis failed');const data=await r.json();$('value').textContent=Number(data.value).toExponential(4);$('unit').textContent=data.unit;$('images').textContent=data.image_count;$('dates').textContent=`${data.start_date} → ${data.end_date}`;$('note').textContent=data.note;$('severity').textContent=data.interpretation?.label||'Relative';$('results').hidden=false;if(resultLayer)map.removeLayer(resultLayer);if(data.map?.tile_url)resultLayer=L.tileLayer(data.map.tile_url,{opacity:.65}).addTo(map);resultVisible=true;$('toggle-result').textContent='HIDE ANALYSIS';$('toggle-result').disabled=!resultLayer;$('status').textContent='Analysis complete. Time series loaded below.';await loadChart()}
  catch(err){$('status').textContent=errorMessage(err,'Analysis failed')}
  finally{$('run').disabled=false}
};
$('variable').addEventListener('change',()=>{if(lastRequest&&lastRequest.variable!==$('variable').value){$('results').hidden=true;closeChart();lastRequest=null;if(resultLayer){map.removeLayer(resultLayer);resultLayer=null}$('toggle-result').disabled=true}});
$('open-chart').onclick=()=>loadChart();$('chart-close').onclick=closeChart;
$('toggle-aoi').onclick=()=>{if(!aoiLayer)return;if(aoiVisible){map.removeLayer(aoiLayer);aoiVisible=false;$('toggle-aoi').textContent='SHOW AOI'}else{aoiLayer.addTo(map);aoiVisible=true;$('toggle-aoi').textContent='HIDE AOI'}};
$('toggle-result').onclick=()=>{if(!resultLayer)return;if(resultVisible){map.removeLayer(resultLayer);resultVisible=false;$('toggle-result').textContent='SHOW ANALYSIS'}else{resultLayer.addTo(map);resultVisible=true;$('toggle-result').textContent='HIDE ANALYSIS'}};
$('download-tif').onclick=async()=>{if(!lastRequest){$('status').textContent='Run an analysis first.';return}$('status').textContent='Preparing GeoTIFF export…';$('download-tif').disabled=true;try{const r=await fetch('/api/export/geotiff/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(lastRequest)});if(!r.ok)throw await responseError(r,'GeoTIFF export failed');const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${lastRequest.variable}_${lastRequest.start_date}_${lastRequest.end_date}.tif`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);$('status').textContent='GeoTIFF downloaded.'}catch(e){$('status').textContent=errorMessage(e,'GeoTIFF export failed')}finally{$('download-tif').disabled=false}};
$('download-pdf').onclick=async()=>{if(!lastRequest){$('status').textContent='Run an analysis first.';return}$('status').textContent='Generating PDF report with map and chart…';$('download-pdf').disabled=true;try{const r=await fetch('/api/report/pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(lastRequest)});if(!r.ok)throw await responseError(r,'PDF generation failed');const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${lastRequest.variable}_report_${lastRequest.start_date}_${lastRequest.end_date}.pdf`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);$('status').textContent='PDF report downloaded.'}catch(e){$('status').textContent=errorMessage(e,'PDF generation failed')}finally{$('download-pdf').disabled=false}};
$('clear').onclick=()=>{if(aoiLayer)map.removeLayer(aoiLayer);if(resultLayer)map.removeLayer(resultLayer);aoiLayer=null;aoiGeometry=null;resultLayer=null;lastRequest=null;aoiVisible=true;resultVisible=true;$('results').hidden=true;closeChart();if(chartInstance){chartInstance.destroy();chartInstance=null}$('upload-status').textContent='';$('toggle-aoi').disabled=true;$('toggle-aoi').textContent='SHOW AOI';$('toggle-result').disabled=true;$('toggle-result').textContent='SHOW ANALYSIS';$('status').textContent='Draw an AOI or upload a Shapefile ZIP.'};
$('aoi-file').addEventListener('change',async e=>{const file=e.target.files?.[0];if(!file)return;$('upload-status').textContent='Uploading and reading AOI…';$('status').textContent='Reading AOI file…';const form=new FormData();form.append('file',file);try{const r=await fetch('/api/upload/aoi',{method:'POST',body:form});if(!r.ok)throw await responseError(r,'AOI upload failed');const d=await r.json();setAOI(d.geometry);$('upload-status').textContent=`Loaded ${d.feature_count||1} polygon feature(s)${d.source_epsg?` · EPSG:${d.source_epsg}`:''}.`}catch(err){const msg=errorMessage(err,'AOI upload failed');$('upload-status').textContent=msg;$('status').textContent=msg}finally{e.target.value=''}});
const infoToggle=$('info-toggle'),infoPanel=$('info-panel'),infoClose=$('info-close');function setInfo(open){infoPanel.hidden=!open;infoToggle.setAttribute('aria-expanded',String(open))}infoToggle.addEventListener('click',()=>setInfo(infoPanel.hidden));infoClose.addEventListener('click',()=>setInfo(false));
const welcome=$('welcome-modal');function closeWelcome(){welcome.classList.add('is-hidden')}$('welcome-close').onclick=closeWelcome;$('start-app').onclick=closeWelcome;document.addEventListener('keydown',e=>{if(e.key==='Escape'){setInfo(false);closeChart();closeWelcome()}});
