    /* 05a-market-summary-chat.js - floating market-study chat.
       A draggable ball (bottom-left) opens a resizable panel, the same chrome
       the land/plans chats use. There is no axis picker: every message goes
       through the single auto thread and the model names the summary axis it
       answered on (echoed back per turn). Threads and stale flags live inside
       the market-study draft state so they persist and autosave with
       everything else: state.summaryChat.general holds the turns and
       state.summaryStale marks aggregate outputs (one_block, decision, swot)
       that need a consolidate pass. */

    const MARKET_SUMMARY_CHAT_GENERAL = 'general';
    const MARKET_SUMMARY_CHAT_HISTORY_SEND = 12;
    const MARKET_SUMMARY_CHAT_HISTORY_KEEP = 40;
    const MARKET_SUMMARY_CHAT_SECTION_KEY = 'section-market-study';
    const MARKET_SUMMARY_CHAT_POS_KEY = 'marketSummaryChatFabPos';
    const MARKET_SUMMARY_CHAT_SIZE_KEY = 'marketSummaryChatPanelSize';
    const MARKET_SUMMARY_CHAT_FAB_SIZE = 56;
    const MARKET_SUMMARY_CHAT_STALE_LABEL_KEYS = {
      one_block: 'summary_chat.stale_one_block',
      decision: 'summary_chat.stale_decision',
      swot: 'summary_chat.stale_swot'
    };
    const MARKET_SUMMARY_CHAT_STALE_FALLBACKS = {
      one_block: 'ملخص دراسة سوق العمل',
      decision: 'تصنيف القرار',
      swot: 'تحليل SWOT'
    };
    const MARKET_SUMMARY_CHAT_DECISIONS = [
      'فرصة قوية', 'فرصة واعدة بشروط', 'فرصة متوسطة', 'فرصة مرتفعة المخاطر', 'البيانات غير كافية'
    ];
    let marketSummaryChatBusy = false;
    let marketSummaryChatProgress = '';
    let marketSummaryChatResearchOn = true;

    function marketSummaryChatAxes() {
      const general = { key: MARKET_SUMMARY_CHAT_GENERAL, label: WFT('summary_chat.general_axis', 'عام') };
      const axes = (MARKET_STUDY_SUMMARY_SECTIONS || []).map(item => ({ key: item.key, label: item.label }));
      return [general].concat(axes);
    }

    function marketSummaryChatAxisLabel(axis) {
      if (axis === MARKET_SUMMARY_CHAT_GENERAL) return WFT('summary_chat.general_axis', 'عام');
      const item = (MARKET_STUDY_SUMMARY_SECTIONS || []).find(entry => entry.key === axis);
      if (!item) return axis;
      return typeof wfTr === 'function' ? wfTr(item.label) : item.label;
    }

    function marketSummaryChatSwotLabel(key) {
      const item = (MARKET_STUDY_SWOT_SECTIONS || []).find(entry => entry.key === key);
      if (!item) return key;
      return typeof wfTr === 'function' ? wfTr(item.label) : item.label;
    }

    function marketSummaryChatState() {
      const state = getMarketStudyState();
      if (!state.summaryChat || typeof state.summaryChat !== 'object' || Array.isArray(state.summaryChat)) {
        state.summaryChat = {};
      }
      if (!state.summaryStale || typeof state.summaryStale !== 'object' || Array.isArray(state.summaryStale)) {
        state.summaryStale = {};
      }
      // Legacy drafts saved one thread per picked axis — the auto thread folds
      // them into `general` so no history is lost.
      const extra = Object.keys(state.summaryChat)
        .filter(key => key !== MARKET_SUMMARY_CHAT_GENERAL && Array.isArray(state.summaryChat[key]));
      if (extra.length) {
        const merged = marketSummaryChatThread(state, MARKET_SUMMARY_CHAT_GENERAL).slice();
        extra.forEach(key => { merged.push.apply(merged, state.summaryChat[key]); delete state.summaryChat[key]; });
        state.summaryChat[MARKET_SUMMARY_CHAT_GENERAL] = merged.slice(-MARKET_SUMMARY_CHAT_HISTORY_KEEP);
      }
      return state;
    }

    function marketSummaryChatThread(state, axis) {
      const list = state && state.summaryChat ? state.summaryChat[axis] : null;
      return (Array.isArray(list) ? list : [])
        .filter(turn => turn && (turn.role === 'user' || turn.role === 'assistant'));
    }

    function marketSummaryChatPush(state, axis, turn) {
      state.summaryChat[axis] = marketSummaryChatThread(state, axis).concat([turn]).slice(-MARKET_SUMMARY_CHAT_HISTORY_KEEP);
      return state.summaryChat[axis];
    }

    function marketSummaryChatHistory(thread) {
      return (Array.isArray(thread) ? thread : [])
        .slice(-MARKET_SUMMARY_CHAT_HISTORY_SEND)
        .map(turn => ({ role: turn.role, content: String(turn.content || '').slice(0, 4000) }));
    }

    function marketSummaryChatLocked() {
      return tenantProjectSectionStatuses?.[MARKET_SUMMARY_CHAT_SECTION_KEY] === 'approved';
    }

    function marketSummaryChatCanDiscuss(state) {
      return marketSummaryHasContent(state.summary)
        && hasPermission('create_presentation')
        && tenantProjectMode !== 'presentation';
    }

    function summaryChatOpsTouched(ops) {
      const touched = {};
      (Array.isArray(ops) ? ops : []).forEach(op => {
        if (!op || typeof op !== 'object') return;
        if (op.op === 'set_axis') {
          touched.one_block = true;
          touched.decision = true;
          touched.swot = true;
        } else if (op.op === 'set_swot' || op.op === 'set_decision') {
          touched.one_block = true;
        }
      });
      return touched;
    }

    function marketSummaryChatDecisionOptions() {
      const select = document.getElementById('marketDecision');
      const fromDom = Array.from(select ? select.options : [])
        .map(option => String(option.value || option.textContent || '').trim())
        .filter(Boolean);
      return fromDom.length ? fromDom : MARKET_SUMMARY_CHAT_DECISIONS;
    }

    function marketSummaryChatProposalSources(proposal) {
      const fromList = Array.isArray(proposal && proposal.sourcesAdd) ? proposal.sourcesAdd : [];
      const fromOps = (Array.isArray(proposal && proposal.ops) ? proposal.ops : [])
        .filter(op => op && op.op === 'add_sources')
        .flatMap(op => Array.isArray(op.rows) ? op.rows : []);
      const seen = new Set();
      return fromList.concat(fromOps)
        .filter(row => row && (String(row.name || '').trim() || String(row.url || '').trim()))
        .filter(row => {
          const url = String(row.url || '').trim().toLowerCase();
          if (!url || !seen.has(url)) {
            if (url) seen.add(url);
            return true;
          }
          return false;
        });
    }

    function applySummaryChatOps(state, proposal) {
      // Mirrors market_study.apply_summary_ops + summary_ops_stale: validates each
      // op against the known key whitelists, merges proposed sources through the
      // existing source merge, and flags the dependents that went stale.
      const next = {
        ...(state || {}),
        summary: { ...(state && state.summary) },
        swot: { ...(state && state.swot) },
        sources: Array.isArray(state && state.sources) ? state.sources.slice() : [],
        summaryStale: { ...(state && state.summaryStale) },
        summaryChat: (state && state.summaryChat) || {}
      };
      const summaryKeys = new Set((MARKET_STUDY_SUMMARY_SECTIONS || []).map(item => item.key));
      const swotKeys = new Set((MARKET_STUDY_SWOT_SECTIONS || []).map(item => item.key));
      const decisions = marketSummaryChatDecisionOptions();
      const ops = Array.isArray(proposal && proposal.ops) ? proposal.ops : [];
      ops.forEach(op => {
        if (!op || typeof op !== 'object') return;
        if (op.op === 'set_axis' && summaryKeys.has(op.key)) {
          next.summary[op.key] = String(op.value || '').trim();
        } else if (op.op === 'set_swot' && swotKeys.has(op.key)) {
          next.swot[op.key] = String(op.value || '').trim();
        } else if (op.op === 'set_decision') {
          const value = String(op.value || '').trim();
          if (decisions.includes(value)) next.decision = value;
        }
      });
      const sourceRows = marketSummaryChatProposalSources(proposal);
      const existingUrls = new Set(next.sources
        .map(row => String(row.url || '').trim().toLowerCase()).filter(Boolean));
      const freshRows = sourceRows.filter(row => {
        const url = String(row.url || '').trim().toLowerCase();
        return url && !existingUrls.has(url);
      });
      if (freshRows.length) next.sources = mergeMarketSourceRows(next.sources, freshRows);
      Object.assign(next.summaryStale, summaryChatOpsTouched(ops));
      return next;
    }

    function marketSummaryChatTurnHtml(turn, axis, index, state, locked) {
      const role = turn.role === 'user' ? 'user' : 'assistant';
      const body = escapeHtml(String(turn.content || '')).replace(/\n/g, '<br>');
      let meta = '';
      if (turn.axis) {
        meta = '<div class="tenant-hint market-summary-chat-axistag">' +
          escapeHtml(WFT('summary_chat.axis_detected', 'المحور: {axis}', { axis: marketSummaryChatAxisLabel(turn.axis) })) + '</div>';
      }
      if (turn.searchPerformed) {
        meta += '<div class="tenant-hint">' + escapeHtml(WFT('summary_chat.searched', 'شمل بحث ويب')) + '</div>';
      }
      let html = '<div class="best-use-chat-message ' + role + (turn.error ? ' error' : '') + '">' +
        '<div class="best-use-chat-text">' + body + '</div>' + meta + '</div>';
      if (turn.proposal && Array.isArray(turn.proposal.ops) && turn.proposal.ops.length) {
        html += marketSummaryChatProposalHtml(turn, axis, index, state, locked);
      }
      return html;
    }

    function marketSummaryChatProposalItemHtml(label, current, proposed) {
      return '<div class="market-summary-proposal-item">' +
        '<span class="market-summary-proposal-label">' + escapeHtml(label) + '</span>' +
        '<div class="summary-compare">' +
        '<div><label>' + escapeHtml(WFT('summary_chat.current_text', 'النص الحالي')) + '</label>' +
        '<div class="market-summary-proposal-text">' + (escapeHtml(String(current || '').trim()) || '—') + '</div></div>' +
        '<div><label>' + escapeHtml(WFT('summary_chat.proposed_text', 'النص المقترح')) + '</label>' +
        '<div class="market-summary-proposal-text">' + (escapeHtml(String(proposed || '').trim()) || '—') + '</div></div>' +
        '</div></div>';
    }

    function marketSummaryChatProposalHtml(turn, axis, index, state, locked) {
      const proposal = turn.proposal || {};
      const status = turn.proposalStatus || 'pending';
      const items = (proposal.ops || []).map(op => {
        if (op.op === 'set_axis') {
          return marketSummaryChatProposalItemHtml(
            marketSummaryChatAxisLabel(op.key),
            (state.summary || {})[op.key] || '',
            op.value);
        }
        if (op.op === 'set_swot') {
          return marketSummaryChatProposalItemHtml(
            marketSummaryChatSwotLabel(op.key),
            (state.swot || {})[op.key] || '',
            op.value);
        }
        if (op.op === 'set_decision') {
          return marketSummaryChatProposalItemHtml(
            WFT('summary_chat.decision_label', 'تصنيف القرار'),
            state.decision || '',
            op.value);
        }
        return '';
      }).filter(Boolean).join('');
      const sourceRows = marketSummaryChatProposalSources(proposal);
      const sourcesHtml = sourceRows.length
        ? '<div class="market-summary-proposal-item"><span class="market-summary-proposal-label">' +
          escapeHtml(WFT('summary_chat.new_sources', 'مصادر جديدة')) + '</span><div>' +
          sourceRows.map(row => {
            const url = String(row.url || '').trim();
            const name = escapeHtml(String(row.name || '').trim() || url);
            const link = /^https?:\/\//i.test(url)
              ? ' <a href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(url) + '</a>'
              : '';
            const extra = [row.data_date, row.note].map(value => String(value || '').trim()).filter(Boolean)
              .map(value => escapeHtml(value)).join(' — ');
            return '<div class="tenant-hint market-summary-proposal-source">' + name + link +
              (extra ? ' — ' + extra : '') + '</div>';
          }).join('') + '</div></div>'
        : '';
      let actionsHtml = '';
      if (status === 'applied') {
        actionsHtml = '<span class="best-use-status">' + escapeHtml(WFT('summary_chat.applied', 'طُبّق')) + '</span>';
      } else if (status === 'dismissed') {
        actionsHtml = '<span class="best-use-status">' + escapeHtml(WFT('summary_chat.dismissed', 'تم التجاهل')) + '</span>';
      } else {
        actionsHtml = '<div class="best-use-actions">' +
          '<button type="button" class="btn primary small" onclick="applyMarketSummaryChatProposal(\'' + axis + '\', ' + index + ')"' +
          (locked || marketSummaryChatBusy ? ' disabled' : '') + '>' + escapeHtml(WFT('summary_chat.apply', 'طبّق')) + '</button>' +
          '<button type="button" class="btn ghost small" onclick="dismissMarketSummaryChatProposal(\'' + axis + '\', ' + index + ')"' +
          (marketSummaryChatBusy ? ' disabled' : '') + '>' + escapeHtml(WFT('summary_chat.dismiss', 'تجاهل')) + '</button>' +
          '</div>';
      }
      return '<div class="best-use-source market-summary-proposal" data-chat-proposal>' +
        '<span class="market-summary-proposal-label">' + escapeHtml(WFT('summary_chat.proposal', 'تعديلات مقترحة')) + '</span>' +
        items + sourcesHtml + actionsHtml + '</div>';
    }

    function marketSummaryChatHtml(state) {
      const locked = marketSummaryChatLocked();
      const axis = MARKET_SUMMARY_CHAT_GENERAL;
      const thread = marketSummaryChatThread(state, axis);
      const canDiscuss = marketSummaryChatCanDiscuss(state);
      const staleKeys = Object.keys(state.summaryStale || {}).filter(key => state.summaryStale[key]);
      let log = '<div class="best-use-chat-messages market-summary-chat-messages" id="marketSummaryChatLog" role="log" aria-live="polite">';
      if (!marketSummaryHasContent(state.summary)) {
        log += '<div class="land-chat-empty">' + escapeHtml(WFT('summary_chat.empty', 'لم يُولَّد ملخص السوق بعد.')) + '</div>';
      } else {
        log += thread.map((turn, index) => marketSummaryChatTurnHtml(turn, axis, index, state, locked)).join('');
        if (marketSummaryChatBusy) {
          log += '<div class="best-use-chat-message assistant"><div class="best-use-chat-text market-summary-chat-pending">' +
            escapeHtml(marketSummaryChatProgress || WFT('summary_chat.sending', 'جاري معالجة الرسالة...')) + '</div></div>';
        } else if (!thread.length) {
          log += '<div class="land-chat-empty">' + escapeHtml(WFT('summary_chat.thread_empty', 'لا توجد رسائل في هذه المحادثة.')) + '</div>';
        }
      }
      log += '</div>';
      const staleNames = staleKeys.map(key =>
        WFT(MARKET_SUMMARY_CHAT_STALE_LABEL_KEYS[key] || '', MARKET_SUMMARY_CHAT_STALE_FALLBACKS[key] || key));
      const staleBar = '<div class="market-summary-chat-stale"' + (staleKeys.length ? '' : ' hidden') + '>' +
        '<div class="market-summary-chat-stale-text">' +
        '<span class="market-summary-chat-stale-title">' + escapeHtml(WFT('summary_chat.stale_title', 'مخرجات تحتاج تحديثًا')) + '</span>' +
        '<span class="market-summary-chat-stale-items">' + escapeHtml(staleNames.join('، ')) + '</span>' +
        '</div>' +
        '<button type="button" class="btn primary small" onclick="runMarketSummaryConsolidate()"' +
        (locked || marketSummaryChatBusy ? ' disabled' : '') + '>' +
        escapeHtml(WFT('summary_chat.consolidate', 'تحديث المخرجات')) + '</button></div>';
      const lockNote = locked
        ? '<div><span class="best-use-status market-summary-chat-lock">' + escapeHtml(WFT('summary_chat.locked', 'الملخص معتمد — التعديلات مقفلة.')) + '</span></div>'
        : '';
      const composerDisabled = !canDiscuss || marketSummaryChatBusy;
      const composer = '<div class="market-summary-chat-composer">' +
        '<textarea id="marketSummaryChatInput" rows="2" maxlength="4000" dir="auto"' +
        ' placeholder="' + escapeHtml(WFT('summary_chat.message', 'الرسالة')) + '"' +
        (composerDisabled ? ' disabled' : '') + ' data-section-lock-ignore="1"></textarea>' +
        '<div class="market-summary-chat-composer-foot">' +
        '<label class="market-summary-chat-research"><input type="checkbox" id="marketSummaryChatResearch"' +
        (marketSummaryChatResearchOn ? ' checked' : '') + (composerDisabled ? ' disabled' : '') +
        ' data-section-lock-ignore="1"> ' + escapeHtml(WFT('summary_chat.research', 'بحث الويب')) + '</label>' +
        '<button type="button" class="btn primary small" onclick="sendMarketSummaryChat()"' +
        (composerDisabled ? ' disabled' : '') + ' data-section-lock-ignore="1">' +
        escapeHtml(WFT('summary_chat.send', 'إرسال')) + '</button>' +
        '</div></div>';
      return lockNote + log + staleBar + composer;
    }

    function marketSummaryChatStaleTargets() {
      const oneBlock = document.getElementById('marketStudyOneBlockSummary');
      const decision = document.getElementById('marketDecision');
      const swot = document.getElementById('marketSwotFields');
      return {
        one_block: oneBlock ? (oneBlock.closest('.market-block') || oneBlock.parentElement) : null,
        decision: decision ? decision.parentElement : null,
        swot: swot ? swot.previousElementSibling : null
      };
    }

    function marketSummaryChatSyncStaleBadges(state) {
      const stale = (state && state.summaryStale) || {};
      Object.entries(marketSummaryChatStaleTargets()).forEach(([key, host]) => {
        if (!host) return;
        const labelHost = key === 'one_block' ? host.querySelector('h4') || host
          : key === 'decision' ? host.querySelector('label') || host
            : host;
        let badge = labelHost.querySelector('.market-summary-stale-tag');
        if (stale[key] && !badge) {
          badge = document.createElement('span');
          badge.className = 'tenant-hint market-summary-stale-tag';
          labelHost.appendChild(badge);
        }
        if (badge) {
          badge.hidden = !stale[key];
          badge.textContent = stale[key] ? WFT('summary_chat.stale', 'يحتاج تحديثًا') : '';
        }
      });
    }

    function renderMarketSummaryChat() {
      const host = document.getElementById('marketSummaryChat');
      if (!host) return;
      const input = document.getElementById('marketSummaryChatInput');
      const savedMessage = input ? input.value : '';
      const state = marketSummaryChatState();
      host.innerHTML = '<section class="best-use-chat market-summary-chat" aria-label="' +
        escapeHtml(WFT('summary_chat.fab_label', 'شات دراسة السوق')) + '">' +
        marketSummaryChatHtml(state) + '</section>';
      const nextInput = document.getElementById('marketSummaryChatInput');
      if (nextInput) {
        nextInput.value = savedMessage;
        nextInput.addEventListener('keydown', event => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendMarketSummaryChat();
          }
        });
        nextInput.addEventListener('input', persistMarketStudyFromDom);
      }
      const research = document.getElementById('marketSummaryChatResearch');
      if (research) research.addEventListener('change', () => { marketSummaryChatResearchOn = research.checked; });
      marketSummaryChatSyncStaleBadges(state);
      const log = document.getElementById('marketSummaryChatLog');
      if (log) log.scrollTop = log.scrollHeight;
      if (typeof refreshDynamicI18n === 'function') refreshDynamicI18n(host);
    }

    // --- Floating chrome: draggable ball + resizable panel (same pattern as plans chat) ---

    function marketSummaryChatClampFabPosition(left, top) {
      const margin = 8;
      const maxLeft = Math.max(margin, window.innerWidth - MARKET_SUMMARY_CHAT_FAB_SIZE - margin);
      const maxTop = Math.max(margin, window.innerHeight - MARKET_SUMMARY_CHAT_FAB_SIZE - margin);
      return {
        left: Math.min(Math.max(left, margin), maxLeft),
        top: Math.min(Math.max(top, margin), maxTop)
      };
    }

    function marketSummaryChatDefaultFabPosition() {
      const host = document.body || document.documentElement;
      const rtl = getComputedStyle(host).direction === 'rtl';
      return marketSummaryChatClampFabPosition(
        rtl ? 18 : window.innerWidth - 18 - MARKET_SUMMARY_CHAT_FAB_SIZE,
        window.innerHeight - 18 - MARKET_SUMMARY_CHAT_FAB_SIZE);
    }

    function marketSummaryChatFabPosition() {
      try {
        const saved = JSON.parse(localStorage.getItem(MARKET_SUMMARY_CHAT_POS_KEY) || 'null');
        if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
          return marketSummaryChatClampFabPosition(saved.left, saved.top);
        }
      } catch (error) {}
      return marketSummaryChatDefaultFabPosition();
    }

    function marketSummaryChatApplyFabPosition(pos, persist) {
      const fab = document.getElementById('marketSummaryChatFab');
      if (!fab) return;
      const clamped = marketSummaryChatClampFabPosition(pos.left, pos.top);
      // inset-inline-end must be cleared BEFORE left/top: in RTL it maps to the
      // physical left edge, and the last declaration wins the edge.
      fab.style.insetInlineEnd = 'auto';
      fab.style.right = 'auto';
      fab.style.bottom = 'auto';
      fab.style.left = clamped.left + 'px';
      fab.style.top = clamped.top + 'px';
      if (persist) {
        try { localStorage.setItem(MARKET_SUMMARY_CHAT_POS_KEY, JSON.stringify(clamped)); } catch (error) {}
      }
      const panel = document.getElementById('marketSummaryChatPanel');
      if (panel && !panel.hidden) marketSummaryChatPositionPanel();
    }

    function marketSummaryChatPositionPanel() {
      const panel = document.getElementById('marketSummaryChatPanel');
      const fab = document.getElementById('marketSummaryChatFab');
      if (!panel || panel.hidden || !fab) return;
      const rect = fab.getBoundingClientRect();
      const width = panel.offsetWidth || Math.min(400, window.innerWidth - 24);
      const height = panel.offsetHeight || Math.min(480, window.innerHeight - 96);
      const gap = 10;
      let top = rect.top - gap - height;
      if (top < 12) top = rect.bottom + gap;
      top = Math.max(12, Math.min(top, window.innerHeight - height - 12));
      const left = Math.max(12, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 12));
      panel.style.insetInlineEnd = 'auto';
      panel.style.right = 'auto';
      panel.style.bottom = 'auto';
      panel.style.left = left + 'px';
      panel.style.top = top + 'px';
    }

    function marketSummaryChatBindFabDrag(fab) {
      let startX = 0;
      let startY = 0;
      let startLeft = 0;
      let startTop = 0;
      let dragging = false;
      let pointerId = null;
      let suppressClick = false;
      fab.addEventListener('pointerdown', (event) => {
        if (event.button !== undefined && event.button !== 0) return;
        pointerId = event.pointerId;
        startX = event.clientX;
        startY = event.clientY;
        const pos = marketSummaryChatFabPosition();
        startLeft = pos.left;
        startTop = pos.top;
        dragging = false;
        try { fab.setPointerCapture(pointerId); } catch (error) {}
        event.preventDefault();
      });
      fab.addEventListener('pointermove', (event) => {
        if (event.pointerId !== pointerId) return;
        const dx = event.clientX - startX;
        const dy = event.clientY - startY;
        if (!dragging && Math.hypot(dx, dy) < 6) return;
        if (!dragging) {
          dragging = true;
          fab.classList.add('dragging');
        }
        marketSummaryChatApplyFabPosition({ left: startLeft + dx, top: startTop + dy }, false);
      });
      const finish = (event) => {
        if (event.pointerId !== pointerId) return;
        pointerId = null;
        suppressClick = dragging;
        if (dragging) {
          fab.classList.remove('dragging');
          const pos = marketSummaryChatClampFabPosition(
            parseFloat(fab.style.left) || 0,
            parseFloat(fab.style.top) || 0);
          try { localStorage.setItem(MARKET_SUMMARY_CHAT_POS_KEY, JSON.stringify(pos)); } catch (error) {}
        }
        dragging = false;
      };
      fab.addEventListener('pointerup', finish);
      fab.addEventListener('pointercancel', finish);
      fab.addEventListener('click', () => {
        if (suppressClick) {
          suppressClick = false;
          return;
        }
        toggleMarketSummaryChat();
      });
    }

    function marketSummaryChatBindResize(panel) {
      const grip = panel.querySelector('#marketSummaryChatResize');
      if (!grip) return;
      let startX = 0;
      let startY = 0;
      let startW = 0;
      let startH = 0;
      let startLeft = 0;
      let pointerId = null;
      grip.addEventListener('pointerdown', (event) => {
        if (event.button !== undefined && event.button !== 0) return;
        pointerId = event.pointerId;
        startX = event.clientX;
        startY = event.clientY;
        const rect = panel.getBoundingClientRect();
        startW = rect.width;
        startH = rect.height;
        startLeft = rect.left;
        try { grip.setPointerCapture(pointerId); } catch (error) {}
        event.preventDefault();
        event.stopPropagation();
      });
      grip.addEventListener('pointermove', (event) => {
        if (event.pointerId !== pointerId) return;
        const rtl = getComputedStyle(panel).direction === 'rtl';
        const dx = event.clientX - startX;
        const dy = event.clientY - startY;
        let width = Math.max(320, Math.min(startW + (rtl ? -dx : dx), window.innerWidth - 24));
        const height = Math.max(260, Math.min(startH + dy, window.innerHeight - 24));
        if (rtl) {
          // The grip sits on the left edge — keep the right edge fixed.
          const left = Math.max(8, Math.min(startLeft + dx, window.innerWidth - width - 8));
          panel.style.left = left + 'px';
          width = Math.min(width, window.innerWidth - left - 8);
        } else {
          width = Math.min(width, window.innerWidth - startLeft - 8);
        }
        panel.style.width = width + 'px';
        panel.style.height = height + 'px';
      });
      const finish = (event) => {
        if (event.pointerId !== pointerId) return;
        pointerId = null;
        try {
          const rect = panel.getBoundingClientRect();
          localStorage.setItem(MARKET_SUMMARY_CHAT_SIZE_KEY, JSON.stringify({ width: rect.width, height: rect.height }));
        } catch (error) {}
      };
      grip.addEventListener('pointerup', finish);
      grip.addEventListener('pointercancel', finish);
    }

    function marketSummaryChatWrapHtml() {
      return '<button type="button" class="land-chat-fab" id="marketSummaryChatFab" aria-label="' +
        escapeHtml(WFT('summary_chat.fab_label', 'شات دراسة السوق')) + '">AI</button>' +
        '<div class="land-chat-panel" id="marketSummaryChatPanel" hidden>' +
        '<div class="land-chat-header">' +
        '<div><div class="land-chat-title" id="marketSummaryChatTitle"></div></div>' +
        '<div class="land-chat-actions">' +
        '<button type="button" class="land-chat-action" id="marketSummaryChatMinimize"' +
        ' title="' + escapeHtml(WFT('summary_chat.minimize', 'إخفاء')) + '"' +
        ' aria-label="' + escapeHtml(WFT('summary_chat.minimize', 'إخفاء')) + '"' +
        ' onclick="toggleMarketSummaryChat(false)">&gt;&lt;</button>' +
        '<button type="button" class="land-chat-action" id="marketSummaryChatEnd"' +
        ' title="' + escapeHtml(WFT('summary_chat.end', 'إنهاء')) + '"' +
        ' aria-label="' + escapeHtml(WFT('summary_chat.end', 'إنهاء')) + '"' +
        ' onclick="showMarketSummaryChatEndConfirm()">×</button>' +
        '</div></div>' +
        '<div class="market-summary-chat-body" id="marketSummaryChat"></div>' +
        '<div class="land-chat-confirm" id="marketSummaryChatConfirm" hidden>' +
        '<div class="land-chat-confirm-card">' +
        '<div class="land-chat-confirm-title">' + escapeHtml(WFT('summary_chat.end_confirm_title', 'هل تريد إنهاء هذه المحادثة؟')) + '</div>' +
        '<div class="land-chat-confirm-body">' + escapeHtml(WFT('summary_chat.end_confirm_body', 'سيبدأ الشات محادثة جديدة عند فتحه مرة أخرى.')) + '</div>' +
        '<button type="button" class="land-chat-confirm-end" id="marketSummaryChatConfirmEnd" onclick="confirmEndMarketSummaryChat()">' +
        escapeHtml(WFT('summary_chat.end_confirm', 'إنهاء المحادثة')) + '</button>' +
        '<button type="button" class="land-chat-confirm-return" id="marketSummaryChatConfirmReturn" onclick="hideMarketSummaryChatEndConfirm()">' +
        escapeHtml(WFT('summary_chat.end_return', 'العودة إلى المحادثة')) + '</button>' +
        '</div></div>' +
        '<div class="land-chat-resize" id="marketSummaryChatResize" aria-hidden="true"></div></div>';
    }

    function mountMarketSummaryChat(sectionHost) {
      const host = sectionHost || document.getElementById(MARKET_SUMMARY_CHAT_SECTION_KEY);
      if (!host || document.getElementById('marketSummaryChatFab')) return;
      const wrap = document.createElement('div');
      wrap.className = 'land-chat-wrap';
      wrap.innerHTML = marketSummaryChatWrapHtml();
      host.appendChild(wrap);
      const fab = wrap.querySelector('#marketSummaryChatFab');
      if (fab) {
        marketSummaryChatBindFabDrag(fab);
        marketSummaryChatApplyFabPosition(marketSummaryChatFabPosition(), false);
      }
      const panel = wrap.querySelector('#marketSummaryChatPanel');
      if (panel) {
        marketSummaryChatBindResize(panel);
        try {
          const size = JSON.parse(localStorage.getItem(MARKET_SUMMARY_CHAT_SIZE_KEY) || 'null');
          if (size && Number.isFinite(size.width) && Number.isFinite(size.height)) {
            panel.style.width = Math.min(size.width, window.innerWidth - 24) + 'px';
            panel.style.height = Math.min(size.height, Math.max(260, window.innerHeight - 96)) + 'px';
          }
        } catch (error) {}
      }
      const title = wrap.querySelector('#marketSummaryChatTitle');
      if (title) title.textContent = WFT('summary_chat.fab_label', 'شات دراسة السوق');
      if (!mountMarketSummaryChat.resizeBound) {
        mountMarketSummaryChat.resizeBound = true;
        window.addEventListener('resize', () => {
          marketSummaryChatApplyFabPosition(marketSummaryChatFabPosition(), false);
          marketSummaryChatPositionPanel();
        });
      }
      renderMarketSummaryChat();
    }

    function toggleMarketSummaryChat(force) {
      const panel = document.getElementById('marketSummaryChatPanel');
      if (!panel) return;
      const open = typeof force === 'boolean' ? force : panel.hidden;
      panel.hidden = !open;
      const fab = document.getElementById('marketSummaryChatFab');
      if (fab) fab.classList.toggle('open', open);
      if (open) {
        hideMarketSummaryChatEndConfirm();
        renderMarketSummaryChat();
        marketSummaryChatPositionPanel();
        const input = document.getElementById('marketSummaryChatInput');
        if (input) input.focus();
      }
    }

    function showMarketSummaryChatEndConfirm() {
      const confirm = document.getElementById('marketSummaryChatConfirm');
      if (confirm) confirm.hidden = false;
    }

    function hideMarketSummaryChatEndConfirm() {
      const confirm = document.getElementById('marketSummaryChatConfirm');
      if (confirm) confirm.hidden = true;
    }

    function confirmEndMarketSummaryChat() {
      const state = marketSummaryChatState();
      state.summaryChat[MARKET_SUMMARY_CHAT_GENERAL] = [];
      setMarketStudyState(state);
      persistMarketStudyFromDom();
      renderMarketSummaryChat();
      hideMarketSummaryChatEndConfirm();
      toggleMarketSummaryChat(false);
    }

    async function sendMarketSummaryChat() {
      if (marketSummaryChatBusy) return;
      const input = document.getElementById('marketSummaryChatInput');
      const message = String(input ? input.value : '').trim();
      if (!message) return;
      persistMarketStudyFromDom();
      const axis = MARKET_SUMMARY_CHAT_GENERAL;
      let state = marketSummaryChatState();
      if (!marketSummaryChatCanDiscuss(state)) {
        toast(WFT('summary_chat.failed', 'تعذر إرسال الرسالة.'));
        return;
      }
      marketSummaryChatPush(state, axis, { role: 'user', content: message.slice(0, 4000) });
      setMarketStudyState(state);
      marketSummaryChatBusy = true;
      marketSummaryChatProgress = '';
      renderMarketSummaryChat();
      try {
        const payload = collectMarketStudyRequestPayload();
        const thread = marketSummaryChatThread(state, axis);
        // Empty axis = auto: the model detects the target axis itself and
        // echoes it back on the reply.
        payload.axis = '';
        payload.message = message;
        payload.research = marketSummaryChatResearchOn ? 'auto' : 'off';
        payload.history = marketSummaryChatHistory(thread.slice(0, -1));
        payload.decision = state.decision || '';
        payload.oneBlockSummary = state.one_block_summary || '';
        let res = await api('POST', '/api/market-study/summary/chat', payload);
        if (res && res.jobId) {
          res = await pollMarketStudyJob(res.jobId, job => {
            marketSummaryChatProgress = String(job && job.message || '');
            const pending = document.querySelector('#marketSummaryChat .market-summary-chat-pending');
            if (pending) pending.textContent = marketSummaryChatProgress;
          });
        }
        state = marketSummaryChatState();
        if (res && res.success && res.reply) {
          const turn = { role: 'assistant', content: String(res.reply) };
          if (res.searchPerformed) turn.searchPerformed = true;
          if (res.axis) turn.axis = String(res.axis);
          if (res.clarification) turn.clarification = true;
          const proposal = res.proposal && Array.isArray(res.proposal.ops) && res.proposal.ops.length ? res.proposal : null;
          if (proposal) {
            turn.proposal = proposal;
            turn.proposalStatus = 'pending';
          }
          marketSummaryChatPush(state, axis, turn);
          const liveInput = document.getElementById('marketSummaryChatInput');
          if (liveInput) liveInput.value = '';
        } else if (marketJobInFlight(res)) {
          marketSummaryChatPush(state, axis, {
            role: 'assistant',
            content: marketJobStillRunningText()
          });
        } else {
          const detail = String(res && (res.error || res.message) || '').trim();
          marketSummaryChatPush(state, axis, {
            role: 'assistant',
            content: detail || WFT('summary_chat.failed', 'تعذر إرسال الرسالة.'),
            error: true
          });
          if (!detail) toast(WFT('summary_chat.failed', 'تعذر إرسال الرسالة.'));
        }
        setMarketStudyState(state);
      } catch (error) {
        state = marketSummaryChatState();
        marketSummaryChatPush(state, axis, {
          role: 'assistant',
          content: String(error && error.message || WFT('summary_chat.failed', 'تعذر إرسال الرسالة.')),
          error: true
        });
        setMarketStudyState(state);
      } finally {
        marketSummaryChatBusy = false;
        marketSummaryChatProgress = '';
        renderMarketSummaryChat();
      }
    }

    function applyMarketSummaryChatProposal(axis, turnIndex) {
      if (marketSummaryChatLocked()) {
        toast(WFT('summary_chat.locked', 'الملخص معتمد — التعديلات مقفلة.'));
        return;
      }
      const state = marketSummaryChatState();
      const thread = marketSummaryChatThread(state, axis);
      const turn = thread[turnIndex];
      if (!turn || !turn.proposal || turn.proposalStatus !== 'pending') return;
      const next = applySummaryChatOps(state, turn.proposal);
      const nextThread = marketSummaryChatThread(next, axis);
      if (nextThread[turnIndex]) nextThread[turnIndex].proposalStatus = 'applied';
      next.summaryChat = { ...(next.summaryChat || {}), [axis]: nextThread };
      setMarketStudyState(next);
      applyMarketStudyState(next);
      persistMarketStudyFromDom();
      toast(WFT('summary_chat.applied_toast', 'طُبّقت التعديلات على الملخص'));
    }

    function dismissMarketSummaryChatProposal(axis, turnIndex) {
      const state = marketSummaryChatState();
      const thread = marketSummaryChatThread(state, axis);
      const turn = thread[turnIndex];
      if (!turn || !turn.proposal || turn.proposalStatus !== 'pending') return;
      state.summaryChat[axis] = thread.slice();
      state.summaryChat[axis][turnIndex] = { ...turn, proposalStatus: 'dismissed' };
      setMarketStudyState(state);
      renderMarketSummaryChat();
    }

    async function runMarketSummaryConsolidate() {
      if (marketSummaryChatBusy) return;
      if (marketSummaryChatLocked()) {
        toast(WFT('summary_chat.locked', 'الملخص معتمد — التعديلات مقفلة.'));
        return;
      }
      persistMarketStudyFromDom();
      let state = marketSummaryChatState();
      const stale = Object.keys(state.summaryStale || {}).filter(key => state.summaryStale[key]);
      if (!stale.length) return;
      marketSummaryChatBusy = true;
      marketSummaryChatProgress = WFT('summary_chat.consolidating', 'جاري تحديث المخرجات...');
      renderMarketSummaryChat();
      try {
        const payload = collectMarketStudyRequestPayload();
        payload.summary = state.summary;
        payload.sources = state.sources;
        payload.swot = state.swot;
        payload.decision = state.decision || '';
        payload.one_block_summary = state.one_block_summary || '';
        payload.stale = stale;
        let res = await api('POST', '/api/market-study/summary/consolidate', payload);
        if (res && res.jobId) {
          res = await pollMarketStudyJob(res.jobId, job => {
            marketSummaryChatProgress = String(job && job.message || marketSummaryChatProgress);
            const pending = document.querySelector('#marketSummaryChat .market-summary-chat-pending');
            if (pending) pending.textContent = marketSummaryChatProgress;
          });
        }
        if (marketJobInFlight(res)) {
          toast(marketJobStillRunningText());
        } else if (res && res.success) {
          const next = marketSummaryChatState();
          if (res.one_block_summary) {
            next.one_block_summary = String(res.one_block_summary).trim();
            delete next.summaryStale.one_block;
          }
          if (res.decision) {
            next.decision = String(res.decision).trim();
            delete next.summaryStale.decision;
          }
          if (res.swot && typeof res.swot === 'object') {
            next.swot = { ...(next.swot || {}), ...res.swot };
            delete next.summaryStale.swot;
          }
          setMarketStudyState(next);
          applyMarketStudyState(next);
          persistMarketStudyFromDom();
          toast(WFT('summary_chat.consolidated', 'تم تحديث المخرجات'));
        } else {
          toast(String(res && (res.error || res.message) || WFT('summary_chat.consolidate_failed', 'تعذر تحديث المخرجات.')));
        }
      } catch (error) {
        toast(String(error && error.message || WFT('summary_chat.consolidate_failed', 'تعذر تحديث المخرجات.')));
      } finally {
        marketSummaryChatBusy = false;
        marketSummaryChatProgress = '';
        renderMarketSummaryChat();
      }
    }

    document.addEventListener('wf:lang', () => {
      try {
        const title = document.getElementById('marketSummaryChatTitle');
        if (title) title.textContent = WFT('summary_chat.fab_label', 'شات دراسة السوق');
        renderMarketSummaryChat();
      } catch (e) { /* ignore */ }
    });
