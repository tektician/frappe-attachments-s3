import frappe
from frappe.utils.password import set_encrypted_password


def execute():
    """aws_secret became a Password field; move the plain-text value into __Auth."""
    doctype = 'S3 File Attachment'
    secret = frappe.db.sql(
        "select value from `tabSingles` where doctype=%s and field='aws_secret'",
        doctype,
    )
    secret = secret[0][0] if secret else None
    # already masked (patch re-run, or saved through the form after the change)
    if not secret or set(secret) == {'*'}:
        return

    set_encrypted_password(doctype, doctype, secret, 'aws_secret')
    frappe.db.set_single_value(doctype, 'aws_secret', '*' * len(secret))
