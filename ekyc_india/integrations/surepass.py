# Copyright (c) 2026, hello@frappe.io and contributors
# For license information, please see license.txt

"""Surepass, who resell the Indian credit bureaux behind one API.

Lives here rather than in lending because a bureau aggregator is an Indian arrangement and
lending is not an Indian app. Lending owns the idea of a credit bureau; this owns the one
vendor. Reached only through the lending_integration_adapters hook, so nothing here is
imported on a site without lending.

Four bureaux are wired. They share this token, this envelope and this parsing, and differ
only in what they want asked:

    CIBIL     a name and a gender, against a pan
    Experian  a name, no gender, against a pan
    CRIF      a first and last name, no gender, against a pan
    Equifax   a name and a gender, against a typed id rather than a pan

So a new one is its endpoint, its bureau name, and its request body — and nothing underneath.
All four are asked for consent and a mobile number, which is the whole of what they share.
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

# Never kept in the stored report. The signed link carries an AWS key and signature in its
# query string and expires in ten minutes, so we download the PDF during the call and drop
# the URL rather than writing somebody else's credentials into our own records. CRIF answers
# with an aadhaar_number field, which is the last thing a credit file needs to be carrying
# around: the score is what the rules read, and the number is not ours to keep.
DROPPED_FROM_PAYLOAD = ("credit_report_link", "credit_report_base64", "aadhaar_number")

# CIBIL answers below the scoring floor to say why it could not score, rather than to score
# badly: -1 is no history at all, 1 to 5 too little of it. Treating those as a score would
# read "no credit history" as "the worst possible borrower".
LOWEST_REAL_SCORE = 300


class SurepassBureauAdapter(BureauAdapter):
	"""What every bureau Surepass carries has in common.

	They share this envelope, this authentication and this parsing. What they do not share is
	the request body: CIBIL asks for one name and a gender, CRIF for a first and last name and
	neither. So a new bureau is its endpoint, its name, and the shape of its request — and
	nothing below that line.
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
			"mobile": indian_mobile(context.get("mobile")),
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

	def request_body(self, context: dict) -> dict:
		return {
			**super().request_body(context),
			"pan": context.get("pan"),
			"name": context.get("name"),
			"gender": (context.get("gender") or "").lower(),
		}


class SurepassExperianAdapter(SurepassBureauAdapter):
	key = "Surepass Experian"
	bureau = "Experian"
	endpoint = "/credit-report-experian/fetch-report-pdf"

	def request_body(self, context: dict) -> dict:
		# CIBIL's body without the gender, which Experian do not ask for.
		return {**super().request_body(context), "pan": context.get("pan"), "name": context.get("name")}


class SurepassCrifAdapter(SurepassBureauAdapter):
	key = "Surepass CRIF"
	bureau = "CRIF"
	endpoint = "/credit-report-crif/fetch-report-pdf"

	# Their flag for how much of the report to send back. False is what their examples use,
	# and it answers with an empty credit_report. Whether true fills that in — and with it the
	# applicant's existing obligations, which is the one number we still have to do without —
	# is untested, so this stays where their documentation puts it.
	raw_report = False

	def request_body(self, context: dict) -> dict:
		first_name, last_name = split_name(context.get("name"))

		return {
			**super().request_body(context),
			"pan": context.get("pan"),
			"first_name": first_name,
			"last_name": last_name,
			"raw": self.raw_report,
		}


class SurepassEquifaxAdapter(SurepassBureauAdapter):
	"""Surepass's credit-report-v2 endpoint, which they tell us answers from Equifax.

	Every other bureau here is named by the path it was fetched from. This one is not: the
	path says only "v2" and the response never names a bureau either, so the name below is
	recorded on Surepass's word. If that word turns out to be wrong, this line is the only
	thing that has to move — but every report already filed under it will be wrong, which is
	why it is worth having in writing from them.
	"""

	key = "Surepass Equifax"
	bureau = "Equifax"

	# Their verb order is reversed here — fetch-pdf-report, not fetch-report-pdf.
	endpoint = "/credit-report-v2/fetch-pdf-report"

	def request_body(self, context: dict) -> dict:
		return {
			**super().request_body(context),
			"name": context.get("name"),
			"gender": (context.get("gender") or "").lower(),
			# v2 identifies people by a typed id rather than by a PAN field of its own. A lead
			# only ever carries a PAN, so the type is not a choice we have to make.
			"id_number": context.get("pan"),
			"id_type": "pan",
		}


def split_name(full_name: str | None) -> tuple[str, str]:
	"""A full name in the two halves CRIF ask for.

	We hold one name, because that is what a lead is captured with. Everything after the first
	word becomes the surname, which is the best a single field can do — and a mononym leaves
	the surname empty rather than guessing at one.
	"""
	parts = (full_name or "").split()

	if not parts:
		return "", ""

	return parts[0], " ".join(parts[1:])


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
