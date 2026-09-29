"use strict";
const $ = id => document.getElementById(id);
let currentReport = null;
let requestNumber = 0;
const dollars = n => n == null ? "—" : new Intl.NumberFormat("en-US", {style:"currency", currency:"USD", maximumFractionDigits:2}).format(n);
const number = n => new Intl.NumberFormat("en-US").format(n);
const multiple = n => n == null ? "—" : n.toFixed(2) + "x";
async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}
function svg(tag, attrs, text) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key,value] of Object.entries(attrs)) element.setAttribute(key, String(value));
  if (text != null) element.textContent = text;
  return element;
}
function chart(days) {
  const target = $("trend"); target.replaceChildren();
  $("chart-empty").hidden = days.length > 0;
  if (!days.length) return;
  const max = Math.max(1, ...days.flatMap(d => [d.net_revenue, d.spend])) * 1.15;
  const first = Date.parse(days[0].date), last = Date.parse(days.at(-1).date);
  const x = d => first === last ? 385 : 55 + (Date.parse(d.date)-first)/(last-first)*635;
  const y = value => 205-value/max*175;
  for (let i=0;i<=4;i++) {
    const value = max*i/4;
    target.append(svg("line", {x1:55,x2:700,y1:y(value),y2:y(value),stroke:"#e9eeeb"}));
    target.append(svg("text", {x:45,y:y(value)+4,"text-anchor":"end"}, "$"+Math.round(value).toLocaleString()));
  }
  for (const [key,color] of [["net_revenue","#26846d"],["spend","#d8a85d"]]) {
    target.append(svg("polyline", {points:days.map(d=>x(d)+","+y(d[key])).join(" "),fill:"none",stroke:color,"stroke-width":2.5}));
    for (const d of days) {
      const dot=svg("circle",{cx:x(d),cy:y(d[key]),r:3,fill:color});
      dot.append(svg("title",{},d.date+" · "+key+": "+dollars(d[key]))); target.append(dot);
    }
  }
  const step=Math.max(1,Math.ceil(days.length/6));
  days.forEach((d,i)=>{if(i%step===0 || i===days.length-1) target.append(svg("text",{x:x(d),y:233,"text-anchor":"middle"},d.date.slice(5)));});
}
function render(data) {
  currentReport=data;
  $("start").value=data.filters.start; $("end").value=data.filters.end;
  const s=data.summary;
  $("revenue").textContent=dollars(s.net_revenue); $("spend").textContent=dollars(s.spend);
  $("roas").textContent=multiple(s.roas); $("orders").textContent=number(s.orders);
  $("aov").textContent="Average order value "+dollars(s.aov);
  $("ctr").textContent=s.ctr==null?"—":s.ctr.toFixed(2)+"%";
  $("cpc").textContent=dollars(s.cpc); $("cpa").textContent=dollars(s.cpa);
  chart(data.daily);
  const channels = new Map();
  for(const c of data.campaigns) channels.set(c.channel,(channels.get(c.channel)||0)+c.net_revenue);
  $("channels").replaceChildren();
  for(const [channel,revenue] of [...channels].sort((a,b)=>b[1]-a[1])) {
    const row=document.createElement("div"); row.className="channel-row";
    const label=document.createElement("div"); label.className="channel-label";
    const name=document.createElement("span"); name.textContent=channel;
    const share=s.net_revenue?revenue/s.net_revenue*100:0;
    const value=document.createElement("span"); value.textContent=dollars(revenue)+" · "+share.toFixed(1)+"%";
    label.append(name,value);
    const bar=svg("svg",{viewBox:"0 0 100 4",preserveAspectRatio:"none","aria-hidden":"true"});
    bar.append(svg("rect",{width:100,height:4,rx:2,fill:"#edf3ee"}),svg("rect",{width:share,height:4,rx:2,fill:"#4b9277"}));
    row.append(label,bar); $("channels").append(row);
  }
  $("campaign-count").textContent=data.campaigns.length+" campaigns";
  $("campaign-rows").replaceChildren();
  for(const c of data.campaigns) {
    const row=document.createElement("tr");
    for(const text of [c.campaign,c.channel,dollars(c.net_revenue),dollars(c.spend),multiple(c.roas),number(c.orders),number(c.conversions)]) {
      const cell=document.createElement("td"); cell.textContent=text; row.append(cell);
    }
    $("campaign-rows").append(row);
  }
  $("insights").replaceChildren();
  for(const text of data.insights) {const p=document.createElement("p");p.className="insight";p.textContent=text;$("insights").append(p);}
  $("quality-counts").replaceChildren();
  const last=data.imports[0];
  if(last) for(const [key,label] of [["accepted","Accepted"],["duplicates","Duplicates"],["rejected","Rejected"],["normalized","Normalized*"]]) {
    const item=document.createElement("div"), value=document.createElement("strong"), name=document.createElement("span");
    value.textContent=number(last[key]);name.textContent=label;item.append(value,name);$("quality-counts").append(item);
  }
  $("issues").replaceChildren();
  for(const issue of data.issues) {const li=document.createElement("li");li.textContent=issue.dataset+" line "+issue.line+": "+issue.reason;$("issues").append(li);}
  $("quality-note").textContent=last?"Import #"+last.id+" · "+new Date(last.created_at).toLocaleString()+". First 50 issues shown. *Normalization is an overlapping count, not an additional row outcome.":"No imports yet.";
}
async function load(reset=false) {
  const sequence=++requestNumber;
  $("error").textContent="";
  const query=new URLSearchParams({channel:$("channel").value});
  if(!reset && $("start").value) query.set("start",$("start").value);
  if(!reset && $("end").value) query.set("end",$("end").value);
  try {const data=await api("/api/report?"+query);if(sequence===requestNumber) render(data);}
  catch(e) {if(sequence===requestNumber) $("error").textContent=e.message;}
}
$("filters").onsubmit=e=>{e.preventDefault();load();};
$("import-form").onsubmit=async e=>{
  e.preventDefault();$("import-button").disabled=true;$("import-result").textContent="Validating…";
  try {
    const sales=$("sales-file").files[0],ads=$("ads-file").files[0];
    if(!sales&&!ads) throw new Error("Choose at least one CSV file.");
    if((sales?.size||0)+(ads?.size||0)>1500000) throw new Error("Choose files under 1.5 MB combined.");
    const result=await api("/api/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sales_csv:sales?await sales.text():"",ads_csv:ads?await ads.text():""})});
    $("import-result").textContent=result.accepted+" accepted · "+result.duplicates+" duplicates · "+result.rejected+" rejected";
    await load(true);
  }catch(e){$("import-result").textContent=e.message;}
  finally{$("import-button").disabled=false;}
};
$("export").onclick=()=>{
  if(!currentReport) return;
  window.location.assign("/api/export?"+new URLSearchParams(currentReport.filters));
};
load(true);
