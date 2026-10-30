const r = await eda.pcb_Drc.check(true, false, true);
const out = { categories: [] };
for (const c of (r || [])) {
  const cat = { name: c.name, title: c.title, count: c.count, nets: (c.list || []).length, errorTypes: {}, ruleNames: {}, objTypes: {} };
  const walk = (n) => {
    if (!n) return;
    if (n.errorType) {
      cat.errorTypes[n.errorType] = (cat.errorTypes[n.errorType] || 0) + 1;
      if (n.ruleName) cat.ruleNames[n.ruleName] = (cat.ruleNames[n.ruleName] || 0) + 1;
      if (n.errorObjType) cat.objTypes[n.errorObjType] = (cat.objTypes[n.errorObjType] || 0) + 1;
    }
    if (Array.isArray(n.list)) n.list.forEach(walk);
  };
  (c.list || []).forEach(walk);
  out.categories.push(cat);
}
return out;
