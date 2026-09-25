/* 16-presentations-export/04_sag_company_create.js — super-admin "new company"
   modal: password tools, validation, create call and result rendering. */


    // SAG Super Admin
    let sagAllTenants = [];
    let sagLastOverview = null;
    let sagCurrentTenantId = null;
    let sagTenantActiveTab = 'company';
    let sagModalUsers = [];

    function openSagCompanyCreate() {
      const modal = document.getElementById('sagCompanyCreateModal');
      const form = document.getElementById('sagCompanyCreateForm');
      form.reset();
      document.getElementById('sagCreateStatus').value = 'active';
      document.getElementById('sagCreatePasswordMode').value = 'set_link';
      document.getElementById('sagCreatePassword').type = 'password';
      document.getElementById('sagCreateWelcomeEmail').checked = true;
      showSagCompanyCreateError('');
      document.getElementById('sagCompanyCreateResult').style.display = 'none';
      form.style.display = 'block';
      toggleSagCompanyPassword();
      modal.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(modal);
    }

    function closeSagCompanyCreate() {
      document.getElementById('sagCompanyCreateModal').style.display = 'none';
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
    }

    function toggleSagCompanyPassword() {
      const manual = document.getElementById('sagCreatePasswordMode').value === 'manual';
      const wrap = document.getElementById('sagCreatePasswordWrap');
      const input = document.getElementById('sagCreatePassword');
      wrap.style.display = manual ? 'block' : 'none';
      input.required = manual;
      if (!manual) {
        input.value = '';
        input.type = 'password';
        const toggle = input.parentElement ? input.parentElement.querySelector('button') : null;
        if (toggle) toggle.textContent = 'إظهار';
      }
    }

    function generateStrongPassword() {
      const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
      const bytes = new Uint8Array(16);
      let password = '';
      do {
        crypto.getRandomValues(bytes);
        password = Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
      } while (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password));
      return password;
    }

    function generateSagCompanyPassword() {
      const mode = document.getElementById('sagCreatePasswordMode');
      if (mode) mode.value = 'manual';
      toggleSagCompanyPassword();
      const input = document.getElementById('sagCreatePassword');
      input.value = generateStrongPassword();
      input.type = 'text';
      const toggle = input.parentElement ? input.parentElement.querySelector('button') : null;
      if (toggle) toggle.textContent = 'إخفاء';
    }

    async function copySagText(value) {
      try {
        await navigator.clipboard.writeText(value);
        toast('تم النسخ');
      } catch (error) {
        const input = document.createElement('textarea');
        input.value = value;
        document.body.appendChild(input);
        input.select();
        document.execCommand('copy');
        input.remove();
        toast('تم النسخ');
      }
    }

    function renderSagSetupResult(host, title, setupUrl, emailSent) {
      host.style.display = 'block';
      host.innerHTML =
        '<h3 style="margin:0 0 12px;color:var(--p)">' + escapeHtml(title) + '</h3>' +
        '<div class="tenant-grid full">' +
        '<div class="tenant-field"><label>رابط تعيين كلمة المرور</label>' +
        '<input type="text" value="' + escapeHtml(setupUrl || '') + '" readonly></div>' +
        '<div class="tenant-field"><label>حالة رسالة الترحيب</label><p style="margin:0">' +
        (emailSent ? 'تم الإرسال' : 'لم يتم الإرسال') + '</p></div></div>' +
        '<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:16px">' +
        '<button type="button" class="btn ghost" data-copy-setup-url>نسخ الرابط</button>' +
        '<button type="button" class="btn primary" onclick="closeSagCompanyCreate()">إغلاق</button></div>';
      host.querySelector('[data-copy-setup-url]').addEventListener('click', () => copySagText(setupUrl || ''));
    }

    function sagCompanyErrorArabic(raw) {
      const text = String(raw || '');
      const map = {
        'Email already registered': 'البريد الإلكتروني مسجل بالفعل لشركة أخرى',
        'Username already registered': 'اسم المستخدم مسجل بالفعل، اختر اسم مستخدم آخر',
        'Email or username already registered': 'البريد الإلكتروني أو اسم المستخدم مسجل بالفعل',
        'All company and account fields are required': 'جميع حقول الشركة والحساب مطلوبة',
        'Company or account manager name is too long': 'اسم الشركة أو اسم مدير الحساب طويل جدا',
        'Invalid email address': 'البريد الإلكتروني غير صالح',
        'Invalid username': 'اسم المستخدم غير صالح',
        'Invalid phone number': 'رقم الجوال غير صالح',
        'Invalid plan': 'الخطة غير صالحة',
        'Invalid password mode': 'طريقة إعداد كلمة المرور غير صالحة',
        'Credit balance must be a valid number': 'الرصيد الائتماني يجب أن يكون رقما صالحا',
        'Credit balance cannot be negative': 'الرصيد الائتماني لا يمكن أن يكون سالبا',
        'Password must be at least 10 characters': 'كلمة المرور يجب أن تكون 10 أحرف على الأقل',
        'Password must include letters and numbers': 'كلمة المرور يجب أن تحتوي على حروف وأرقام'
      };
      if (map[text]) return map[text];
      const lower = text.toLowerCase();
      if (lower.includes('email') && lower.includes('already')) return map['Email already registered'];
      if (lower.includes('username') && lower.includes('already')) return map['Username already registered'];
      return text || 'تعذر إنشاء حساب الشركة';
    }

    function showSagCompanyCreateError(msg) {
      const el = document.getElementById('sagCompanyCreateError');
      if (!el) return;
      if (typeof showTenantError === 'function') {
        showTenantError('sagCompanyCreateError', msg);
        return;
      }
      el.textContent = msg;
      el.style.display = msg ? 'block' : 'none';
    }

    async function createSagCompany(event) {
      event.preventDefault();
      const submit = document.getElementById('sagCreateCompanySubmit');
      const trialDaysEl = document.getElementById('sagCreateTrialDays');
      const payload = {
        companyName: document.getElementById('sagCreateCompanyName').value.trim(),
        accountManagerName: document.getElementById('sagCreateManagerName').value.trim(),
        email: document.getElementById('sagCreateEmail').value.trim().toLowerCase(),
        phone: document.getElementById('sagCreatePhone').value.trim(),
        username: document.getElementById('sagCreateUsername').value.trim().toLowerCase(),
        slug: (document.getElementById('sagCreateSlug') || {}).value || '',
        isActive: document.getElementById('sagCreateStatus').value === 'active',
        trialDays: trialDaysEl && trialDaysEl.value !== '' ? Number(trialDaysEl.value) : null,
        legalName: (document.getElementById('sagCreateLegalName') || {}).value || '',
        taxNumber: (document.getElementById('sagCreateTaxNumber') || {}).value || '',
        crNumber: (document.getElementById('sagCreateCrNumber') || {}).value || '',
        country: (document.getElementById('sagCreateCountry') || {}).value || '',
        passwordMode: document.getElementById('sagCreatePasswordMode').value,
        password: document.getElementById('sagCreatePassword').value,
        sendWelcomeEmail: document.getElementById('sagCreateWelcomeEmail').checked
      };
      showSagCompanyCreateError('');
      submit.disabled = true;
      showLoader('جاري إنشاء حساب الشركة', 'إنشاء الشركة والمستخدم الرئيسي', 12);
      try {
        const data = await api('POST', '/api/admin/tenants', payload);
        if (!data.success) {
          showSagCompanyCreateError(sagCompanyErrorArabic(data.error));
          return;
        }
        document.getElementById('sagCompanyCreateForm').style.display = 'none';
        renderSagSetupResult(
          document.getElementById('sagCompanyCreateResult'),
          'تم إنشاء حساب الشركة والمستخدم الرئيسي بنجاح',
          data.setupUrl,
          data.welcomeEmailSent
        );
        if (data.keyProvisioned === false) {
          toast(WFT('admin.key_provision_failed', 'أُنشئت الشركة لكن إصدار مفتاحها فشل — أصدره من قائمة الشركات'));
        }
        const tenantsData = await api('GET', '/api/admin/tenants');
        sagAllTenants = tenantsData.success ? tenantsData.tenants || [] : sagAllTenants;
        sagSyncPlanFilter();
        renderSagTenants(sagAllTenants);
      } finally {
        submit.disabled = false;
        hideLoader();
      }
    }
