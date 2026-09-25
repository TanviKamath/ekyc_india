import frappe


def create_workflow_states():
	workflow_states = [
		{"doctype": "Workflow State", "workflow_state_name": "eKYC Requested"},
		{"doctype": "Workflow State", "workflow_state_name": "eSignature Requested"},
	]

	for state in workflow_states:
		if not frappe.db.exists(
			"Workflow State",
			{"workflow_state_name": state["workflow_state_name"]},
		):
			doc = frappe.get_doc(state)
			doc.insert(ignore_permissions=True)


def create_workflow_transition_tasks():
	workflow_transition_tasks = [
		{
			"doctype": "Workflow Transition Tasks",
			"name": "Send eKYC Request",
			"tasks": [{"task": "Send eKYC Request", "enabled": 1}],
		},
		{
			"doctype": "Workflow Transition Tasks",
			"name": "Make eSignature Request",
			"tasks": [{"task": "Make eSignature Request", "enabled": 1}],
		},
	]

	for transition in workflow_transition_tasks:
		if not frappe.db.exists(
			"Workflow Transition Tasks",
			{"name": transition["name"]},
		):
			frappe.get_doc(transition).insert(ignore_permissions=True)


def create_integration_providers():
	# Lending owns the doctype, and this app installs without it.
	if not frappe.db.exists("DocType", "Loan Integration Provider"):
		return

	for path in frappe.get_hooks("lending_integration_adapters", app_name="ekyc_india"):
		adapter = frappe.get_attr(path)

		# Inactive: the credentials are the site's own, and lending allows one active bureau.
		if not frappe.db.exists("Loan Integration Provider", adapter.key):
			frappe.get_doc(
				{
					"doctype": "Loan Integration Provider",
					"provider_name": adapter.key,
					"provider_type": adapter.provider_type,
					"adapter": adapter.key,
					"is_active": 0,
				}
			).insert(ignore_permissions=True)


def after_install():
	create_workflow_states()
	create_workflow_transition_tasks()
	create_integration_providers()


def after_app_install(app_name):
	if app_name == "lending":
		create_integration_providers()


def after_migrate():
	# Sites that had ekyc_india before lending shipped the provider doctype.
	create_integration_providers()
