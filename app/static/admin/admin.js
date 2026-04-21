const uploadBtn = document.getElementById('uploadBtn');
const docFiles = document.getElementById('docFiles');

const reindexBtn = document.getElementById('reindexBtn');
const refreshStatusBtn = document.getElementById('refreshStatusBtn');
const adminPageStatus = document.getElementById('adminPageStatus');
const adminSidebarOverlay = document.getElementById('adminSidebarOverlay');
const sidebarDrawerBtn = document.getElementById('sidebarDrawerBtn');
const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
const sidebarToggleIcon = document.getElementById('sidebarToggleIcon');
const knowledgeTableBody = document.getElementById('knowledgeTableBody');
const knowledgeTableEmpty = document.getElementById('knowledgeTableEmpty');
const selectFilesBtn = document.getElementById('selectFilesBtn');
const selectedFileInfo = document.getElementById('selectedFileInfo');
const uploadDropzone = document.getElementById('uploadDropzone');
const healthCoverageValue = document.getElementById('healthCoverageValue');
const healthCoverageBar = document.getElementById('healthCoverageBar');
const healthQueueValue = document.getElementById('healthQueueValue');
const healthChunksValue = document.getElementById('healthChunksValue');
const healthIndexStatus = document.getElementById('healthIndexStatus');
const healthLastSync = document.getElementById('healthLastSync');
const knowledgeSearchInput = document.getElementById('knowledgeSearchInput');
const knowledgeStatusFilter = document.getElementById('knowledgeStatusFilter');

const historyTabButtons = document.querySelectorAll('[data-history-tab]');
const historySearchInput = document.getElementById('historySearchInput');
const historyStatusFilter = document.getElementById('historyStatusFilter');
const historyTableHead = document.getElementById('historyTableHead');
const historyTableBody = document.getElementById('historyTableBody');
const historyTableEmpty = document.getElementById('historyTableEmpty');
const historySummaryCards = document.getElementById('historySummaryCards');

let stagedFiles = null;
let latestKnowledgeSummary = null;

const historyState = {
  activeTab: 'calls',
  items: {
    calls: [],
    messages: []
  },
  loaded: {
    calls: false,
    messages: false
  },
  loading: {
    calls: false,
    messages: false
  },
  errors: {
    calls: '',
    messages: ''
  },
  summary: {
    calls: null,
    messages: null
  }
};

const HISTORY_CONFIG = {
  calls: {
    endpoint: '/api/admin/contact-calls?limit=50',
    emptyMessage: 'Belum ada riwayat call.',
    columns: ['Waktu', 'Employee', 'Status', 'Provider', 'Detail'],
    summaryCards: [
      { key: 'total', label: 'Total Calls', tone: 'neutral' },
      { key: 'active', label: 'Active', tone: 'info' },
      { key: 'no_response', label: 'No Response', tone: 'warning' },
      { key: 'failed', label: 'Failed', tone: 'danger' }
    ]
  },
  messages: {
    endpoint: '/api/admin/contact-messages?limit=50',
    emptyMessage: 'Belum ada riwayat message.',
    columns: ['Waktu', 'Visitor', 'Employee', 'Status', 'Channel', 'Message'],
    summaryCards: [
      { key: 'total', label: 'Total Messages', tone: 'neutral' },
      { key: 'dispatched', label: 'Dispatched', tone: 'success' },
      { key: 'queued', label: 'Queued', tone: 'warning' },
      { key: 'failed', label: 'Failed', tone: 'danger' }
    ]
  }
};

const navViewItems = document.querySelectorAll('.vr-admin-nav__item[data-view]');
const viewSections = document.querySelectorAll('.vr-admin-view[data-view]');
const dashIndexedDocs = document.getElementById('dashIndexedDocs');
const dashChunksTotal = document.getElementById('dashChunksTotal');
const dashReadinessLabel = document.getElementById('dashReadinessLabel');
const dashCoverage = document.getElementById('dashCoverage');
const dashCheckedAt = document.getElementById('dashCheckedAt');
const dashRecentActivity = document.getElementById('dashRecentActivity');
const dashInsightText = document.getElementById('dashInsightText');
const mobileSidebarQuery = window.matchMedia('(max-width: 1024px)');

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

function isMobileSidebarMode() {
  return mobileSidebarQuery.matches;
}

function syncSidebarButtons() {
  const isCollapsed = document.body.classList.contains('is-sidebar-collapsed');
  const isOpen = document.body.classList.contains('is-sidebar-open');

  if (sidebarDrawerBtn) {
    sidebarDrawerBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  }

  if (sidebarToggleBtn) {
    const isMobile = isMobileSidebarMode();
    sidebarToggleBtn.setAttribute('aria-pressed', !isMobile && isCollapsed ? 'true' : 'false');
    sidebarToggleBtn.setAttribute('aria-label', isMobile
      ? 'Tutup menu'
      : isCollapsed
      ? 'Expand sidebar'
      : 'Collapse sidebar'
    );
  }

  if (sidebarToggleIcon) {
    sidebarToggleIcon.textContent = isMobileSidebarMode()
      ? 'chevron_left'
      : isCollapsed
      ? 'chevron_right'
      : 'chevron_left';
  }
}

function closeSidebarDrawer() {
  document.body.classList.remove('is-sidebar-open');
  syncSidebarButtons();
}

function openSidebarDrawer() {
  document.body.classList.add('is-sidebar-open');
  syncSidebarButtons();
}

function toggleSidebarDrawer() {
  if (document.body.classList.contains('is-sidebar-open')) {
    closeSidebarDrawer();
  } else {
    openSidebarDrawer();
  }
}

function toggleSidebarCollapse() {
  if (isMobileSidebarMode()) {
    toggleSidebarDrawer();
    return;
  }

  document.body.classList.toggle('is-sidebar-collapsed');
  syncSidebarButtons();
}

function syncSidebarLayout() {
  if (isMobileSidebarMode()) {
    document.body.classList.remove('is-sidebar-collapsed');
  } else {
    document.body.classList.remove('is-sidebar-open');
  }
  syncSidebarButtons();
}

function formatDateTime(dateValue) {
  if (!dateValue) return '-';
  return new Date(dateValue).toLocaleString('id-ID');
}

function formatPrimaryText(value, fallback = '-') {
  const normalized = String(value || '').trim();
  return normalized || fallback;
}

function humanizeStatus(value) {
  const normalized = String(value || '').trim();
  if (!normalized) return '-';
  return normalized.replace(/_/g, ' ');
}

function sentenceCase(value) {
  const normalized = humanizeStatus(value);
  if (normalized === '-') return normalized;
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function setButtonBusy(button, busyLabel, isBusy) {
  if (!button) return;
  if (!button.dataset.defaultLabel) {
    button.dataset.defaultLabel = button.textContent;
  }
  button.disabled = isBusy;
  button.textContent = isBusy ? busyLabel : button.dataset.defaultLabel;
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

  if (viewName === 'history') {
    syncHistoryFilterOptions();
    renderHistoryTable();
    void ensureHistoryData(historyState.activeTab);
  }

  if (isMobileSidebarMode()) {
    closeSidebarDrawer();
  }
}

function getViewFromHash() {
  if (window.location.hash === '#knowledge') return 'knowledge';
  if (window.location.hash === '#history') return 'history';
  return 'dashboard';
}

function renderDashboardActivity(summaryData) {
  const checkedAt = formatDateTime(summaryData.checked_at);

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

  if (summaryData.unindexed_documents > 0) {
    dashInsightText.textContent = `Masih ada ${summaryData.unindexed_documents} dokumen pending reindex. Jalankan reindex agar retrieval optimal.`;
  } else if (summaryData.index_status === 'warning') {
    dashInsightText.textContent = summaryData.index_detail || 'Index perlu dicek karena ada masalah koneksi atau metadata.';
  } else {
    dashInsightText.textContent = 'Knowledge sudah sinkron. Pertahankan alur upload lalu reindex untuk menjaga kualitas jawaban AI.';
  }

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
    healthQueueValue.textContent = `${summaryData.unindexed_documents ?? 0} dokumen`;
  }
  if (healthChunksValue) {
    healthChunksValue.textContent = `${summaryData.chunks_total ?? 0}`;
  }
  if (healthIndexStatus) {
    healthIndexStatus.textContent = summaryData.index_status === 'active' ? 'Ready' : 'Warning';
  }
  if (healthLastSync) {
    healthLastSync.textContent = formatDateTime(summaryData.checked_at);
  }
}

function getFilteredKnowledgeRows(summaryData) {
  const tableRows = summaryData.documents || [];
  const searchValue = (knowledgeSearchInput?.value || '').trim().toLowerCase();
  const statusValue = knowledgeStatusFilter?.value || 'all';

  return tableRows.filter((rowData) => {
    const matchesSearch = !searchValue || String(rowData.document || '').toLowerCase().includes(searchValue);
    const matchesStatus = statusValue === 'all' || rowData.status === statusValue;
    return matchesSearch && matchesStatus;
  });
}

function renderKnowledgeTable(summaryData) {
  if (!knowledgeTableBody || !knowledgeTableEmpty) return;
  const tableRows = getFilteredKnowledgeRows(summaryData);
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
    updatedCell.textContent = formatDateTime(rowData.updated_at);

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
  if (!tableRows.length) {
    knowledgeTableEmpty.textContent = 'Tidak ada dokumen yang cocok dengan filter saat ini.';
  }
}

function renderKnowledgeSummary(summaryData) {
  latestKnowledgeSummary = summaryData;
  renderKnowledgeHealth(summaryData);
  renderKnowledgeTable(summaryData);

  renderDashboard(summaryData);

  const statusMessage = summaryData.index_status === 'warning'
    ? `Knowledge: ${summaryData.readiness_label} - ${summaryData.index_detail}`
    : `Knowledge: ${summaryData.readiness_label}`;

  setPageStatus(statusMessage, summaryData.readiness === 'active' ? 'active' : 'warning');
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

function getHistoryTabLabel(tabName) {
  return tabName === 'messages' ? 'message' : 'call';
}

function createStackContent(primary, secondary = '') {
  const wrapper = document.createElement('div');
  wrapper.className = 'vr-history-stack';

  const primaryNode = document.createElement('strong');
  primaryNode.className = 'vr-history-primary';
  primaryNode.textContent = formatPrimaryText(primary);
  wrapper.appendChild(primaryNode);

  if (String(secondary || '').trim()) {
    const secondaryNode = document.createElement('span');
    secondaryNode.className = 'vr-history-secondary';
    secondaryNode.textContent = secondary;
    wrapper.appendChild(secondaryNode);
  }

  return wrapper;
}

function createStatusChip(statusValue) {
  const chip = document.createElement('span');
  chip.className = `vr-status-chip ${getStatusChipClass(statusValue)}`;
  chip.textContent = sentenceCase(statusValue);
  return chip;
}

function getStatusChipClass(statusValue) {
  const normalized = String(statusValue || '').trim().toLowerCase();
  if (['connected', 'completed', 'sent', 'accepted'].includes(normalized)) {
    return 'vr-status-chip--success';
  }
  if (['queued', 'ringing', 'dialing_employee', 'pending', 'busy', 'no_response'].includes(normalized)) {
    return 'vr-status-chip--warning';
  }
  if (['failed', 'cancelled', 'rejected'].includes(normalized)) {
    return 'vr-status-chip--danger';
  }
  return 'vr-status-chip--neutral';
}

function buildHistoryTableHead(tabName) {
  if (!historyTableHead) return;

  const row = document.createElement('tr');
  for (const label of HISTORY_CONFIG[tabName].columns) {
    const th = document.createElement('th');
    th.textContent = label;
    row.appendChild(th);
  }

  historyTableHead.innerHTML = '';
  historyTableHead.appendChild(row);
}

function setHistoryEmptyState(message) {
  if (!historyTableEmpty || !historyTableBody) return;
  historyTableBody.innerHTML = '';
  historyTableEmpty.textContent = message;
  historyTableEmpty.classList.remove('is-hidden');
}

function clearHistoryEmptyState() {
  if (!historyTableEmpty) return;
  historyTableEmpty.classList.add('is-hidden');
}

function renderHistorySummary() {
  if (!historySummaryCards) return;

  const tabName = historyState.activeTab;
  const summary = historyState.summary[tabName];
  const hasError = Boolean(historyState.errors[tabName]);
  const isLoading = historyState.loading[tabName];

  if (!summary || hasError || isLoading) {
    historySummaryCards.innerHTML = '';
    historySummaryCards.classList.add('is-hidden');
    return;
  }

  historySummaryCards.innerHTML = '';
  historySummaryCards.classList.remove('is-hidden');

  for (const card of HISTORY_CONFIG[tabName].summaryCards) {
    const article = document.createElement('article');
    article.className = `vr-history-summary__card vr-history-summary__card--${card.tone}`;

    const label = document.createElement('span');
    label.className = 'vr-history-summary__label';
    label.textContent = card.label;

    const value = document.createElement('strong');
    value.className = 'vr-history-summary__value';
    value.textContent = String(summary[card.key] ?? 0);

    article.appendChild(label);
    article.appendChild(value);
    historySummaryCards.appendChild(article);
  }
}

function getHistoryStatusValue(item, tabName) {
  return tabName === 'messages' ? item.delivery_status : item.call_status;
}

function getFilteredHistoryItems(tabName) {
  const searchValue = (historySearchInput?.value || '').trim().toLowerCase();
  const statusValue = historyStatusFilter?.value || 'all';
  const items = historyState.items[tabName] || [];

  return items.filter((item) => {
    const searchParts = tabName === 'messages'
      ? [
          item.visitor_name,
          item.visitor_goal,
          item.employee_nama,
          item.employee_departemen,
          item.delivery_status,
          item.channel,
          item.message_text
        ]
      : [
          item.employee_nama,
          item.employee_departemen,
          item.call_status,
          item.call_provider,
          item.call_detail
        ];

    const haystack = searchParts
      .map((part) => String(part || '').toLowerCase())
      .join(' ');

    const matchesSearch = !searchValue || haystack.includes(searchValue);
    const matchesStatus = statusValue === 'all' || getHistoryStatusValue(item, tabName) === statusValue;
    return matchesSearch && matchesStatus;
  });
}

function syncHistoryFilterOptions() {
  if (!historyStatusFilter) return;

  const tabName = historyState.activeTab;
  const currentValue = historyStatusFilter.value || 'all';
  const items = historyState.items[tabName] || [];
  const statusValues = Array.from(
    new Set(
      items
        .map((item) => getHistoryStatusValue(item, tabName))
        .filter((value) => String(value || '').trim())
    )
  ).sort();

  historyStatusFilter.innerHTML = '';
  const allOption = document.createElement('option');
  allOption.value = 'all';
  allOption.textContent = 'Semua';
  historyStatusFilter.appendChild(allOption);

  for (const statusValue of statusValues) {
    const option = document.createElement('option');
    option.value = statusValue;
    option.textContent = sentenceCase(statusValue);
    historyStatusFilter.appendChild(option);
  }

  historyStatusFilter.value = statusValues.includes(currentValue) || currentValue === 'all'
    ? currentValue
    : 'all';
}

function renderCallHistoryRows(items) {
  for (const item of items) {
    const row = document.createElement('tr');

    const timeCell = document.createElement('td');
    let timeMeta = '';
    if (item.ended_at) {
      timeMeta = `Selesai ${formatDateTime(item.ended_at)}`;
    } else if (item.connected_at) {
      timeMeta = `Tersambung ${formatDateTime(item.connected_at)}`;
    }
    timeCell.appendChild(createStackContent(formatDateTime(item.created_at), timeMeta));

    const employeeCell = document.createElement('td');
    employeeCell.appendChild(createStackContent(item.employee_nama, item.employee_departemen));

    const statusCell = document.createElement('td');
    statusCell.appendChild(createStatusChip(item.call_status));

    const providerCell = document.createElement('td');
    providerCell.appendChild(createStackContent(formatPrimaryText(item.call_provider).toUpperCase()));

    const detailCell = document.createElement('td');
    detailCell.className = 'vr-history-cell--copy';
    const detailCopy = document.createElement('div');
    detailCopy.className = 'vr-history-copy';
    detailCopy.textContent = formatPrimaryText(item.call_detail);
    detailCell.appendChild(detailCopy);

    row.appendChild(timeCell);
    row.appendChild(employeeCell);
    row.appendChild(statusCell);
    row.appendChild(providerCell);
    row.appendChild(detailCell);
    historyTableBody.appendChild(row);
  }
}

function renderMessageHistoryRows(items) {
  for (const item of items) {
    const row = document.createElement('tr');

    const timeCell = document.createElement('td');
    const sentMeta = item.sent_at ? `Terkirim ${formatDateTime(item.sent_at)}` : '';
    timeCell.appendChild(createStackContent(formatDateTime(item.created_at), sentMeta));

    const visitorCell = document.createElement('td');
    visitorCell.appendChild(createStackContent(item.visitor_name, item.visitor_goal));

    const employeeCell = document.createElement('td');
    employeeCell.appendChild(createStackContent(item.employee_nama, item.employee_departemen));

    const statusCell = document.createElement('td');
    statusCell.appendChild(createStatusChip(item.delivery_status));

    const channelCell = document.createElement('td');
    channelCell.appendChild(createStackContent(formatPrimaryText(item.channel).toUpperCase()));

    const messageCell = document.createElement('td');
    messageCell.className = 'vr-history-cell--copy';
    const messageCopy = document.createElement('div');
    messageCopy.className = 'vr-history-copy';
    messageCopy.textContent = formatPrimaryText(item.message_text);
    messageCell.appendChild(messageCopy);

    row.appendChild(timeCell);
    row.appendChild(visitorCell);
    row.appendChild(employeeCell);
    row.appendChild(statusCell);
    row.appendChild(channelCell);
    row.appendChild(messageCell);
    historyTableBody.appendChild(row);
  }
}

function renderHistoryTable() {
  if (!historyTableHead || !historyTableBody || !historyTableEmpty) return;

  const tabName = historyState.activeTab;
  renderHistorySummary();
  buildHistoryTableHead(tabName);

  if (historyState.loading[tabName]) {
    setHistoryEmptyState(`Memuat riwayat ${getHistoryTabLabel(tabName)}...`);
    return;
  }

  if (historyState.errors[tabName]) {
    setHistoryEmptyState(`Gagal memuat riwayat ${getHistoryTabLabel(tabName)}.`);
    return;
  }

  const filteredItems = getFilteredHistoryItems(tabName);
  historyTableBody.innerHTML = '';

  if (!filteredItems.length) {
    const baseMessage = historyState.items[tabName].length
      ? 'Tidak ada data yang cocok dengan filter saat ini.'
      : HISTORY_CONFIG[tabName].emptyMessage;
    setHistoryEmptyState(baseMessage);
    return;
  }

  clearHistoryEmptyState();
  if (tabName === 'messages') {
    renderMessageHistoryRows(filteredItems);
  } else {
    renderCallHistoryRows(filteredItems);
  }
}

async function fetchHistoryData(tabName) {
  const response = await fetch(HISTORY_CONFIG[tabName].endpoint);
  if (!response.ok) throw new Error(`Gagal memuat riwayat ${getHistoryTabLabel(tabName)}`);
  return response.json();
}

async function ensureHistoryData(tabName, force = false) {
  if (historyState.loading[tabName]) return;
  if (historyState.loaded[tabName] && !force) return;

  historyState.loading[tabName] = true;
  historyState.errors[tabName] = '';
  renderHistoryTable();

  try {
    const payload = await fetchHistoryData(tabName);
    historyState.items[tabName] = payload.items || [];
    historyState.summary[tabName] = payload.summary || null;
    historyState.loaded[tabName] = true;
  } catch (error) {
    historyState.errors[tabName] = error.message || `Gagal memuat riwayat ${getHistoryTabLabel(tabName)}`;
    historyState.summary[tabName] = null;
    setPageStatus(historyState.errors[tabName], 'warning');
  } finally {
    historyState.loading[tabName] = false;
    syncHistoryFilterOptions();
    renderHistoryTable();
  }
}

function activateHistoryTab(tabName) {
  historyState.activeTab = tabName === 'messages' ? 'messages' : 'calls';

  for (const button of historyTabButtons) {
    const isActive = button.dataset.historyTab === historyState.activeTab;
    button.classList.toggle('is-active', isActive);
    button.setAttribute('aria-selected', isActive ? 'true' : 'false');
  }

  syncHistoryFilterOptions();
  renderHistoryTable();
  void ensureHistoryData(historyState.activeTab);
}

uploadBtn.addEventListener('click', async () => {
  setButtonBusy(uploadBtn, 'Uploading...', true);
  try {
    await uploadDocuments();
    await refreshKnowledgeSummary();
    setPageStatus('Upload dokumen selesai', 'active');
  } catch (error) {
    setPageStatus('Warning: upload dokumen gagal', 'warning');
  } finally {
    setButtonBusy(uploadBtn, 'Uploading...', false);
  }
});

reindexBtn.addEventListener('click', async () => {
  setButtonBusy(reindexBtn, 'Reindexing...', true);
  try {
    await triggerReindex();
    await refreshKnowledgeSummary();
  } catch (error) {
    setPageStatus('Warning: reindex gagal', 'warning');
  } finally {
    setButtonBusy(reindexBtn, 'Reindexing...', false);
  }
});

refreshStatusBtn.addEventListener('click', async () => {
  setButtonBusy(refreshStatusBtn, 'Refreshing...', true);
  try {
    await refreshKnowledgeSummary();
  } catch (error) {
    setPageStatus('Warning: refresh knowledge gagal', 'warning');
  } finally {
    setButtonBusy(refreshStatusBtn, 'Refreshing...', false);
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

if (knowledgeSearchInput) {
  knowledgeSearchInput.addEventListener('input', () => {
    if (latestKnowledgeSummary) {
      renderKnowledgeTable(latestKnowledgeSummary);
    }
  });
}

if (knowledgeStatusFilter) {
  knowledgeStatusFilter.addEventListener('change', () => {
    if (latestKnowledgeSummary) {
      renderKnowledgeTable(latestKnowledgeSummary);
    }
  });
}

if (historySearchInput) {
  historySearchInput.addEventListener('input', () => {
    renderHistoryTable();
  });
}

if (historyStatusFilter) {
  historyStatusFilter.addEventListener('change', () => {
    renderHistoryTable();
  });
}

if (sidebarDrawerBtn) {
  sidebarDrawerBtn.addEventListener('click', () => {
    toggleSidebarDrawer();
  });
}

if (sidebarToggleBtn) {
  sidebarToggleBtn.addEventListener('click', () => {
    toggleSidebarCollapse();
  });
}

if (adminSidebarOverlay) {
  adminSidebarOverlay.addEventListener('click', () => {
    closeSidebarDrawer();
  });
}

for (const historyTabButton of historyTabButtons) {
  historyTabButton.addEventListener('click', () => {
    activateHistoryTab(historyTabButton.dataset.historyTab || 'calls');
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

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && isMobileSidebarMode()) {
    closeSidebarDrawer();
  }
});

if (mobileSidebarQuery && typeof mobileSidebarQuery.addEventListener === 'function') {
  mobileSidebarQuery.addEventListener('change', () => {
    syncSidebarLayout();
  });
}

(async () => {
  try {
    syncSidebarLayout();
    activateHistoryTab('calls');
    activateView(getViewFromHash());
    await refreshKnowledgeSummary();
    if (getViewFromHash() === 'history') {
      await ensureHistoryData(historyState.activeTab);
    }
    setPageStatus('Admin Active', 'active');
  } catch (error) {
    setPageStatus('Warning: gagal memuat panel admin', 'warning');
  }
})();
