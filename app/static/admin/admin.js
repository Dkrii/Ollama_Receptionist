const uploadBtn = document.getElementById('uploadBtn');
const docFiles = document.getElementById('docFiles');

const reindexBtn = document.getElementById('reindexBtn');
const refreshStatusBtn = document.getElementById('refreshStatusBtn');
const adminPageStatus = document.getElementById('adminPageStatus');
const knowledgeTableBody = document.getElementById('knowledgeTableBody');
const knowledgeTableEmpty = document.getElementById('knowledgeTableEmpty');
const selectFilesBtn = document.getElementById('selectFilesBtn');
const selectedFileInfo = document.getElementById('selectedFileInfo');
const uploadDropzone = document.getElementById('uploadDropzone');
const clearKnowledgeHistoryBtn = document.getElementById('clearKnowledgeHistoryBtn');
const healthCoverageValue = document.getElementById('healthCoverageValue');
const healthCoverageBar = document.getElementById('healthCoverageBar');
const healthQueueValue = document.getElementById('healthQueueValue');
const healthChunksValue = document.getElementById('healthChunksValue');

let stagedFiles = null;

const navViewItems = document.querySelectorAll('.vr-admin-nav__item[data-view]');
const viewSections = document.querySelectorAll('.vr-admin-view[data-view]');
const dashIndexedDocs = document.getElementById('dashIndexedDocs');
const dashChunksTotal = document.getElementById('dashChunksTotal');
const dashReadinessLabel = document.getElementById('dashReadinessLabel');
const dashCoverage = document.getElementById('dashCoverage');
const dashCheckedAt = document.getElementById('dashCheckedAt');
const dashRecentActivity = document.getElementById('dashRecentActivity');
const dashInsightText = document.getElementById('dashInsightText');
const employeeForm = document.getElementById('employeeForm');
const employeeSaveBtn = document.getElementById('employeeSaveBtn');
const employeeNamaInput = document.getElementById('employeeNama');
const employeeDepartemenInput = document.getElementById('employeeDepartemen');
const employeeJabatanInput = document.getElementById('employeeJabatan');
const employeeNomorWaInput = document.getElementById('employeeNomorWa');
const employeeTableBody = document.getElementById('employeeTableBody');
const employeeTableEmpty = document.getElementById('employeeTableEmpty');

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

function updateSelectedFilesInfo() {
  if (!selectedFileInfo || !docFiles) return;

  const activeFiles = stagedFiles || docFiles.files;
  const count = activeFiles?.length || 0;
  if (!count) {
    selectedFileInfo.textContent = 'Belum ada file dipilih.';
    return;
  }

  const names = Array.from(activeFiles).slice(0, 2).map((file) => file.name);
  const suffix = count > 2 ? ` +${count - 2} file` : '';
  selectedFileInfo.textContent = `Dipilih: ${names.join(', ')}${suffix}`;
}

function openDocumentPicker() {
  if (!docFiles) return;

  // Prefer the native picker API when available; fallback to synthetic click.
  if (typeof docFiles.showPicker === 'function') {
    docFiles.showPicker();
    return;
  }

  docFiles.click();
}

function activateView(viewName) {
  for (const item of navViewItems) {
    item.classList.toggle('is-active', item.dataset.view === viewName);
  }

  for (const section of viewSections) {
    const shouldShow = section.dataset.view === viewName;
    section.classList.toggle('is-hidden', !shouldShow);
  }
}

function getViewFromHash() {
  if (window.location.hash === '#knowledge') return 'knowledge';
  if (window.location.hash === '#employees') return 'employees';
  return 'dashboard';
}

function renderEmployeeTable(items) {
  if (!employeeTableBody || !employeeTableEmpty) return;

  employeeTableBody.innerHTML = '';
  for (const item of items) {
    const row = document.createElement('tr');

    const namaCell = document.createElement('td');
    namaCell.textContent = item.nama || '-';

    const departemenCell = document.createElement('td');
    departemenCell.textContent = item.departemen || '-';

    const jabatanCell = document.createElement('td');
    jabatanCell.textContent = item.jabatan || '-';

    const waCell = document.createElement('td');
    waCell.textContent = item.nomor_wa || '-';

    row.appendChild(namaCell);
    row.appendChild(departemenCell);
    row.appendChild(jabatanCell);
    row.appendChild(waCell);
    employeeTableBody.appendChild(row);
  }

  employeeTableEmpty.classList.toggle('is-hidden', items.length > 0);
}

async function refreshEmployees() {
  const response = await fetch('/api/admin/employees');
  if (!response.ok) throw new Error('Gagal memuat data karyawan');

  const payload = await response.json();
  const employees = payload.employees || [];
  renderEmployeeTable(employees);
}

async function saveEmployee(payload) {
  const response = await fetch('/api/admin/employees', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    let detail = 'Gagal menyimpan data karyawan';
    try {
      const errorData = await response.json();
      detail = errorData.detail || detail;
    } catch (error) {
    }
    throw new Error(detail);
  }

  return response.json();
}

function renderDashboardActivity(summaryData) {
  const checkedAt = summaryData.checked_at
    ? new Date(summaryData.checked_at).toLocaleString('id-ID')
    : '-';

  const activities = [
    ...(summaryData.top_sources || []).map((source) => ({
      title: source.source,
      detail: `${source.chunks} chunk terindeks`,
      time: 'baru'
    })),
    ...(summaryData.unindexed_sources || []).slice(0, 2).map((source) => ({
      title: source,
      detail: 'Belum terindeks',
      time: 'perlu aksi'
    }))
  ].slice(0, 4);

  dashRecentActivity.innerHTML = '';
  if (!activities.length) {
    const empty = document.createElement('div');
    empty.className = 'vr-dash-activity__item';
    empty.innerHTML = '<div><strong>Belum ada aktivitas</strong><span>Upload dokumen untuk memulai.</span></div>';
    dashRecentActivity.appendChild(empty);
    return;
  }

  for (const activity of activities) {
    const item = document.createElement('div');
    item.className = 'vr-dash-activity__item';
    item.innerHTML = `
      <div>
        <strong>${activity.title}</strong>
        <span>${activity.detail}</span>
      </div>
      <span>${activity.time}</span>
    `;
    dashRecentActivity.appendChild(item);
  }

  dashCheckedAt.textContent = `Updated ${checkedAt}`;
}

function renderDashboard(summaryData) {
  const coverage = Number(summaryData.coverage_pct || 0);
  dashIndexedDocs.textContent = summaryData.indexed_documents ?? 0;
  dashChunksTotal.textContent = summaryData.chunks_total ?? 0;
  dashReadinessLabel.textContent = summaryData.readiness_label || 'Unknown';
  dashCoverage.textContent = `Coverage ${coverage}%`;

  dashInsightText.textContent = summaryData.unindexed_documents > 0
    ? `Masih ada ${summaryData.unindexed_documents} dokumen belum terindeks. Jalankan reindex agar retrieval optimal.`
    : 'Knowledge sudah sinkron. Pertahankan alur upload lalu reindex untuk menjaga kualitas jawaban AI.';

  renderDashboardActivity(summaryData);
}

async function uploadDocuments() {
  const activeFiles = stagedFiles || docFiles.files;
  if (!activeFiles || !activeFiles.length) {
    setPageStatus('Pilih file terlebih dahulu', 'warning');
    return;
  }

  const formData = new FormData();
  for (const file of activeFiles) {
    formData.append('files', file);
  }

  const response = await fetch('/api/admin/upload-documents', {
    method: 'POST',
    body: formData
  });

  if (!response.ok) throw new Error('Upload gagal');
  const data = await response.json();
  const skipped = data.skipped?.length || 0;
  const uploadMessage = skipped
    ? `Upload selesai: ${data.uploaded_count} file, ${skipped} file dilewati.`
    : `Upload selesai: ${data.uploaded_count} file.`;
  setPageStatus(uploadMessage, skipped ? 'warning' : 'active');
  stagedFiles = null;
  if (docFiles) {
    docFiles.value = '';
  }
  updateSelectedFilesInfo();
}

function renderKnowledgeHealth(summaryData) {
  if (healthCoverageValue) {
    healthCoverageValue.textContent = `${summaryData.coverage_pct ?? 0}%`;
  }
  if (healthCoverageBar) {
    healthCoverageBar.style.width = `${summaryData.coverage_pct ?? 0}%`;
  }
  if (healthQueueValue) {
    healthQueueValue.textContent = `${summaryData.unindexed_documents ?? 0} tasks`;
  }
  if (healthChunksValue) {
    healthChunksValue.textContent = `${summaryData.chunks_total ?? 0}`;
  }
}

function renderKnowledgeTable(summaryData) {
  if (!knowledgeTableBody || !knowledgeTableEmpty) return;
  const tableRows = summaryData.documents || [];
  knowledgeTableBody.innerHTML = '';

  for (const rowData of tableRows) {
    const row = document.createElement('tr');
    const documentCell = document.createElement('td');
    documentCell.textContent = rowData.document || '-';

    const chunksCell = document.createElement('td');
    chunksCell.textContent = rowData.chunks ?? '-';

    const statusCell = document.createElement('td');
    const statusBadge = document.createElement('span');
    statusBadge.className = `vr-knowledge-status vr-knowledge-status--${rowData.status}`;
    statusBadge.textContent = rowData.status === 'indexed' ? 'Indexed' : 'Pending';
    statusCell.appendChild(statusBadge);

    const updatedCell = document.createElement('td');
    updatedCell.textContent = rowData.updated_at
      ? new Date(rowData.updated_at).toLocaleString('id-ID')
      : '-';

    const actionCell = document.createElement('td');
    const actionWrap = document.createElement('div');
    actionWrap.className = 'vr-knowledge-actions';

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'vr-knowledge-delete';
    deleteButton.dataset.path = rowData.path || rowData.document || '';
    deleteButton.textContent = 'Delete';
    actionWrap.appendChild(deleteButton);
    actionCell.appendChild(actionWrap);

    row.appendChild(documentCell);
    row.appendChild(chunksCell);
    row.appendChild(statusCell);
    row.appendChild(updatedCell);
    row.appendChild(actionCell);
    knowledgeTableBody.appendChild(row);
  }

  knowledgeTableEmpty.classList.toggle('is-hidden', tableRows.length > 0);
}

function renderKnowledgeSummary(summaryData) {
  renderKnowledgeHealth(summaryData);
  renderKnowledgeTable(summaryData);

  renderDashboard(summaryData);

  setPageStatus(
    `Knowledge: ${summaryData.readiness_label}`,
    summaryData.readiness === 'active' ? 'active' : 'warning'
  );
}

async function refreshKnowledgeSummary() {
  const response = await fetch('/api/admin/knowledge-summary');
  if (!response.ok) throw new Error('Gagal memuat ringkasan knowledge');
  const data = await response.json();
  renderKnowledgeSummary(data);
}

async function deleteKnowledgeDocument(path) {
  const response = await fetch('/api/admin/documents', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path })
  });

  if (!response.ok) {
    let detail = 'Gagal menghapus dokumen';
    try {
      const errorData = await response.json();
      detail = errorData.detail || detail;
    } catch (error) {
    }
    throw new Error(detail);
  }

  return response.json();
}

async function triggerReindex() {
  const response = await fetch('/api/reindex', { method: 'POST' });
  if (!response.ok) throw new Error('Reindex gagal');
  const data = await response.json();
  setPageStatus(`Reindex sukses: ${data.documents} dokumen, ${data.chunks} chunk.`, 'active');
}

uploadBtn.addEventListener('click', async () => {
  try {
    await uploadDocuments();
    await refreshKnowledgeSummary();
    setPageStatus('Upload dokumen selesai', 'active');
  } catch (error) {
    setPageStatus('Warning: upload dokumen gagal', 'warning');
  }
});

reindexBtn.addEventListener('click', async () => {
  try {
    await triggerReindex();
    await refreshKnowledgeSummary();
  } catch (error) {
    setPageStatus('Warning: reindex gagal', 'warning');
  }
});

refreshStatusBtn.addEventListener('click', async () => {
  try {
    await refreshKnowledgeSummary();
  } catch (error) {
    setPageStatus('Warning: refresh knowledge gagal', 'warning');
  }
});

if (selectFilesBtn && docFiles) {
  selectFilesBtn.addEventListener('click', openDocumentPicker);
}

if (docFiles) {
  docFiles.addEventListener('change', () => {
    stagedFiles = null;
    updateSelectedFilesInfo();
  });
}

if (uploadDropzone && docFiles) {
  const preventDefaults = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };

  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
    uploadDropzone.addEventListener(eventName, preventDefaults);
  });

  ['dragenter', 'dragover'].forEach((eventName) => {
    uploadDropzone.addEventListener(eventName, () => uploadDropzone.classList.add('is-dragover'));
  });

  ['dragleave', 'drop'].forEach((eventName) => {
    uploadDropzone.addEventListener(eventName, () => uploadDropzone.classList.remove('is-dragover'));
  });

  uploadDropzone.addEventListener('drop', (event) => {
    const files = event.dataTransfer?.files;
    if (!files?.length) return;
    stagedFiles = files;
    updateSelectedFilesInfo();
  });
}

if (clearKnowledgeHistoryBtn && knowledgeTableBody && knowledgeTableEmpty) {
  clearKnowledgeHistoryBtn.addEventListener('click', () => {
    knowledgeTableBody.innerHTML = '';
    knowledgeTableEmpty.classList.remove('is-hidden');
  });
}

if (knowledgeTableBody) {
  knowledgeTableBody.addEventListener('click', async (event) => {
    const targetButton = event.target.closest('.vr-knowledge-delete');
    if (!targetButton) return;

    const documentPath = targetButton.dataset.path;
    if (!documentPath) return;

    const confirmed = window.confirm(`Hapus dokumen "${documentPath}" dari knowledge base?`);
    if (!confirmed) return;

    const originalText = targetButton.textContent;
    targetButton.disabled = true;
    targetButton.textContent = 'Deleting...';

    try {
      const result = await deleteKnowledgeDocument(documentPath);
      await refreshKnowledgeSummary();
      setPageStatus(`Dokumen dihapus: ${result.deleted}`, 'active');
    } catch (error) {
      setPageStatus(error.message || 'Warning: gagal menghapus dokumen', 'warning');
    } finally {
      targetButton.disabled = false;
      targetButton.textContent = originalText;
    }
  });
}

if (employeeForm) {
  employeeForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!employeeNamaInput || !employeeDepartemenInput || !employeeJabatanInput || !employeeNomorWaInput) {
      setPageStatus('Warning: form karyawan tidak lengkap', 'warning');
      return;
    }

    const payload = {
      nama: employeeNamaInput.value,
      departemen: employeeDepartemenInput.value,
      jabatan: employeeJabatanInput.value,
      nomor_wa: employeeNomorWaInput.value
    };

    if (employeeSaveBtn) {
      employeeSaveBtn.disabled = true;
      employeeSaveBtn.textContent = 'Menyimpan...';
    }

    try {
      await saveEmployee(payload);
      employeeForm.reset();
      await refreshEmployees();
      setPageStatus('Data karyawan berhasil disimpan', 'active');
    } catch (error) {
      setPageStatus(error.message || 'Warning: gagal menyimpan data karyawan', 'warning');
    } finally {
      if (employeeSaveBtn) {
        employeeSaveBtn.disabled = false;
        employeeSaveBtn.textContent = 'Simpan';
      }
    }
  });
}

for (const navItem of navViewItems) {
  navItem.addEventListener('click', () => {
    const targetView = navItem.dataset.view || 'dashboard';
    activateView(targetView);
  });
}

for (const dashboardButton of document.querySelectorAll('[data-view="knowledge"]')) {
  dashboardButton.addEventListener('click', () => {
    activateView('knowledge');
    window.location.hash = 'knowledge';
  });
}

window.addEventListener('hashchange', () => {
  activateView(getViewFromHash());
});

(async () => {
  try {
    activateView(getViewFromHash());
    await refreshKnowledgeSummary();
    await refreshEmployees();
    setPageStatus('Admin Active', 'active');
  } catch (error) {
    setPageStatus('Warning: gagal memuat panel admin', 'warning');
  }
})();
