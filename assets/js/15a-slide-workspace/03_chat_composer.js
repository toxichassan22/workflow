/* Chat composer: attachments as small previews inside the entry box, the
   send/stop toggle and the full-size preview overlay. */

    let tenantChatAttachedImage = null;
    let tenantChatAttachedImages = [];
    let tenantChatAttachedDocs = [];
    const TENANT_CHAT_IMAGE_LIMIT = 4 * 1024 * 1024;
    const TENANT_CHAT_MAX_IMAGES = 3;
    const TENANT_CHAT_MAX_DOCS = 2;

    function composerText(key, fallback, params) {
      return (typeof WFT === 'function') ? WFT(key, fallback, params) : fallback;
    }

    function renderTenantChatAttachment() {
      const box = document.getElementById('tenantChatAttachment');
      if (!box) return;
      const images = tenantChatAttachedImages.length
        ? tenantChatAttachedImages
        : (tenantChatAttachedImage ? [tenantChatAttachedImage] : []);
      box.innerHTML = '';
      if (!images.length && !tenantChatAttachedDocs.length) {
        box.hidden = true;
        return;
      }
      const removeLabel = escapeHtml(composerText('ws.delete', 'حذف'));
      images.forEach((item, index) => {
        const node = document.createElement('div');
        node.className = 'tenant-chat-attachment-item';
        node.innerHTML = '<img src="' + escapeHtml(item.dataUri || '') + '" alt="">'
          + '<button type="button" class="tenant-chat-attachment-remove"'
          + ' onclick="removeTenantChatAttachment(\'image\', ' + index + ')">' + removeLabel + '</button>';
        box.appendChild(node);
      });
      tenantChatAttachedDocs.forEach((item, index) => {
        const node = document.createElement('div');
        node.className = 'tenant-chat-attachment-item is-doc';
        node.textContent = item.name || composerText('ws.attachment_document', 'ملف PDF');
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'tenant-chat-attachment-remove';
        remove.textContent = composerText('ws.delete', 'حذف');
        remove.onclick = () => removeTenantChatAttachment('doc', index);
        node.appendChild(remove);
        box.appendChild(node);
      });
      box.hidden = false;
    }

    function removeTenantChatAttachment(kind, index) {
      if (kind === 'doc') {
        tenantChatAttachedDocs.splice(Number(index) || 0, 1);
      } else {
        const list = tenantChatAttachedImages.length
          ? tenantChatAttachedImages.slice()
          : (tenantChatAttachedImage ? [tenantChatAttachedImage] : []);
        list.splice(Number(index) || 0, 1);
        tenantChatAttachedImages = list;
        tenantChatAttachedImage = list[0] || null;
      }
      renderTenantChatAttachment();
    }

    function openTenantChatImagePreview(src) {
      if (!src) return;
      const previous = document.getElementById('tenantChatLightbox');
      if (previous) previous.remove();
      const modal = document.createElement('div');
      modal.id = 'tenantChatLightbox';
      modal.className = 'tenant-chat-lightbox';
      modal.innerHTML = '<div class="tenant-chat-lightbox-card">'
        + '<button type="button" class="tenant-chat-lightbox-close" aria-label="'
        + escapeHtml(composerText('ws.close_preview', 'إغلاق الصورة')) + '">'
        + escapeHtml(composerText('ws.close_preview', 'إغلاق الصورة')) + '</button>'
        + '<img src="' + escapeHtml(src) + '" alt="">'
        + '</div>';
      modal.addEventListener('click', event => {
        if (event.target === modal || event.target.closest('.tenant-chat-lightbox-close')) modal.remove();
      });
      document.body.appendChild(modal);
    }

    function clearTenantChatAttachment() {
      tenantChatAttachedImage = null;
      tenantChatAttachedImages = [];
      tenantChatAttachedDocs = [];
      const input = document.getElementById('tenantChatImageFile');
      if (input) input.value = '';
      renderTenantChatAttachment();
    }

    // The attach button used to open the training page's file input, and the designer never
    // received the image: the picked file was only ever read by the training chat.
    function attachTenantChatImage(input) {
      const picked = input && input.files ? Array.from(input.files).slice(0, TENANT_CHAT_MAX_IMAGES) : [];
      if (!picked.length) return;
      const images = [];
      const docs = [];
      for (const file of picked) {
        if (String(file.type || '') === 'application/pdf') {
          if (file.size > TENANT_CHAT_IMAGE_LIMIT) {
            toast(composerText('ws.file_too_large', 'حجم الملف أكبر من 4 م.ب'));
            clearTenantChatAttachment();
            return;
          }
          docs.push(file);
          continue;
        }
        if (!String(file.type || '').startsWith('image/')) {
          toast(WFT('chat.attachment_unsupported_type', 'نوع الملف غير مدعوم — أرفق صورة أو PDF'));
          clearTenantChatAttachment();
          return;
        }
        if (file.size > TENANT_CHAT_IMAGE_LIMIT) {
          toast(composerText('ws.file_too_large', 'حجم الملف أكبر من 4 م.ب'));
          clearTenantChatAttachment();
          return;
        }
        images.push(file);
      }
      const readFile = file => new Promise(resolve => {
        const reader = new FileReader();
        reader.onload = () => resolve({ name: file.name, dataUri: String(reader.result || '') });
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(file);
      });
      Promise.all(images.concat(docs).map(readFile)).then(results => {
        const imageItems = results.slice(0, images.length)
          .filter(item => item && String(item.dataUri || '').startsWith('data:image/'));
        const docItems = results.slice(images.length)
          .filter(item => item && String(item.dataUri || '').startsWith('data:application/pdf'))
          .slice(0, TENANT_CHAT_MAX_DOCS);
        if (!imageItems.length && !docItems.length) {
          toast(WFT('chat.attachment_read_failed', 'تعذر قراءة الملف المرفق'));
          clearTenantChatAttachment();
          return;
        }
        tenantChatAttachedImages = imageItems.slice(0, TENANT_CHAT_MAX_IMAGES);
        tenantChatAttachedImage = tenantChatAttachedImages[0] || null;
        tenantChatAttachedDocs = docItems;
        renderTenantChatAttachment();
      });
    }
