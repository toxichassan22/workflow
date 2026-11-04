/* 18-landloom-ops/04_wallet_ledger.js — Tenant wallet hero, ledger table,
   package selection and IBAN quick-copy. Shared global scope, classic scripts in order. */

    let llWalletData = null;
    let llActiveWalletCategory = 'all';

    function llCopyIban(customText) {
      const ibanEl = document.getElementById('llWalletIban') || document.getElementById('llWalletIbanMain');
      const text = customText || (ibanEl ? ibanEl.textContent.trim() : 'SA9880000213608010009988');
      if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          toast(WFT('wallet.iban_copied', 'تم نسخ الآيبان إلى الحافظة'));
        }).catch(function () {
          toast(text);
        });
      } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try {
          document.execCommand('copy');
          toast(WFT('wallet.iban_copied', 'تم نسخ الآيبان إلى الحافظة'));
        } catch (e) {
          toast(text);
        }
        document.body.removeChild(ta);
      }
    }

    function setWalletCategory(cat) {
      llActiveWalletCategory = cat || 'all';
      const tabs = document.querySelectorAll('.tenant-wallet-category-tabs button[data-wallet-category]');
      tabs.forEach(function (btn) {
        const isActive = btn.getAttribute('data-wallet-category') === llActiveWalletCategory;
        btn.classList.toggle('primary', isActive);
        btn.classList.toggle('ghost', !isActive);
      });
      const filter = document.getElementById('llRechargeStatusFilter');
      if (filter) {
        filter.value = (cat === 'all' ? '' : cat);
      }
      if (typeof llLoadRechargeRequests === 'function') {
        llLoadRechargeRequests('llRechargeList');
      }
    }

    function llOnRechargeFilterChange() {
      const filter = document.getElementById('llRechargeStatusFilter');
      const val = filter ? filter.value : '';
      const cat = val || 'all';
      llActiveWalletCategory = cat;
      const tabs = document.querySelectorAll('.tenant-wallet-category-tabs button[data-wallet-category]');
      tabs.forEach(function (btn) {
        const isActive = btn.getAttribute('data-wallet-category') === cat;
        btn.classList.toggle('primary', isActive);
        btn.classList.toggle('ghost', !isActive);
      });
      if (typeof llLoadRechargeRequests === 'function') {
        llLoadRechargeRequests('llRechargeList');
      }
    }

    function llUpdateWalletStats(requests) {
      const list = Array.isArray(requests) ? requests : [];
      const totalEl = document.getElementById('llWalletStatTotal');
      const pendingEl = document.getElementById('llWalletStatPending');
      const approvedEl = document.getElementById('llWalletStatApproved');
      const rejectedEl = document.getElementById('llWalletStatRejected');

      let nTotal = list.length;
      let nPending = 0;
      let nApproved = 0;
      let nRejected = 0;

      list.forEach(function (r) {
        if (r.status === 'pending') nPending++;
        else if (r.status === 'approved') nApproved++;
        else if (r.status === 'rejected') nRejected++;
      });

      if (totalEl) totalEl.textContent = String(nTotal);
      if (pendingEl) pendingEl.textContent = String(nPending);
      if (approvedEl) approvedEl.textContent = String(nApproved);
      if (rejectedEl) rejectedEl.textContent = String(nRejected);
    }

    function llRenderWalletCatalog() {
      const container = document.getElementById('llWalletCatalog');
      if (!container) return;
      if (typeof llPackageSliderItems !== 'function') return;
      const items = llPackageSliderItems();
      if (!items || !items.length) {
        container.innerHTML = '<p class="tenant-hint">' + llEscape(WFT('wallet.no_packages', 'لا توجد باقات متاحة حالياً.')) + '</p>';
        return;
      }
      container.innerHTML = '<div class="tenant-wallet-packages-grid">' +
        items.map(function (p) {
          if (typeof llRechargePackageCardHtml === 'function') {
            return llRechargePackageCardHtml(p);
          }
          return '';
        }).join('') +
        '</div>';
    }

    async function llRefreshWallet() {
      if (typeof llFetchPackages === 'function') {
        await llFetchPackages();
      }
      llRenderWalletCatalog();

      const ledgerData = await api('GET', '/api/billing/ledger').catch(function () { return null; });
      if (!ledgerData || !ledgerData.success) {
        const balEl = document.getElementById('llWalletBalance');
        if (balEl && balEl.textContent === '—') {
          balEl.textContent = '0 ' + WFT('wallet.sar_unit', 'ر.س');
        }
        return;
      }

      llWalletData = ledgerData;
      const balSar = Number(ledgerData.balance_sar || 0);
      const pointsObj = ledgerData.points || {};
      const pts = (pointsObj && Number(pointsObj.available_points || pointsObj.balance_points || 0)) || (balSar * 1000);

      const balEl = document.getElementById('llWalletBalance');
      if (balEl) {
        balEl.innerHTML = llEscape(llMoney(balSar)) +
          ' <span class="tenant-wallet-currency">' + llEscape(WFT('wallet.sar_unit', 'ر.س')) + '</span>' +
          ' <span class="tenant-wallet-pts">(' + llEscape(llMoney(pts)) + ' ' + llEscape(WFT('wallet.points_unit', 'نقطة')) + ')</span>';
      }

      const pkgNameEl = document.getElementById('llWalletPackageName');
      if (pkgNameEl) {
        if (pointsObj && pointsObj.active_package) {
          pkgNameEl.textContent = pointsObj.active_package;
          pkgNameEl.style.display = '';
        } else if (typeof tenantUser !== 'undefined' && tenantUser && (tenantUser.company_name || tenantUser.company)) {
          pkgNameEl.textContent = tenantUser.company_name || tenantUser.company;
          pkgNameEl.style.display = '';
        } else {
          pkgNameEl.textContent = WFT('wallet.default_company_type', 'حساب منشأة معتمد');
          pkgNameEl.style.display = '';
        }
      }

      const metaEl = document.getElementById('llWalletMeta');
      if (metaEl) {
        const mult = ledgerData.multiplier ? ledgerData.multiplier + 'x' : '1.6x';
        const mode = ledgerData.enforced
          ? WFT('wallet.billing_enforced', 'نظام الفوترة مشغل')
          : WFT('wallet.billing_trial', 'فوترة تجريبية');
        metaEl.textContent = WFT('wallet.exchange_rate_info', 'سعر الصرف المعتمد: {mult} — {mode}', { mult: mult, mode: mode });
      }

      const reservedEl = document.getElementById('llWalletReserved');
      if (reservedEl) {
        const resSar = (pointsObj && pointsObj.reserved_sar) || 0;
        reservedEl.textContent = llMoney(resSar) + ' ' + WFT('wallet.sar_unit', 'ر.س');
      }

      const expiredEl = document.getElementById('llWalletExpired');
      if (expiredEl) {
        const expSar = (pointsObj && pointsObj.expired_sar) || 0;
        expiredEl.textContent = llMoney(expSar) + ' ' + WFT('wallet.sar_unit', 'ر.س');
      }

      const consumedEl = document.getElementById('llWalletConsumed');
      if (consumedEl) {
        const conSar = (pointsObj && pointsObj.consumed_sar) || 0;
        consumedEl.textContent = llMoney(conSar) + ' ' + WFT('wallet.sar_unit', 'ر.س');
      }

      const ledgerBody = document.getElementById('llLedgerBody');
      if (ledgerBody) {
        const entries = ledgerData.entries || [];
        if (!entries.length) {
          ledgerBody.innerHTML = '<tr class="tenant-wallet-ledger-empty"><td colspan="6" class="tenant-hint" style="text-align:center;padding:32px">' +
            llEscape(WFT('wallet.no_transactions', 'لا توجد معاملات مالية مسجلة بعد.')) + '</td></tr>';
        } else {
          ledgerBody.innerHTML = entries.map(function (entry) {
            const date = (entry.created_at || '').slice(0, 16).replace('T', ' ');
            const isCredit = entry.kind === 'credit';
            const typeLabel = isCredit
              ? WFT('wallet.type_credit', 'إيداع رصيد (شحن)')
              : (entry.kind === 'debit'
                  ? WFT('wallet.type_debit', 'تسوية استهلاك مشروع')
                  : (entry.kind === 'reversal' ? WFT('wallet.type_reversal', 'تسوية عكسية') : (entry.kind || WFT('wallet.transaction_fallback', 'معاملة'))));
            const typeBadge = '<span class="tenant-wallet-type-badge ' + (isCredit ? 'is-credit' : 'is-debit') + '">' +
              llEscape(typeLabel) + '</span>';
            const amountSar = Number(entry.amount_sar || 0);
            const sign = isCredit ? '+' : '-';
            const color = isCredit ? 'var(--teal, #0FA9C4)' : 'var(--navy, #07182C)';
            const amountHtml = '<strong style="color:' + color + ';font-size:13.5px">' + sign + ' ' +
              llEscape(llMoney(Math.abs(amountSar))) + ' <span style="font-size:11px;font-weight:600">' +
              llEscape(WFT('wallet.sar_unit', 'ر.س')) + '</span></strong>';
            const desc = entry.note || entry.package_name || (entry.draft_id ? WFT('wallet.project_prefix', 'مشروع #{id}', { id: entry.draft_id.slice(0, 8) }) : '—');
            const statusText = entry.status ? llStatus(entry.status) : (isCredit ? WFT('wallet.status_approved', 'معتمد') : WFT('wallet.status_completed', 'مكتمل'));
            const statusBadge = '<span class="tenant-badge" style="background:#dcfce7;color:#15803d;padding:3px 8px;border-radius:6px;font-size:11.5px;font-weight:700">' +
              llEscape(statusText) + '</span>';
            const invoiceHtml = entry.receipt_file_id
              ? '<a href="#" onclick="llOpenRechargeAttachment(\'' + entry.id + '\', \'receipt\');return false;">' + llEscape(WFT('wallet.receipt', 'إيصال')) + '</a>'
              : (entry.invoice_file_id
                  ? '<a href="#" onclick="llOpenRechargeAttachment(\'' + entry.id + '\', \'invoice\');return false;">' + llEscape(WFT('wallet.invoice', 'فاتورة')) + '</a>'
                  : '—');
            return '<tr>' +
              '<td>' + llEscape(date) + '</td>' +
              '<td>' + typeBadge + '</td>' +
              '<td>' + amountHtml + '</td>' +
              '<td style="font-weight:600">' + llEscape(desc) + '</td>' +
              '<td>' + statusBadge + '</td>' +
              '<td>' + invoiceHtml + '</td>' +
              '</tr>';
          }).join('');
        }
      }

      if (typeof llLoadRechargeRequests === 'function') {
        await llLoadRechargeRequests('llRechargeList');
      }

      if (typeof hydrateWorkspaceIcons === 'function') {
        hydrateWorkspaceIcons(document.getElementById('llTabPane_recharge'));
      }
    }
