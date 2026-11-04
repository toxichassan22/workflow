"""Regression guards for platform button audits, loader traps, destructive actions, and approval gates."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ButtonAuditGuardsTests(unittest.TestCase):
    def read_file_text(self, rel_path: str) -> str:
        full_path = ROOT / rel_path
        self.assertTrue(full_path.exists(), f"File does not exist: {rel_path}")
        return full_path.read_text(encoding="utf-8")

    def test_loader_traps_enforce_finally_hide_loader(self):
        """All 7 critical loader spots must invoke hideLoader() in a finally block."""
        # 1. geocodeProjectAddress
        geo_src = self.read_file_text("assets/js/10-financial-report-timeline/02_timeline_sidebar.js")
        self.assertRegex(
            geo_src,
            r"async function geocodeProjectAddress[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{\s*hideLoader\(\);\s*\}",
            "geocodeProjectAddress must execute hideLoader() inside finally",
        )

        # 2. fetchNearbyLandmarks
        map_src = self.read_file_text("assets/js/11-land-croquis/02_map_edits.js")
        self.assertRegex(
            map_src,
            r"async function fetchNearbyLandmarks[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{\s*hideLoader\(\);\s*\}",
            "fetchNearbyLandmarks must execute hideLoader() inside finally",
        )

        # 3, 4, 5. aiAutoBuildFields, suggestAiFields, approveAllAiFields
        team_src = self.read_file_text("assets/js/06-team.js")
        self.assertRegex(
            team_src,
            r"async function aiAutoBuildFields[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{[\s\S]*?hideLoader\(\);",
            "aiAutoBuildFields must execute hideLoader() inside finally",
        )
        self.assertRegex(
            team_src,
            r"async function suggestAiFields[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{[\s\S]*?hideLoader\(\);",
            "suggestAiFields must execute hideLoader() inside finally",
        )
        self.assertRegex(
            team_src,
            r"async function approveAllAiFields[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{[\s\S]*?hideLoader\(\);",
            "approveAllAiFields must execute hideLoader() inside finally",
        )

        # 6. translateTenantPresentationToEnglish
        pres_src = self.read_file_text("assets/js/16-presentations-export/01_presentations.js")
        self.assertRegex(
            pres_src,
            r"async function translateTenantPresentationToEnglish[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{\s*hideLoader\(\);\s*\}",
            "translateTenantPresentationToEnglish must execute hideLoader() inside finally",
        )

        # 7. saveSagUserPermissions
        admin_src = self.read_file_text("assets/js/16-presentations-export/02_admin_dashboard.js")
        self.assertRegex(
            admin_src,
            r"async function saveSagUserPermissions[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{\s*hideLoader\(\);\s*\}",
            "saveSagUserPermissions must execute hideLoader() inside finally",
        )

    def test_start_tenant_project_guards_dirty_draft(self):
        """startTenantProject must confirm before clearing when tenantDraftDirty is true."""
        form_src = self.read_file_text("assets/js/07-project-form/01_form_sections.js")
        self.assertIn("tenantDraftDirty", form_src)
        self.assertRegex(
            form_src,
            r"async function startTenantProject\(\)\s*\{[\s\S]*?if\s*\([\s\S]*?tenantDraftDirty[\s\S]*?\)[\s\S]*?confirm\(",
            "startTenantProject must prompt confirm() if tenantDraftDirty is true",
        )

    def test_destructive_actions_require_confirmation(self):
        """Destructive deletes must ask user confirmation before proceeding."""
        # 1. deleteTenantWatermark
        auth_src = self.read_file_text("assets/js/02-settings-branding/02_auth_boot.js")
        self.assertRegex(
            auth_src,
            r"async function deleteTenantWatermark\(\)\s*\{[\s\S]*?if\s*\(!confirm\(",
            "deleteTenantWatermark must require confirm()",
        )

        # 2. clearAllChatSessions
        train_src = self.read_file_text("assets/js/17-admin-boot/03_training_chat_sessions.js")
        self.assertRegex(
            train_src,
            r"function clearAllChatSessions\(type\)\s*\{[\s\S]*?if\s*\(!confirm\(",
            "clearAllChatSessions must require confirm()",
        )

        # 3 & 4. deleteVisualConceptInteriorField & deleteVisualConceptSlotImage
        vc_src = self.read_file_text("assets/js/13-visual/01_visual_concept_page.js")
        self.assertRegex(
            vc_src,
            r"function deleteVisualConceptInteriorField\(slotId\)\s*\{[\s\S]*?if\s*\(!confirm\(",
            "deleteVisualConceptInteriorField must require confirm()",
        )
        self.assertRegex(
            vc_src,
            r"function deleteVisualConceptSlotImage\(slotId\)\s*\{[\s\S]*?if\s*\(!confirm\(",
            "deleteVisualConceptSlotImage must require confirm()",
        )

        # 5. removeLandPhoto & removeLandDocument
        files_src = self.read_file_text("assets/js/12-files-media/01_files_media.js")
        self.assertRegex(
            files_src,
            r"function removeLandPhoto\(fileId\)\s*\{[\s\S]*?if\s*\(!confirm\(",
            "removeLandPhoto must require confirm()",
        )
        self.assertRegex(
            files_src,
            r"function removeLandDocument\(fileId\)\s*\{[\s\S]*?if\s*\(!confirm\(",
            "removeLandDocument must require confirm()",
        )

    def test_concurrent_actions_disable_submit_buttons_with_finally(self):
        """Forms and operations buttons must be disabled during in-flight requests and restored in finally."""
        # Login and OTP in 01-nav-auth.js
        nav_src = self.read_file_text("assets/js/01-nav-auth.js")
        self.assertRegex(
            nav_src,
            r"async function handleLogin\(e\)\s*\{[\s\S]*?submitBtn\.disabled\s*=\s*true[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{[\s\S]*?submitBtn\.disabled\s*=\s*false",
            "handleLogin must disable submitBtn and restore it in finally",
        )
        self.assertRegex(
            nav_src,
            r"async function handleLoginOtpVerify\(e\)\s*\{[\s\S]*?submitBtn\.disabled\s*=\s*true[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{[\s\S]*?submitBtn\.disabled\s*=\s*false",
            "handleLoginOtpVerify must disable submitBtn and restore it in finally",
        )

        # Recharge requests and decisions in 18-landloom-ops.js
        ops_src = self.read_file_text("assets/js/18-landloom-ops.js")
        self.assertRegex(
            ops_src,
            r"async function llCreateRechargeRequest\(\)\s*\{[\s\S]*?submitBtn\.disabled\s*=\s*true[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{[\s\S]*?submitBtn\.disabled\s*=\s*false",
            "llCreateRechargeRequest must disable submitBtn and restore it in finally",
        )
        self.assertRegex(
            ops_src,
            r"async function llSubmitRechargeDecision\(\)\s*\{[\s\S]*?submitBtn\.disabled\s*=\s*true[\s\S]*?try\s*\{[\s\S]*?\}\s*finally\s*\{[\s\S]*?submitBtn\.disabled\s*=\s*false",
            "llSubmitRechargeDecision must disable submitBtn and restore it in finally",
        )

        # index.html must have the recharge button IDs
        index_src = self.read_file_text("index.html")
        self.assertIn('id="llRechargeSubmitBtn"', index_src)
        self.assertIn('id="llRechargeDecisionSubmitBtn"', index_src)

    def test_two_tier_approval_wording_guards(self):
        """Frontend files must never use 'بوابة الاعتماد الثانية' or 'بوابة الاعتماد الثالثة'."""
        files_src = self.read_file_text("assets/js/12-files-media/01_files_media.js")
        export_src = self.read_file_text("assets/js/16-presentations-export/03_export_delivery.js")

        self.assertNotIn("بوابة الاعتماد الثانية", files_src)
        self.assertNotIn("بوابة الاعتماد الثالثة", export_src)

        self.assertIn("تقدير التكلفة وحجز رصيد المحفظة لبدء التوليد", files_src)
        self.assertIn("قفل إصدار العرض وختم البصمة الرقمية للملف", export_src)

    def test_google_sheets_tracking_rule_recorded_in_agents_md(self):
        """AGENTS.md must document the Google Sheets task tracking rule and column structure."""
        agents_src = self.read_file_text("AGENTS.md")
        self.assertIn("Task tracking in Google Sheets (owner-managed workflow)", agents_src)
        self.assertIn("1xvCD6hoAjQBR38aBEA2jskI_UqbaHmGoYGiAAr25JM8", agents_src)
        self.assertIn("قيد العمل", agents_src)
        self.assertIn("قيد المراجعة", agents_src)
        self.assertIn("الملاحظات", agents_src)
        self.assertIn("مشكله سيستم", agents_src)
        self.assertIn("صفحه التصميم", agents_src)
        self.assertIn("DD/Mon/YYYY", agents_src)
        self.assertIn("strictly forbidden for ANY model or agent to write a completion date into column F", agents_src)
        self.assertIn("Auto-numbered by spreadsheet formula automatically", agents_src)


if __name__ == "__main__":
    unittest.main()
