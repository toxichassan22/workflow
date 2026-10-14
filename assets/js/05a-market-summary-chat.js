    /* 05a-market-summary-chat.js - per-axis discuss/research chat for the market summary.
       Threads and stale flags live inside the market-study draft state so they
       persist and autosave with everything else: state.summaryChat[axis] holds
       the turns and state.summaryStale marks aggregate outputs (one_block,
       decision, swot) that need a consolidate pass. */

    const MARKET_SUMMARY_CHAT_GENERAL = 'general';
    const MARKET_SUMMARY_CHAT_HISTORY_SEND = 12;
    const MARKET_SUMMARY_CHAT_HISTORY_KEEP = 40;
    const MARKET_SUMMARY_CHAT_SECTION_KEY = 'section-market-study';
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
    let marketSummaryChatAxis = MARKET_SUMMARY_CHAT_GENERAL;
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
      if (turn.searchPerformed) {
        meta = '<div class="tenant-hint">' + escapeHtml(WFT('summary_chat.searched', 'شمل بحث ويب')) + '</div>';
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
      const axes = marketSummaryChatAxes();
      if (!axes.some(item => item.key === marketSummaryChatAxis)) marketSummaryChatAxis = MARKET_SUMMARY_CHAT_GENERAL;
      const axis = marketSummaryChatAxis;
      const thread = marketSummaryChatThread(state, axis);
      const canDiscuss = marketSummaryChatCanDiscuss(state);
      const staleKeys = Object.keys(state.summaryStale || {}).filter(key => state.summaryStale[key]);
      const chips = '<div class="market-source-tabs market-summary-chat-axes" role="tablist">' +
        axes.map(item =>
          '<button type="button" class="market-source-tab' + (item.key === axis ? ' active' : '') + '"' +
          ' role="tab" aria-selected="' + (item.key === axis ? 'true' : 'false') + '"' +
          ' onclick="selectMarketSummaryChatAxis(\'' + item.key + '\')">' +
          escapeHtml(marketSummaryChatAxisLabel(item.key)) + '</button>'
        ).join('') + '</div>';
      let log = '<div class="best-use-chat-messages market-summary-chat-messages" id="marketSummaryChatLog" role="log" aria-live="polite">';
      if (!marketSummaryHasContent(state.summary)) {
        log += '<div class="tenant-hint">' + escapeHtml(WFT('summary_chat.empty', 'لم يُولَّد ملخص السوق بعد.')) + '</div>';
      } else {
        log += thread.map((turn, index) => marketSummaryChatTurnHtml(turn, axis, index, state, locked)).join('');
        if (marketSummaryChatBusy) {
          log += '<div class="best-use-chat-message assistant"><div class="best-use-chat-text market-summary-chat-pending">' +
            escapeHtml(marketSummaryChatProgress || WFT('summary_chat.sending', 'جاري معالجة الرسالة...')) + '</div></div>';
        }
      }
      log += '</div>';
      const staleNames = staleKeys.map(key =>
        WFT(MARKET_SUMMARY_CHAT_STALE_LABEL_KEYS[key] || '', MARKET_SUMMARY_CHAT_STALE_FALLBACKS[key] || key));
      const staleBar = '<div class="market-summary-chat-stale"' + (staleKeys.length ? '' : ' hidden') + '>' +
        '<span class="tenant-hint">' + escapeHtml(WFT('summary_chat.stale_for', 'يحتاج تحديثًا: {items}', { items: staleNames.join('، ') })) + '</span>' +
        '<button type="button" class="btn primary small" onclick="runMarketSummaryConsolidate()"' +
        (locked || marketSummaryChatBusy ? ' disabled' : '') + '>' +
        escapeHtml(WFT('summary_chat.consolidate', 'تحديث الملخص التنفيذي')) + '</button></div>';
      const lockNote = locked
        ? '<span class="best-use-status market-summary-chat-lock">' + escapeHtml(WFT('summary_chat.locked', 'الملخص معتمد — التعديلات مقفلة.')) + '</span>'
        : '';
      const composerDisabled = !canDiscuss || marketSummaryChatBusy;
      const composer = '<div class="market-summary-chat-composer">' +
        '<label for="marketSummaryChatInput">' + escapeHtml(WFT('summary_chat.message', 'الرسالة')) + '</label>' +
        '<textarea id="marketSummaryChatInput" rows="3" maxlength="4000" dir="auto"' +
        (composerDisabled ? ' disabled' : '') + ' data-section-lock-ignore="1"></textarea>' +
        '<div class="best-use-actions">' +
        '<label class="market-summary-chat-research"><input type="checkbox" id="marketSummaryChatResearch"' +
        (marketSummaryChatResearchOn ? ' checked' : '') + (composerDisabled ? ' disabled' : '') +
        ' data-section-lock-ignore="1"> ' + escapeHtml(WFT('summary_chat.research', 'بحث الويب')) + '</label>' +
        '<button type="button" class="btn primary small" onclick="sendMarketSummaryChat()"' +
        (composerDisabled ? ' disabled' : '') + ' data-section-lock-ignore="1">' +
        escapeHtml(WFT('summary_chat.send', 'إرسال')) + '</button>' +
        '</div></div>';
      return '<div class="best-use-proposal-heading"><h4>' + escapeHtml(WFT('summary_chat.title', 'مناقشة ملخص السوق')) + '</h4>' +
        lockNote + '</div>' + chips + log + staleBar + composer;
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
        escapeHtml(WFT('summary_chat.title', 'مناقشة ملخص السوق')) + '">' +
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

    function selectMarketSummaryChatAxis(axis) {
      marketSummaryChatAxis = String(axis || MARKET_SUMMARY_CHAT_GENERAL);
      renderMarketSummaryChat();
    }

    async function sendMarketSummaryChat() {
      if (marketSummaryChatBusy) return;
      const input = document.getElementById('marketSummaryChatInput');
      const message = String(input ? input.value : '').trim();
      if (!message) return;
      persistMarketStudyFromDom();
      const axis = marketSummaryChatAxis;
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
        payload.axis = axis === MARKET_SUMMARY_CHAT_GENERAL ? '' : axis;
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
      marketSummaryChatProgress = WFT('summary_chat.consolidating', 'جاري تحديث المخرجات المعلّمة...');
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
          toast(WFT('summary_chat.consolidated', 'تم تحديث المخرجات المعلّمة'));
        } else {
          toast(String(res && (res.error || res.message) || WFT('summary_chat.consolidate_failed', 'تعذر تحديث المخرجات المعلّمة.')));
        }
      } catch (error) {
        toast(String(error && error.message || WFT('summary_chat.consolidate_failed', 'تعذر تحديث المخرجات المعلّمة.')));
      } finally {
        marketSummaryChatBusy = false;
        marketSummaryChatProgress = '';
        renderMarketSummaryChat();
      }
    }

    document.addEventListener('wf:lang', () => {
      try { renderMarketSummaryChat(); } catch (e) { /* ignore */ }
    });
