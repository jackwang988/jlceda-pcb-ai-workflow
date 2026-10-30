const out = {};
try { out.version = await eda.sys_Environment.getEditorCurrentVersion(); } catch (e) { out.versionErr = String(e).slice(0, 80); }
try { out.isJLCEDAPro = await eda.sys_Environment.isJLCEDAProEdition(); } catch (e) { out.edErr = String(e).slice(0, 80); }
try { out.curName = await eda.pcb_Drc.getCurrentRuleConfigurationName(); } catch (e) { out.curNameErr = String(e).slice(0, 80); }
try { out.defName = await eda.pcb_Drc.getDefaultRuleConfigurationName(); } catch (e) { out.defNameErr = String(e).slice(0, 80); }
try {
  const all = await eda.pcb_Drc.getAllRuleConfigurations(true);
  out.allCount = Array.isArray(all) ? all.length : -1;
  out.allNames = Array.isArray(all) ? all.map(x => (x && (x.name || x.configurationName)) || Object.keys(x || {})[0]) : null;
  out.allKeysSample = Array.isArray(all) && all[0] ? Object.keys(all[0]).slice(0, 12) : null;
} catch (e) { out.allErr = String(e).slice(0, 120); }
return out;
