# Copyright (c) 2026, hello@frappe.io and contributors
# See license.txt

import unittest

import frappe
from frappe.tests import IntegrationTestCase

from ekyc_india.ekyc_india.install import (
	after_app_install,
	after_migrate,
	create_integration_providers,
)

SUREPASS_PROVIDERS = ["Surepass CIBIL", "Surepass CRIF", "Surepass Equifax", "Surepass Experian"]


@unittest.skipUnless(
	frappe.db.exists("DocType", "Loan Integration Provider"), "needs lending's Loan Integration Provider"
)
class TestCreateIntegrationProviders(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Loan Integration Provider", {"name": ("in", SUREPASS_PROVIDERS)})

	def test_creates_one_inactive_provider_per_adapter(self):
		create_integration_providers()

		providers = frappe.get_all(
			"Loan Integration Provider",
			filters={"name": ("in", SUREPASS_PROVIDERS)},
			fields=["name", "adapter", "provider_type", "is_active", "settings_doctype"],
			order_by="name",
		)

		self.assertEqual([p.name for p in providers], SUREPASS_PROVIDERS)

		for provider in providers:
			self.assertEqual(provider.adapter, provider.name)
			self.assertEqual(provider.provider_type, "Credit Bureau")
			self.assertEqual(provider.is_active, 0)
			self.assertEqual(provider.settings_doctype, "Surepass Settings")

	def test_leaves_an_existing_provider_alone(self):
		create_integration_providers()
		frappe.db.set_value("Loan Integration Provider", "Surepass CIBIL", "is_active", 1)

		create_integration_providers()

		self.assertEqual(frappe.db.get_value("Loan Integration Provider", "Surepass CIBIL", "is_active"), 1)

	def test_creates_providers_when_lending_is_installed_later(self):
		after_app_install("some_other_app")
		self.assertEqual(self.surepass_provider_count(), 0)

		after_app_install("lending")
		self.assertEqual(self.surepass_provider_count(), len(SUREPASS_PROVIDERS))

	def test_creates_providers_on_migrate(self):
		after_migrate()

		self.assertEqual(self.surepass_provider_count(), len(SUREPASS_PROVIDERS))

	def surepass_provider_count(self):
		return frappe.db.count("Loan Integration Provider", {"name": ("in", SUREPASS_PROVIDERS)})
