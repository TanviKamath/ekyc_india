# Copyright (c) 2026, hello@frappe.io and contributors
# For license information, please see license.txt

"""Surepass, who resell the Indian credit bureaux behind one API.

Lives here rather than in lending because a bureau aggregator is an Indian arrangement and
lending is not an Indian app. Lending owns the idea of a credit bureau; this owns the one
vendor. Reached only through the lending_integration_adapters hook, so nothing here is
imported on a site without lending.

Adding the next bureau Surepass carries is a class:

    class SurepassCrifAdapter(SurepassBureauAdapter):
        key = "Surepass CRIF"
        bureau = "CRIF"
        endpoint = "/credit-report-crif/fetch-report-pdf"

and one line in hooks. Nothing else moves: not the report, not the log, not the rules.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint
from lending.loan_integrations.base import IntegrationError
from lending.loan_integrations.bureau import BureauAdapter

SETTINGS = "Surepass Settings"

# Surepass answers HTTP 200 and reports the real outcome in the body, so the status line
# alone never says whether a call worked.
SUCCESS_CODE = 200

# The signed link Surepass returns carries an AWS key and signature in its query string, and
# expires in ten minutes. We download the PDF during the call and drop the URL, rather than
# writing somebody else's credentials into our own logs.
DROPPED_FROM_PAYLOAD = ("credit_report_link", "credit_report_base64")

# CIBIL answers below the scoring floor to say why it could not score, rather than to score
# badly: -1 is no history at all, 1 to 5 too little of it. Treating those as a score would
# read "no credit history" as "the worst possible borrower".
LOWEST_REAL_SCORE = 300


class SurepassBureauAdapter(BureauAdapter):
	"""What every bureau Surepass carries has in common.

	They share this envelope, this authentication and this request body, so a new one is the
	endpoint and the bureau name and nothing else.
	"""

	settings_doctype = SETTINGS

	# The path under the base URL, and the Credit Bureau Report option this fills in.
	endpoint: str = ""

	def auth_headers(self) -> dict:
		# Not the Basic auth the base class assumes: Surepass issues one bearer token and no
		# client id, so the pair of credential fields carries the token in its second half.
		_, token = self.creds()

		if not token:
			frappe.throw(
				_("Set the {0} API Secret in {1} to the token from the Surepass console.").format(
					self.environment().title(), SETTINGS
				)
			)

		return {
			"Content-Type": "application/json",
			"Accept": "application/json",
			"Authorization": f"Bearer {token}",
		}

	def pull(self, context: dict) -> dict:
		return self.request("POST", self.endpoint, json=self.request_body(context))

	def request_body(self, context: dict) -> dict:
		# "Y" is an assertion that the applicant agreed, so it is only ever sent because the
		# caller already checked that they did. Hardcoding it would make us claim a consent
		# nobody gave. See lending's validate_bureau_consent.
		return {
			"name": context.get("name"),
			"pan": context.get("pan"),
			"mobile": indian_mobile(context.get("mobile")),
			"gender": (context.get("gender") or "").lower(),
			"consent": "Y",
		}

	def parse(self, response: dict) -> dict:
		if not response.get("success") or cint(response.get("status_code")) != SUCCESS_CODE:
			raise IntegrationError(
				_("{0} refused the request: {1}").format(
					self.provider.name, response.get("message") or _("no reason given")
				)
			)

		data = response.get("data") or {}
		score = cint(data.get("credit_score"))

		return {
			"external_id": data.get("client_id"),
			"score": score if score >= LOWEST_REAL_SCORE else 0,
			# Surepass's report endpoints answer with a score and a document. Neither carries
			# the applicant's existing obligations, so we say we do not know them rather than
			# let an unfilled field be read as an applicant who owes nothing.
			"obligations_known": False,
			"total_emi": 0,
			"report_url": data.get("credit_report_link"),
			"payload": {k: v for k, v in data.items() if k not in DROPPED_FROM_PAYLOAD},
		}


class SurepassCibilAdapter(SurepassBureauAdapter):
	key = "Surepass CIBIL"
	bureau = "CIBIL"
	endpoint = "/credit-report-cibil/fetch-report-pdf"


def indian_mobile(value: str | None) -> str:
	"""Ten bare digits, which is what Surepass ask for.

	A lead's number is a Phone field, so it arrives carrying the country code and whatever
	punctuation somebody typed: "+91-9988776655". Surepass's own examples are ten digits, and
	a number they cannot match is a refusal we are billed for.
	"""
	digits = re.sub(r"\D", "", value or "")

	if len(digits) == 12 and digits.startswith("91"):
		return digits[2:]

	if len(digits) == 11 and digits.startswith("0"):
		return digits[1:]

	return digits
