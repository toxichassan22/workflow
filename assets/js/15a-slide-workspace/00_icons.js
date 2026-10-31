/* Deck workspace icons. The owner authorized icons on the presentation page
   (2026-10-31) after the page shipped text-only: send, attach, stop, collapse,
   and the compact slide actions. This is the only icon sprite in the client;
   it stays a local stroke set, never a library, font, emoji or glyph label. */

    const WS_ICON_PATHS = {
      send: '<path d="M21 3 3 10.6l7.2 2.8 2.7 7.6L21 3Z"/><path d="M10.2 13.4 21 3"/>',
      stop: '<rect x="7" y="7" width="10" height="10" rx="2.2" fill="currentColor" stroke="none"/>',
      attach: '<path d="M20 11.6l-8.2 8.2a5 5 0 0 1-7.1-7.1l8.2-8.2a3.3 3.3 0 0 1 4.7 4.7l-8.1 8.1a1.7 1.7 0 0 1-2.4-2.4l7.3-7.3"/>',
      'arrow-up': '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',
      'arrow-down': '<path d="M12 5v14"/><path d="m6 13 6 6 6-6"/>',
      more: '<circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none"/>',
      notes: '<path d="M7 3.8h7l4 4V20H7z"/><path d="M14 3.8V8h4"/><path d="M10 12h5"/><path d="M10 15.5h5"/>',
      group: '<rect x="3.8" y="3.8" width="9" height="9" rx="1.6"/><rect x="11.2" y="11.2" width="9" height="9" rx="1.6"/>',
      trash: '<path d="M5 7h14"/><path d="M9.5 7V4.5h5V7"/><path d="M7 7l1 13h8l1-13"/><path d="M10.5 11v5.5"/><path d="M13.5 11v5.5"/>',
      rename: '<path d="M4 20h4L20 8l-4-4L4 16v4Z"/><path d="m14 6 4 4"/>',
      duplicate: '<rect x="9" y="9" width="11" height="11" rx="1.8"/><path d="M5 15V5h10"/>',
      refresh: '<path d="M20 11a8 8 0 1 0-2.3 6"/><path d="M20 4.5V11h-6.5"/>',
      eye: '<path d="M12 6c5 0 9 2.9 9 6s-4 6-9 6-9-2.9-9-6 4-6 9-6Z"/><circle cx="12" cy="12" r="2.6"/>',
      'eye-off': '<path d="M4 4l16 16"/><path d="M9.9 9.9A2.6 2.6 0 0 0 12 14.6c.7 0 1.3-.3 1.8-.7"/><path d="M6.4 6.9C4.3 8.3 3 10.1 3 12c0 3.1 4 6 9 6 1.5 0 2.9-.3 4.1-.9"/><path d="M17.9 16.2C19.2 15 20 13.6 20 12c0-3.1-4-6-9-6-.6 0-1.2.1-1.8.2"/>',
      chevron: '<path d="m14.5 5.5-6.5 6.5 6.5 6.5"/>',
      close: '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
      plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
    };

    function wsIcon(name) {
      const glyph = WS_ICON_PATHS[name] || WS_ICON_PATHS.more;
      return '<svg class="ws-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"'
        + ' fill="none" stroke="currentColor" stroke-width="1.8"'
        + ' stroke-linecap="round" stroke-linejoin="round">' + glyph + '</svg>';
    }

    // Static shell buttons declare data-ws-icon; this fills them once at boot.
    function hydrateWorkspaceIcons(root) {
      const scope = root || document;
      scope.querySelectorAll('[data-ws-icon]').forEach(node => {
        const name = node.getAttribute('data-ws-icon');
        if (!name || node.dataset.wsIconReady === '1') return;
        node.insertAdjacentHTML('afterbegin', wsIcon(name));
        node.dataset.wsIconReady = '1';
      });
    }
