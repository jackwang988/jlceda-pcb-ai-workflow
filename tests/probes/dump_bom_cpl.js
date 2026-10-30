const out = {};
const d = await eda.dmt_SelectControl.getCurrentDocumentInfo();
out.docType = d ? d.documentType : null;
const enc = async (f) => {
  if (!f) return null;
  const bytes = new Uint8Array(await f.arrayBuffer());
  let bin = ''; const chunk = 8192;
  for (let i = 0; i < bytes.length; i += chunk) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  return { name: f.name, size: f.size, b64: btoa(bin) };
};
try { out.bom = await enc(await eda.pcb_ManufactureData.getBomFile('BOM_probe', 'csv')); } catch (e) { out.bomErr = String(e).slice(0, 160); }
try { out.cpl = await enc(await eda.pcb_ManufactureData.getPickAndPlaceFile('CPL_probe', 'csv', 'mm')); } catch (e) { out.cplErr = String(e).slice(0, 160); }
return out;
