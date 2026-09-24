import frappe


def execute():
    """
    public_read_acl is new; keep the old behaviour (public-read ACL on
    public files) on sites where it was never saved. A field default is
    not written for existing Single doctypes.
    """
    set_public_read_acl_default()


def set_public_read_acl_default():
    doctype = 'S3 File Attachment'
    if not frappe.db.sql(
        "select 1 from `tabSingles` where doctype=%s and field='public_read_acl'",
        doctype,
    ):
        frappe.db.set_single_value(doctype, 'public_read_acl', 1)
