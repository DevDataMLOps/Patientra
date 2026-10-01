"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const dimensions = {hospital:"Hospital",sex:"Sex",age_band:"Age band",diagnosis_group:"Diagnosis group",discharge_status:"Discharge status",prior_completed_admission_band:"Prior completed admissions",length_of_stay_band:"Length of stay",discharge_year:"Discharge year",discharge_month:"Discharge month"};
  let token = "", data = null, generation = 0, controller = null, busy = false;
  const number = value => Number.isFinite(value) ? value.toLocaleString("en-US") : "Not assessed";
  const percent = value => Number.isFinite(value) ? `${value.toFixed(2)}%` : "Not assessed";
  const date = value => {const d = new Date(value); return Number.isNaN(d.getTime()) ? "Unavailable" : d.toISOString().replace("T"," ");};
  function message(text, error = false) { $("message").textContent = text; $("message").classList.toggle("error",error); }
  function clear() { data = null; $("results").hidden = true; ["rows","pipeline","quality","lineage"].forEach(id => $(id).replaceChildren()); }
  function lock(value) {busy=value; ["connect","refresh"].forEach(id => $(id).disabled=value);}
  function forget() {generation++; controller?.abort(); controller=null; token=""; $("token").value=""; clear(); lock(false); $("connect").hidden=false; $("token").hidden=false; $("disconnect").hidden=true; $("refresh").hidden=true;}
  function list(id, entries) {$(id).replaceChildren(...entries.map(([label,value]) => {const row=document.createElement("div"),dt=document.createElement("dt"),dd=document.createElement("dd"); dt.textContent=label; dd.textContent=value; row.append(dt,dd); return row;}));}
  async function get(path, signal) {
    const response = await fetch(path,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",credentials:"omit",redirect:"error",signal});
    if (!response.ok) {const error=new Error("API unavailable"); error.status=response.status; throw error;}
    return response.json();
  }
  function drawRows() {
    if (!data) return;
    const rows=data.breakdowns.filter(r=>r.dimension===$("dimension").value);
    $("rows").replaceChildren(...rows.map(r=>{const tr=document.createElement("tr"); [r.category,number(r.eligible_admissions),number(r.readmitted_admissions),percent(r.readmission_rate_pct),`${percent(r.wilson_95_lower_pct)} – ${percent(r.wilson_95_upper_pct)}`].forEach(value=>{const td=document.createElement("td");td.textContent=value;tr.append(td);});return tr;}));
    $("empty").hidden=rows.length>0;
    $("breakdown-count").textContent=`${rows.length} released groups in this dimension · ${number(data.quality.suppressed_rows)} suppressed rows across the full release`;
  }
  function render() {
    const {overall:o,status:s,quality:q}=data;
    $("rate").textContent=percent(o.readmission_rate_pct); $("interval").textContent=`95% Wilson interval: ${percent(o.wilson_95_lower_pct)} – ${percent(o.wilson_95_upper_pct)}`;
    $("eligible").textContent=number(o.eligible_admissions); $("excluded").textContent=`${number(q.excluded_rows)} excluded · ${number(q.gold_rows)} Gold records`;
    $("readmitted").textContent=number(o.readmitted_admissions); $("not-readmitted").textContent=`${number(o.not_readmitted_admissions)} not readmitted`;
    $("patients").textContent=number(q.unique_master_patients);
    $("identity").textContent=q.identity_resolution==="not_assessed" ? "Identity-review completion has not been assessed for this release." : `${number(q.unresolved_identity_reviews)} identity reviews remain unresolved in this release. This dashboard cannot resolve patient identities.`;
    $("release").textContent=`TECHNICAL ${s.release_status}`;
    list("pipeline",[["Release validation",`${s.validation_checks_passed} checks passed`],["Current analytics freshness",s.current_freshness],["Freshness at publication",s.freshness_at_publication],["Analytics age",`${(s.current_source_age_seconds/3600).toFixed(1)} hours`],["Published (UTC)",date(s.published_at_utc)]]);
    list("quality",[["Gold row reconciliation",q.row_reconciliation],["Suppression integrity",q.suppression_integrity],["Released / total breakdowns",`${number(q.released_breakdown_rows)} / ${number(q.breakdown_rows)}`],["Suppressed breakdowns",number(q.suppressed_rows)],["Minimum released cell size",number(q.minimum_cell_size)],["Clinical accuracy","Not assessed"]]);
    list("lineage",[["Analytics run (UTC)",date(s.source_run_at_utc)],["Analytics SHA-256",s.analytics_sha256],["Breakdowns SHA-256",s.breakdown_sha256],["Validation gate SHA-256",s.gate_sha256]]);
    $("checked").textContent=`Fetched ${new Date().toLocaleTimeString()}`;
    drawRows(); $("results").hidden=false;
  }
  async function load() {
    if (busy || !token) return;
    const current=++generation; controller=new AbortController(); const signal=controller.signal; const timeout=setTimeout(()=>controller?.abort(),90000);
    clear(); lock(true); message("Loading the approved release… Free hosting may take a minute to wake.");
    try {
      const [overall,status,quality,first]=await Promise.all([get("/api/v1/overall",signal),get("/api/v1/pipeline-status",signal),get("/api/v1/data-quality",signal),get("/api/v1/breakdowns?limit=100&offset=0",signal)]);
      if (!Number.isInteger(first.total) || first.total<0 || first.total>10000) throw new Error("Invalid aggregate page");
      const breakdowns=[...first.items];
      for(let offset=100;offset<first.total;offset+=100){const page=await get(`/api/v1/breakdowns?limit=100&offset=${offset}`,signal);if(page.total!==first.total || page.limit!==100 || page.offset!==offset) throw new Error("Release changed");breakdowns.push(...page.items);}
      const finalStatus=await get("/api/v1/pipeline-status",signal);
      if(["published_at_utc","source_run_at_utc","analytics_sha256","breakdown_sha256","gate_sha256"].some(key=>status[key]!==finalStatus[key])) throw new Error("Release changed");
      if(current!==generation) return;
      if(breakdowns.length!==first.total || first.total!==quality.released_breakdown_rows || overall.eligible_admissions!==quality.eligible_rows || quality.gold_rows!==quality.eligible_rows+quality.excluded_rows || quality.breakdown_rows!==quality.released_breakdown_rows+quality.suppressed_rows || status.validation_checks_passed!==quality.validation_checks_passed) throw new Error("Release changed");
      data={overall,status:finalStatus,quality,breakdowns}; render(); $("token").value=""; $("token").hidden=true; $("connect").hidden=true; $("disconnect").hidden=false; $("refresh").hidden=false;
      message(status.current_freshness==="STALE" ? "Connected. Analytics are STALE; review the run time before interpreting this snapshot." : "Connected to the approved release. Analytics freshness does not measure hospital-record freshness.");
    } catch(error) {
      if(current!==generation) return;
      clear();
      if(error.status===401){forget();message("Authentication failed. Enter the correct bearer token; no data was retained.",true);}
      else message(error.status===429 ? "Request limit reached. Wait at least 60 seconds, then refresh." : error.status===503 ? "Approved snapshot unavailable. No aggregate data is displayed." : "Unable to load a consistent release. Check connectivity and retry; no aggregate data is displayed.",true);
    } finally {clearTimeout(timeout);if(current===generation) lock(false);}
  }
  Object.entries(dimensions).forEach(([value,label])=>{const option=document.createElement("option");option.value=value;option.textContent=label;$("dimension").append(option);});
  $("connect-form").addEventListener("submit",event=>{event.preventDefault();if(busy)return;const entered=$("token").value.trim();if(entered.length<32 || /\s/.test(entered) || !/^[\x21-\x7e]+$/.test(entered)){message("Enter the bearer token without the Bearer prefix.",true);return;}token=entered;load();});
  $("disconnect").addEventListener("click",()=>{forget();message("Disconnected. Token and displayed data cleared.");});
  $("refresh").addEventListener("click",load);
  $("dimension").addEventListener("change",drawRows);
  window.addEventListener("pagehide",forget);
})();
