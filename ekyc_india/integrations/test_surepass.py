# Copyright (c) 2026, hello@frappe.io and contributors
# See license.txt

import unittest

import frappe
from frappe.tests import IntegrationTestCase

# The adapters sit on lending's BureauAdapter, so they only exist where lending does. eKYC
# India is installable on its own, and its test run has to survive that.
HAS_LENDING = "lending" in frappe.get_installed_apps()

if HAS_LENDING:
	from lending.loan_integrations.base import IntegrationError

	from ekyc_india.integrations.surepass import SurepassBureauAdapter, SurepassCibilAdapter

TEST_PAN = "EKRPR1234F"
TOKEN = "a-test-token"
SANDBOX_URL = "https://sandboxapp.surepass.app/sandbox/api/v1"

# The response Surepass's sandbox actually returns, kept whole so a change in their envelope
# fails here rather than in production.
SANDBOX_RESPONSE = {
	"data": {
		"client_id": "credit_report_cibil_pdf_xfOSfdDRgierjgNdZelb",
		"name": "VISHAL RATHORE",
		"mobile": "9988776655",
		"pan": TEST_PAN,
		"gender": "male",
		"user_email": None,
		"credit_score": "750",
		"credit_report": None,
		"credit_report_link": (
			"https://aadhaar-kyc-docs.s3.amazonaws.com/user123/credit_report_cibil/report.pdf"
			"?X-Amz-Credential=AKIAY5K3QRM5KVPBYKKE%2F20260806%2Fap-south-1%2Fs3%2Faws4_request"
			"&X-Amz-Expires=600&X-Amz-Signature=c5168167bdab60bf30e2b27ac148585a4b474633"
		),
		"credit_report_base64": None,
	},
	"status_code": 200,
	"success": True,
	"message": "Success",
	"message_code": "success",
}


@unittest.skipUnless(HAS_LENDING, "the Surepass bureau adapters need the lending app")
class TestSurepassBureau(IntegrationTestCase):
	def setUp(self):
		settings = frappe.get_single("Surepass Settings")
		settings.update(
			{
				"enable_production": 0,
				"enable_sandbox": 1,
				"sandbox_url": SANDBOX_URL,
				"sandbox_api_secret": TOKEN,
			}
		)
		settings.save(ignore_permissions=True)

		# Lending hands the adapter the routing row. Only its name is read, for messages.
		self.adapter = SurepassCibilAdapter(frappe._dict(name="Surepass CIBIL"))

	def test_it_reads_the_score_out_of_the_envelope(self):
		parsed = self.adapter.parse(SANDBOX_RESPONSE)

		self.assertEqual(parsed["score"], 750)
		self.assertEqual(parsed["external_id"], "credit_report_cibil_pdf_xfOSfdDRgierjgNdZelb")

	def test_it_does_not_claim_to_know_the_obligations(self):
		# The endpoint returns no obligations, and saying so is what keeps the affordability
		# rules from reading an unfilled field as an applicant who owes nothing.
		self.assertFalse(self.adapter.parse(SANDBOX_RESPONSE)["obligations_known"])

	def test_it_keeps_the_signed_link_out_of_the_stored_payload(self):
		parsed = self.adapter.parse(SANDBOX_RESPONSE)

		self.assertNotIn("credit_report_link", parsed["payload"])
		self.assertNotIn("AKIAY5K3QRM5KVPBYKKE", frappe.as_json(parsed["payload"]))
		# Dropped from what we store, but still used to fetch the document during the call.
		self.assertIn("X-Amz-Signature", parsed["report_url"])

	def test_a_score_below_the_floor_is_not_a_score(self):
		response = {**SANDBOX_RESPONSE, "data": {**SANDBOX_RESPONSE["data"], "credit_score": "-1"}}

		self.assertEqual(self.adapter.parse(response)["score"], 0)

	def test_a_failure_reported_in_the_body_is_a_failure(self):
		# Surepass answers HTTP 200 and says so in the body, so raise_for_status sees nothing.
		response = {**SANDBOX_RESPONSE, "success": False, "message": "PAN not found"}

		with self.assertRaises(IntegrationError):
			self.adapter.parse(response)

	def test_the_request_body_carries_what_the_bureau_asks_for(self):
		body = self.adapter.request_body(
			{"name": "Vishal Rathore", "pan": TEST_PAN, "mobile": "9988776655", "gender": "Male"}
		)

		self.assertEqual(body["gender"], "male")
		self.assertEqual(body["pan"], TEST_PAN)

	def test_it_authenticates_with_a_bearer_token(self):
		# Surepass issues one token and no client id, so this is not the base class's Basic auth.
		self.assertEqual(self.adapter.auth_headers()["Authorization"], f"Bearer {TOKEN}")

	def test_it_reads_its_own_settings_rather_than_the_provider_row(self):
		self.assertEqual(self.adapter.settings.doctype, "Surepass Settings")
		self.assertEqual(self.adapter.get_base_url(), SANDBOX_URL)

	def test_another_surepass_bureau_is_an_endpoint_and_a_name(self):
		class SurepassCrifAdapter(SurepassBureauAdapter):
			key = "Surepass CRIF"
			bureau = "CRIF"
			endpoint = "/credit-report-crif/fetch-report-pdf"

		crif = SurepassCrifAdapter(frappe._dict(name="Surepass CRIF"))

		# Same envelope, same token, same parsing — only the endpoint and the name changed.
		self.assertEqual(crif.parse(SANDBOX_RESPONSE)["score"], 750)
		self.assertEqual(crif.auth_headers(), self.adapter.auth_headers())
		self.assertEqual(crif.bureau, "CRIF")
