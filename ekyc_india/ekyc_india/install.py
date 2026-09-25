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


def after_install():
	create_workflow_states()
	create_workflow_transition_tasks()
