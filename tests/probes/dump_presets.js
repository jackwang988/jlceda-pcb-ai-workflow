const all = await eda.pcb_Drc.getAllRuleConfigurations(true);
const out = {};
for (const x of all) { out[x.name] = x.config; }
return out;
