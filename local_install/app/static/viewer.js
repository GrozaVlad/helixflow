let structureViewer;

async function openViewer(id, file) {
  const modal = document.querySelector("#viewer-modal");
  const status = document.querySelector("#viewer-status");
  document.querySelector("#viewer-title").textContent = file.split("/").pop();
  modal.hidden = false;
  document.body.style.overflow = "hidden";
  status.textContent = "Loading local CIF…";
  try {
    await new Promise(resolve => requestAnimationFrame(resolve));
    if (!structureViewer) {
      structureViewer = await molstar.Viewer.create("molstar-viewer", {
        layoutIsExpanded: false,
        layoutShowControls: true,
        layoutShowRemoteState: false,
        layoutShowSequence: true,
        layoutShowLog: false,
        layoutShowLeftPanel: true,
        viewportShowExpand: true,
        viewportShowSelectionMode: true,
        viewportShowAnimation: true,
        viewportBackgroundColor: "#080b10"
      });
    } else {
      await structureViewer.plugin.clear();
    }
    const url = `/api/jobs/${id}/files/${encodeURI(file)}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`CIF download failed (${response.status})`);
    const cif = await response.text();
    if (!cif.trim()) throw new Error("The CIF file is empty");
    await structureViewer.loadStructureFromData(cif, "mmcif", {
      dataLabel: file.split("/").pop()
    });
    structureViewer.handleResize();
    structureViewer.plugin.canvas3d?.requestCameraReset();
    status.textContent = "Loaded locally";
  } catch (error) {
    status.textContent = `Could not load structure: ${error.message}`;
  }
}

function closeViewer() {
  document.querySelector("#viewer-modal").hidden = true;
  document.body.style.overflow = "";
}

document.querySelector("#viewer-modal").addEventListener("click", event => {
  if (event.target.id === "viewer-modal") closeViewer();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeViewer();
});
