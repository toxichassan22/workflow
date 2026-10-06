/* 18-landloom-ops/02_join_requests.js — super-admin desk for the public
   «اطلب حسابًا» leads. Rows arrive from GET /api/admin/join-requests; triage
   moves a lead new -> contacted -> closed through the status endpoint.
   Shared global scope, classic scripts in order. */

    const ADMIN_JOIN_STATUSES = {
      new: ['admin.join_status_new', 'جديد'],
      contacted: ['admin.join_status_contacted', 'تم التواصل'],
      closed: ['admin.join_status_closed', 'مغلقة']
    };

    async function openAdminJoinPage() {
      showTenantPage('tenantAdminJoinPage');
      await adminLoadJoinRequests();
    }

    function adminJoinStatusLabel(status) {
      const entry = ADMIN_JOIN_STATUSES[status];
      return entry ? WFT(entry[0], entry[1]) : String(status || '');
    }

    async function adminLoadJoinRequests() {
      const box = document.getElementById('adminJoinRequestsList');
      if (!box) return;
      box.innerHTML = '<p class="tenant-hint">' + WFT('common.loading', 'جاري التحميل...') + '</p>';
      const status = (document.getElementById('adminJoinStatusFilter') || {}).value || '';
      const url = '/api/admin/join-requests' + (status ? '?status=' + encodeURIComponent(status) : '');
      const data = await api('GET', url).catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">' + WFT('admin.join_load_failed', 'تعذر تحميل طلبات الانضمام.') + '</p>';
        return;
      }
      const requests = data.requests || [];
      const newEl = document.getElementById('adminStatJoinNew');
      if (newEl) newEl.textContent = requests.filter(r => r.status === 'new').length;
      if (!requests.length) {
        box.innerHTML = '<p class="tenant-hint">' + WFT('admin.join_empty', 'لا توجد طلبات انضمام.') + '</p>';
        return;
      }
      box.innerHTML =
        '<div class="table-wrap"><table><thead><tr>' +
        '<th>' + WFT('admin.join_col_name', 'الاسم') + '</th>' +
        '<th>' + WFT('admin.join_col_company', 'الشركة') + '</th>' +
        '<th>' + WFT('admin.join_col_contact', 'التواصل') + '</th>' +
        '<th>' + WFT('admin.join_col_status', 'الحالة') + '</th>' +
        '<th>' + WFT('admin.join_col_date', 'التاريخ') + '</th>' +
        '<th></th>' +
        '</tr></thead><tbody>' +
        requests.map(r => {
          const date = (r.created_at || '').slice(0, 16).replace('T', ' ');
          // Each row only offers the statuses it can still move to.
          const moves = { new: ['contacted', 'closed'], contacted: ['closed'], closed: [] }[r.status] || [];
          const actions = moves.map(s =>
            '<button type="button" class="btn small ghost" onclick="adminSetJoinStatus(\'' + r.id + '\',\'' + s + '\')">' +
            adminJoinStatusLabel(s) + '</button>').join(' ');
          return '<tr>' +
            '<td style="font-weight:700">' + llEscape(r.name) +
              (r.message ? '<div style="font-weight:400;font-size:11.5px;color:var(--muted)">' + llEscape(r.message) + '</div>' : '') +
            '</td>' +
            '<td>' + llEscape(r.company) + '</td>' +
            '<td dir="ltr" style="text-align:start">' + llEscape(r.email) +
              (r.phone ? '<br>' + llEscape(r.phone) : '') + '</td>' +
            '<td>' + adminJoinStatusLabel(r.status) + '</td>' +
            '<td>' + llEscape(date) + '</td>' +
            '<td style="white-space:nowrap">' + actions + '</td>' +
            '</tr>';
        }).join('') +
        '</tbody></table></div>';
    }

    async function adminSetJoinStatus(id, status) {
      const res = await api('POST', '/api/admin/join-requests/' + id + '/status', { status: status }).catch(e => e);
      if (!res || !res.success) {
        toast((res && res.error) || WFT('admin.join_update_failed', 'تعذر تحديث الحالة'));
        return;
      }
      toast(WFT('admin.join_updated', 'تم تحديث الطلب'));
      await adminLoadJoinRequests();
    }
