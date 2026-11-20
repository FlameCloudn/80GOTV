import { byId, closeDialog, onRefresh, refreshBundle, root, state } from '../features/admin-operations/context.mjs';
import { bindStatistics, loadStatsTarget, populateStatsSelectors } from '../features/admin-operations/statistics.mjs';
import { loadLiveReference, renderResultsTab } from '../features/admin-operations/results.mjs';
import { bindRunDialogs, openBatchParticipationModal, openBindDirectorModal, openDirectorReceiptsModal, openRecordParticipationModal, openReviewParticipationModal, openStartRunModal, openTechReplayModal } from '../features/admin-operations/run-dialogs.mjs';
import { bindDemos, loadDemoAnalyses, openAnalysisPreview, populateDemoUploadSelectors, renderDemosList, triggerDemoParse } from '../features/admin-operations/demos.mjs';
import { bindResultDialogs, openConfirmMapModal, openSeriesActionModal } from '../features/admin-operations/result-dialogs.mjs';
import { renderAuthCard, renderFrozenRoster, renderMapsAndRuns, renderSummary } from '../features/admin-operations/runs.mjs';

/* ==================== Tab 切换 ==================== */
function setActiveTab(tabName, updateHash) {
  var valid = ['runs', 'demos', 'results', 'stats'];
  if (valid.indexOf(tabName) === -1) tabName = 'runs';
  state.tab = tabName;
  root.querySelectorAll('[data-ops-tab]').forEach(function (btn) {
    var active = btn.dataset.opsTab === tabName;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
    btn.tabIndex = active ? 0 : -1;
  });
  root.querySelectorAll('[data-ops-pane]').forEach(function (pane) {
    var active = pane.dataset.opsPane === tabName;
    pane.hidden = !active;
    pane.classList.toggle('active', active);
  });
  if (updateHash) {
    try {
      history.replaceState(null, '', '#' + tabName);
    } catch (_e) {}
  }
  if (tabName === 'stats' && !state.statsLoaded && state.statsTarget.runId && state.statsTarget.playerId) {
    loadStatsTarget();
  }
  if (tabName === 'results') loadLiveReference();
}

function renderAll() {
  renderSummary();
  renderAuthCard();
  renderFrozenRoster();
  renderMapsAndRuns();
  populateDemoUploadSelectors();
  renderDemosList();
  renderResultsTab();
  if (state.tab === 'results') loadLiveReference();
  populateStatsSelectors();
  if (state.tab === 'stats' && state.statsTarget.runId && state.statsTarget.playerId) {
    loadStatsTarget(true);
  }
}
function bindPage() {
  window.setInterval(function () {
    if (state.tab === 'results' && !document.hidden) loadLiveReference();
  }, 5000);
  var tabs = Array.from(root.querySelectorAll('[data-ops-tab]'));
  tabs.forEach(function (btn, index) {
    btn.addEventListener('click', function () {
      setActiveTab(btn.dataset.opsTab, true);
    });
    btn.addEventListener('keydown', function (event) {
      var next = {ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index + tabs.length - 1) % tabs.length,
        Home: 0, End: tabs.length - 1}[event.key];
      if (next === undefined) return;
      event.preventDefault();
      tabs[next].focus();
      setActiveTab(tabs[next].dataset.opsTab, true);
    });
  });

  byId('opsRefreshBtn').addEventListener('click', function () {
    refreshBundle(false);
  });
  // Dialog close buttons
  root.querySelectorAll('[data-close-dialog]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      closeDialog(btn.dataset.closeDialog);
    });
  });

  // Dynamic action buttons inside panes
  root.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var act = btn.dataset.action;
    if (act === 'open-start-run') {
      openStartRunModal(Number(btn.dataset.mapId), btn.dataset.prevRunId ? Number(btn.dataset.prevRunId) : null);
    } else if (act === 'bind-director') {
      openBindDirectorModal(Number(btn.dataset.runId), Number(btn.dataset.mapId));
    } else if (act === 'view-receipts') {
      openDirectorReceiptsModal(Number(btn.dataset.runId));
    } else if (act === 'open-participation') {
      openRecordParticipationModal(Number(btn.dataset.runId));
    } else if (act === 'open-batch-participation') {
      openBatchParticipationModal(Number(btn.dataset.runId));
    } else if (act === 'quick-participation') {
      openRecordParticipationModal(Number(btn.dataset.runId), Number(btn.dataset.playerId), Number(btn.dataset.partyId));
    } else if (act === 'review-participation') {
      openReviewParticipationModal(
        Number(btn.dataset.partId),
        btn.dataset.present === '1',
        Number(btn.dataset.rev),
        btn.dataset.playerName || ''
      );
    } else if (act === 'open-tech-replay') {
      openTechReplayModal(Number(btn.dataset.runId), Number(btn.dataset.mapId));
    } else if (act === 'jump-stats') {
      state.statsTarget.runId = Number(btn.dataset.runId);
      state.statsTarget.playerId = Number(btn.dataset.playerId);
      populateStatsSelectors();
      setActiveTab('stats', true);
      if (state.statsLoaded) loadStatsTarget(false);
    } else if (act === 'parse-demo') {
      btn.disabled = true;
      triggerDemoParse(Number(btn.dataset.demoId)).finally(function () { btn.disabled = false; });
    } else if (act === 'toggle-analyses') {
      loadDemoAnalyses(Number(btn.dataset.demoId));
    } else if (act === 'preview-analysis') {
      openAnalysisPreview(Number(btn.dataset.analysisId));
    } else if (act === 'open-confirm-map') {
      openConfirmMapModal(Number(btn.dataset.mapId));
    } else if (act === 'open-series-settle') {
      openSeriesActionModal('settle');
    } else if (act === 'open-series-reopen') {
      openSeriesActionModal('reopen');
    }
  });
}

onRefresh(renderAll);
bindPage();
bindDemos();
bindStatistics();
bindRunDialogs();
bindResultDialogs();
renderAll();
setActiveTab(location.hash.slice(1) || 'runs', false);
