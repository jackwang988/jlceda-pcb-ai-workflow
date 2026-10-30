const out = {};
try { const d = await eda.dmt_SelectControl.getCurrentDocumentInfo(); out.doc = d ? { type: d.documentType, name: d.name || d.tabTitle || null } : null; } catch (e) { out.docErr = String(e).slice(0, 100); }
try { const p = await eda.dmt_Project.getCurrentProjectInfo(); out.project = p ? { name: p.friendlyName || p.name } : null; } catch (e) { out.projErr = String(e).slice(0, 100); }
try { out.pcbComp = ((await eda.pcb_PrimitiveComponent.getAll()) || []).length; } catch (e) { out.compErr = String(e).slice(0, 80); }
try { out.pcbVia = ((await eda.pcb_PrimitiveVia.getAll()) || []).length; } catch (e) { out.viaErr = String(e).slice(0, 80); }
try { out.pcbLine = ((await eda.pcb_PrimitiveLine.getAll()) || []).length; } catch (e) { out.lineErr = String(e).slice(0, 80); }
try {
  const r0 = await eda.pcb_Drc.check(true, false, false);
  out.checkBool = { type: typeof r0, value: (typeof r0 === 'boolean') ? r0 : (Array.isArray(r0) ? 'array' + r0.length : String(r0).slice(0, 60)) };
} catch (e) { out.checkBoolErr = String(e).slice(0, 120); }
try {
  const r = await eda.pcb_Drc.check(true, false, true);
  out.verbose = { isArray: Array.isArray(r), len: Array.isArray(r) ? r.length : -1 };
  if (Array.isArray(r) && r.length) {
    out.verbose.firstKeys = Object.keys(r[0] || {}).slice(0, 12);
    let s = ''; try { s = JSON.stringify(r[0]); } catch (e) { s = 'unserializable'; }
    out.verbose.firstSample = s.slice(0, 600);
  }
} catch (e) { out.verboseErr = String(e).slice(0, 160); }
return out;
