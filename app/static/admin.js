const uploadBtn = document.getElementById('uploadBtn');
const docFiles = document.getElementById('docFiles');
const uploadResult = document.getElementById('uploadResult');

const reindexBtn = document.getElementById('reindexBtn');
const refreshStatusBtn = document.getElementById('refreshStatusBtn');
const reindexResult = document.getElementById('reindexResult');
const monitoringList = document.getElementById('monitoringList');
const adminPageStatus = document.getElementById('adminPageStatus');

function setPageStatus(text, mode = 'active') {
  adminPageStatus.textContent = text;
  adminPageStatus.classList.remove('vr-chip--active');
  adminPageStatus.classList.remove('vr-chip--warning');
  if (mode === 'warning') {
    adminPageStatus.classList.add('vr-chip--warning');
  } else {
    adminPageStatus.classList.add('vr-chip--active');
  }
}

async function uploadDocuments() {
  if (!docFiles.files || !docFiles.files.length) {
    uploadResult.textContent = 'Pilih file terlebih dahulu.';
    return;
  }

  const formData = new FormData();
  for (const file of docFiles.files) {
    formData.append('files', file);
  }

  const response = await fetch('/api/admin/upload-documents', {
    method: 'POST',
    body: formData
  });

  if (!response.ok) throw new Error('Upload gagal');
  const data = await response.json();
  const skipped = data.skipped?.length || 0;
  uploadResult.textContent = skipped
    ? `Upload selesai: ${data.uploaded_count} file, ${skipped} file dilewati.`
    : `Upload selesai: ${data.uploaded_count} file.`;
}

function renderMonitoring(statusData) {
  monitoringList.innerHTML = '';

  for (const service of statusData.services || []) {
    const card = document.createElement('div');
    card.className = 'vr-monitor-item';

    const head = document.createElement('div');
    head.className = 'vr-monitor-item__head';

    const name = document.createElement('strong');
    name.textContent = service.name;

    const label = document.createElement('span');
    label.className = `vr-status-badge ${service.status === 'active' ? 'vr-status-badge--active' : 'vr-status-badge--warning'}`;
    label.textContent = service.label;

    head.appendChild(name);
    head.appendChild(label);

    const detail = document.createElement('p');
    detail.className = 'vr-admin-note';
    detail.textContent = service.detail;

    card.appendChild(head);
    card.appendChild(detail);
    monitoringList.appendChild(card);
  }

  setPageStatus(
    `Monitoring: ${statusData.overall_label}`,
    statusData.overall === 'active' ? 'active' : 'warning'
  );
}

async function refreshMonitoring() {
  const response = await fetch('/api/admin/status');
  if (!response.ok) throw new Error('Gagal memuat status service');
  const data = await response.json();
  renderMonitoring(data);
}

async function triggerReindex() {
  const response = await fetch('/api/reindex', { method: 'POST' });
  if (!response.ok) throw new Error('Reindex gagal');
  const data = await response.json();
  reindexResult.textContent = `Reindex sukses: ${data.documents} dokumen, ${data.chunks} chunk.`;
  setPageStatus('Reindex selesai', 'active');
}

uploadBtn.addEventListener('click', async () => {
  try {
    await uploadDocuments();
    setPageStatus('Upload dokumen selesai', 'active');
  } catch (error) {
    setPageStatus('Warning: upload dokumen gagal', 'warning');
  }
});

reindexBtn.addEventListener('click', async () => {
  try {
    await triggerReindex();
    await refreshMonitoring();
  } catch (error) {
    setPageStatus('Warning: reindex gagal', 'warning');
  }
});

refreshStatusBtn.addEventListener('click', async () => {
  try {
    await refreshMonitoring();
  } catch (error) {
    setPageStatus('Warning: monitoring gagal', 'warning');
  }
});

(async () => {
  try {
    await refreshMonitoring();
    setPageStatus('Admin Active', 'active');
  } catch (error) {
    setPageStatus('Warning: gagal memuat panel admin', 'warning');
  }
})();
