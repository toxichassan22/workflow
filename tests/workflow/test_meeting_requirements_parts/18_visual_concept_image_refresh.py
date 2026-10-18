class MeetingRequirementsTestsPart18(MeetingRequirementsTests):

    def test_visual_concept_retries_failed_image_load_without_reopening_view(self):
        source = read_frontend_text()
        self.assertIn('function retryVisualConceptImageLoad(image)', source)
        self.assertIn("image.closest('.visual-concept-card[data-visual-slot], [data-sketch-card]')", source)
        self.assertIn("retryUrl.searchParams.set('t', Date.now() + '-' + nextAttempt)", source)
        self.assertIn('if (sketch.imageUrl === currentUrl) sketch.imageUrl = refreshedUrl;', source)
        self.assertIn('if (slot.imageUrl === currentUrl) slot.imageUrl = refreshedUrl;', source)
        self.assertIn('markVisualConceptDirty();', source)
        self.assertIn("document.addEventListener('error', event => {", source)
        self.assertIn('retryVisualConceptImageLoad(image);', source)
        self.assertIn('if (currentAttempt >= 2) return;', source)
