from pathlib import Path


def test_successful_designer_edits_are_persisted_and_failures_are_visible():
    text = Path('index.html').read_text(encoding='utf-8')
    start = text.index('async function persistTenantDesignerWorkspace')
    end = text.index('async function renderPresentationFontStatus', start)
    section = text[start:end]
    assert "await api('PUT', '/api/presentations/' + tenantPresentationId" in section
    assert 'await saveProjectAsDraft(true);' in section
    assert 'const designerHadUnsavedChanges = tenantDraftDirty;' in section
    assert "action?.status === 'success'" in section
    assert 'await persistTenantDesignerWorkspace(designerHadUnsavedChanges)' in section
    assert 'لكن تعذر حفظه على الخادم' in section


if __name__ == '__main__':
    test_successful_designer_edits_are_persisted_and_failures_are_visible()
    print('designer chat persistence test passed')
