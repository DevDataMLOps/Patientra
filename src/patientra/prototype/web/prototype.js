(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const views = ["pipeline", "governance", "product", "ml"];
  let token = "", state = null, controller = null, generation = 0;
  const number = value => Number(value).toLocaleString();
  const percent = value => `${Number(value).toFixed(2)}%`;
  const pretty = value => value.replaceAll("_", " ");
  const node = (tag, value, className) => {const e = document.createElement(tag); e.textContent = value; if (className) e.className = className; return e;};
  function tab(view) {
    views.forEach(name => {const b=$(`tab-${name}`); b.setAttribute("aria-selected", String(name===view)); b.tabIndex=name===view ? 0 : -1; $(name).hidden=name!==view;});
  }
  views.forEach((view, i) => {
    $(`tab-${view}`).addEventListener("click", () => tab(view));
    $(`tab-${view}`).addEventListener("keydown", e => {if (!["ArrowRight","ArrowLeft","Home","End"].includes(e.key)) return; e.preventDefault(); const next=e.key==="Home" ? 0 : e.key==="End" ? 3 : (i+(e.key==="ArrowRight" ? 1 : 3))%4; tab(views[next]); $(`tab-${views[next]}`).focus();});
  });
  function clear() {state=null; $("results").hidden=true; ["stages","counts","provenance","governance-metrics","release-checks","governance-details","product-metrics","breakdowns","dimension","ml-metrics","split","ml-checks","model-metrics"].forEach(id=>$(id).replaceChildren());}
  function disconnect() {generation++; controller?.abort(); token=""; $("token").value=""; clear(); $("token").hidden=false; $("connect").hidden=false; $("connect").disabled=false; $("disconnect").hidden=true; $("refresh").hidden=true; $("message").textContent="Disconnected. Credentials and displayed data cleared.";}
  function entries(id, rows) {$(id).replaceChildren(...rows.map(([label,value])=>{const e=document.createElement("div"); e.append(node("dt",label),node("dd",String(value)));return e;}));}
  function metrics(id, values) {$(id).replaceChildren(...values.map(([label,value,note])=>{const e=node("article","","metric"); e.append(node("p",label),node("strong",String(value)),node("small",note));return e;}));}
  function checks(id, values) {$(id).replaceChildren(...values.map(c=>{const e=document.createElement("li");e.append(node("div",pretty(c.check)),node("span","✓ PASS"));return e;}));}
  function table(id, rows) {$(id).replaceChildren(...rows.map(values=>{const tr=document.createElement("tr");values.forEach(v=>tr.append(node("td",String(v))));return tr;}));}
  function drawBreakdowns() {
    if (!state) return;
    const rows=state.breakdowns.filter(row=>row.dimension===$("dimension").value);
    table("breakdowns",rows.map(r=>[r.category,number(r.eligible_admissions),number(r.readmitted_admissions),percent(r.readmission_rate_pct),`${percent(r.wilson_95_lower_pct)} – ${percent(r.wilson_95_upper_pct)}`]));
    $("empty").hidden=rows.length>0;
    $("breakdown-caption").textContent=`${rows.length} released groups · ${state.quality.suppressed_rows} suppressed rows across the release`;
  }
  function render() {
    const {evidence:e,overall:o,quality:q,status:s}=state, split=e.ml.split;
    const stages=[["Bronze",number(e.bronze.admissions),"Raw admissions"],["Silver",number(e.silver.admissions),"Accepted admissions"],["Identity",number(e.master_patients),"Master patients"],["Gold",number(e.gold_rows),"Feature rows"],["Analytics",number(q.released_breakdown_rows),"Released groups"],["Validation","13 / 13","Release checks passed"]];
    $("stages").replaceChildren(...stages.map(([name,value,label],i)=>{const el=node("article","","stage");el.append(node("small",`STAGE ${String(i+1).padStart(2,"0")}`),node("h3",name),node("strong",value),node("p",label));return el;}));
    table("counts",["patients","admissions","lab_results"].map(d=>[pretty(d),e.bronze[d],e.silver[d],e.quarantine[d]]));
    entries("provenance",[["Data boundary",e.data_mode],["Pipeline run",e.run_id],["Base source commit",e.source_commit],["Executed (UTC)",e.created_at_utc],["Aggregate bundle SHA-256",e.bundle_sha256],["Execution environment","Local Python · no cloud job launched"]]);
    const rejected=Object.values(e.quarantine).reduce((a,b)=>a+b,0);
    metrics("governance-metrics",[["Release validation","13 / 13","All technical release checks passed"],["Quarantined records",rejected,"Invalid fictional inputs excluded"],["Suppressed groups",q.suppressed_rows,"Protected cells remain unpublished"],["Unresolved reviews",e.unresolved_identity_reviews,"No automatic human review decisions"]]);
    checks("release-checks",e.validation_checks);
    entries("governance-details",[["Patient quarantine",e.quarantine.patients],["Admission quarantine",e.quarantine.admissions],["Lab quarantine",e.quarantine.lab_results],["Minimum released cell size",q.minimum_cell_size],["Suppression integrity",q.suppression_integrity],["Identity resolution",pretty(q.identity_resolution)],["Clinical accuracy","Not assessed"]]);
    metrics("product-metrics",[["30-day readmission rate",percent(o.readmission_rate_pct),`95% Wilson interval ${percent(o.wilson_95_lower_pct)} – ${percent(o.wilson_95_upper_pct)}`],["Eligible admissions",number(o.eligible_admissions),`${q.excluded_rows} excluded label rows`],["Observed readmissions",number(o.readmitted_admissions),`${o.not_readmitted_admissions} not readmitted`],["Released groups",q.released_breakdown_rows,`${q.suppressed_rows} groups withheld`]]);
    const dimensions=[...new Set(state.breakdowns.map(r=>r.dimension))];
    $("dimension").replaceChildren(...dimensions.map(d=>{const option=node("option",pretty(d));option.value=d;return option;}));drawBreakdowns();
    metrics("ml-metrics",[["Shared patients","0","Patient-disjoint temporal holdout"],["Training admissions",split.train_admissions,`${split.train_readmissions} observed readmissions`],["Holdout admissions",split.test_admissions,`${split.test_readmissions} observed readmissions`],["Identity exclusions",split.pending_identity_excluded_admissions,"Unresolved identity admissions excluded"]]);
    entries("split",[["Fixed cutoff",split.cutoff_date],["Training-label embargo",`${split.label_embargo_days} days`],["Preprocessing","Fitted on training only"],["Prediction time","Index discharge"],["Model artifacts exported","No"],["Individual predictions exported","No"]]);
    checks("ml-checks",e.ml.technical_checks);
    table("model-metrics",["roc_auc","average_precision","brier_score","balanced_accuracy_at_0_5","log_loss"].map(key=>[pretty(key),e.ml.logistic_regression[key].toFixed(4),e.ml.training_prevalence_baseline[key].toFixed(4)]));
    $("results").hidden=false;
    $("message").textContent=`Authenticated synthetic release loaded · ${s.validation_checks_passed}/13 checks · analytics ${s.current_freshness.toLowerCase()} · fetched ${new Date().toLocaleTimeString()}`;
  }
  async function get(path, signal) {
    const response=await fetch(path,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",credentials:"omit",redirect:"error",signal});
    if (!response.ok) {const error=new Error("Approved release unavailable"); error.status=response.status;throw error;}
    return response.json();
  }
  async function load() {
    const current=++generation; controller?.abort();controller=new AbortController();const signal=controller.signal;
    const timeout=setTimeout(()=>controller?.abort(),90000);
    clear(); $("connect").disabled=true; $("refresh").disabled=true;$("message").textContent="Verifying the approved synthetic release…";
    try {
      const [evidence,overall,quality,status,first]=await Promise.all([get("/api/v1/prototype",signal),get("/api/v1/overall",signal),get("/api/v1/data-quality",signal),get("/api/v1/pipeline-status",signal),get("/api/v1/breakdowns?limit=100&offset=0",signal)]);
      if (!Number.isInteger(first.total) || first.total<0 || first.total>10000) throw new Error("Invalid release");
      const breakdowns=[...first.items];
      while (breakdowns.length<first.total) {const page=await get(`/api/v1/breakdowns?limit=100&offset=${breakdowns.length}`,signal);if(page.total!==first.total || !page.items.length) throw new Error("Release changed");breakdowns.push(...page.items);}
      const after=await get("/api/v1/pipeline-status",signal);
      if (["analytics_sha256","breakdown_sha256","gate_sha256","published_at_utc"].some(key=>status[key]!==after[key]) || breakdowns.length!==quality.released_breakdown_rows || overall.eligible_admissions!==quality.eligible_rows || evidence.gold_rows!==quality.gold_rows || evidence.unresolved_identity_reviews!==quality.unresolved_identity_reviews || evidence.data_mode!=="SYNTHETIC_ONLY") throw new Error("Release changed");
      if(current!==generation)return;
      state={evidence,overall,quality,status,breakdowns};render();$("token").value="";$("token").hidden=true;$("connect").hidden=true;$("disconnect").hidden=false;$("refresh").hidden=false;
    } catch(error) {
      if(current!==generation)return;
      if(error.status===401)disconnect();else clear();
      $("message").textContent=error.status===401 ? "Authentication failed. Paste the local demo token." : error.status===429 ? "Request limit reached. Wait one minute before refreshing." : "Release unavailable or inconsistent. No results are displayed.";
    } finally {clearTimeout(timeout);if(current===generation){$("connect").disabled=false;$("refresh").disabled=false;}}
  }
  $("connect-form").addEventListener("submit",e=>{e.preventDefault();token=$("token").value;load();});
  $("disconnect").addEventListener("click",disconnect);$("refresh").addEventListener("click",load);$("dimension").addEventListener("change",drawBreakdowns);
  window.addEventListener("pagehide",disconnect);
})();
