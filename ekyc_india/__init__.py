import frappe

__version__ = "0.0.1"


def check_app_permission():
	# Every route this app exposes lives under /app, so offering it to a website user lands
	# them on a permission error — and frappe sends them to the only app they are offered.
	from frappe.utils.user import is_website_user

	if frappe.session.user == "Administrator":
		return True

	if is_website_user():
		return False

	return True
