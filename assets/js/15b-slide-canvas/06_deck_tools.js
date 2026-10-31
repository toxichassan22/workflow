/* Deck-wide corrections: find and replace across every slide. Hidden slides
   stay in the file (and in the export) but the present mode skips them. */

    // A deck-wide replacement re-renders the cards; blurring a focused editor
    // during that rebuild would write its pre-replace text over the result.
    let slideDeckReplaceBusy = false;

    function deckToolText(key, fallback, params) {
      return (typeof WFT === 'function') ? WFT(key, fallback, params) : fallback;
    }

    function deckFindResultElement() {
      return document.getElementById('deckFindResult');
    }

    function setDeckFindResult(message, isError) {
      const box = deckFindResultElement();
      if (!box) return;
      box.textContent = String(message || '');
      box.hidden = !message;
      box.classList.toggle('is-error', !!isError);
    }

    function runDeckFindReplace() {
      if (!hasPermission('create_presentation')) return;
      const findInput = document.getElementById('deckFindInput');
      const replaceInput = document.getElementById('deckReplaceInput');
      const find = findInput ? String(findInput.value || '') : '';
      const replace = replaceInput ? String(replaceInput.value || '') : '';
      if (!find) {
        setDeckFindResult(deckToolText('deck.find_required', 'اكتب النص المطلوب البحث عنه'), true);
        return;
      }
      // A live text edit commits on blur. Clicking the menu blurs the editor,
      // and that commit must land before the slides are read — otherwise it
      // writes the pre-replace text back over the replacement.
      const active = document.activeElement;
      if (active && active.blur && active.closest && active.closest('.tenant-slide-stage')) {
        active.blur();
      }
      let total = 0;
      let touched = 0;
      slideDeckReplaceBusy = true;
      try {
        beginPresentationUndoChange();
        tenantSlidesData.forEach(slide => {
          if (!slide) return;
          let changed = false;
          if (slide.html) {
            const result = deckReplaceInSlideHtml(slide.html, find, replace);
            if (result.count > 0) {
              slide.html = result.html;
              total += result.count;
              changed = true;
            }
          }
          if (slide.title && String(slide.title).indexOf(find) !== -1) {
            const occurrences = String(slide.title).split(find).length - 1;
            slide.title = String(slide.title).split(find).join(replace);
            total += occurrences;
            changed = true;
          }
          if (changed) {
            touched += 1;
            slide.is_custom = true;
            slide._designer_keep_html = true;
          }
        });
        if (!total) {
          setDeckFindResult(deckToolText('deck.find_none', 'لا توجد نتائج مطابقة'), true);
          return;
        }
        renumberTenantSlides();
        renderTenantSlides();
        markSlidesDeckChanged();
        if (typeof checkpointPresentationUndo === 'function') checkpointPresentationUndo();
        const message = deckToolText('deck.find_result', 'تم استبدال {n} مرة في {slides} شريحة',
          { n: total, slides: touched });
        setDeckFindResult(message, false);
        toast(message);
      } finally {
        setTimeout(() => { slideDeckReplaceBusy = false; }, 0);
      }
    }
