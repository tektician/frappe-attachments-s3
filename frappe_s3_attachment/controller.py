from __future__ import unicode_literals

import datetime
import os
import random
import re
import string
from urllib.parse import parse_qs, quote, unquote, urlparse

import boto3

from botocore.client import Config
from botocore.exceptions import ClientError

import frappe


import magic


class S3Operations(object):

    def __init__(self):
        """
        Function to initialise the aws settings from frappe S3 File attachment
        doctype.
        """
        self.s3_settings_doc = frappe.get_doc(
            'S3 File Attachment',
            'S3 File Attachment',
        )
        client_kwargs = {
            'region_name': self.s3_settings_doc.region_name,
            # Empty means AWS; set it for S3-compatible storage (MinIO, R2, ...)
            'endpoint_url': self.s3_settings_doc.endpoint_url or None,
            'config': Config(signature_version='s3v4'),
        }
        if (
            self.s3_settings_doc.aws_key and
            self.s3_settings_doc.aws_secret
        ):
            client_kwargs.update(
                aws_access_key_id=self.s3_settings_doc.aws_key,
                aws_secret_access_key=self.s3_settings_doc.aws_secret,
            )
        self.S3_CLIENT = boto3.client('s3', **client_kwargs)
        self.BUCKET = self.s3_settings_doc.bucket_name
        self.folder_name = self.s3_settings_doc.folder_name

    def strip_special_chars(self, file_name):
        """
        Strips file charachters which doesnt match the regex.
        """
        regex = re.compile('[^0-9a-zA-Z._-]')
        file_name = regex.sub('', file_name)
        return file_name

    def key_generator(self, file_name, parent_doctype, parent_name):
        """
        Generate keys for s3 objects uploaded with file name attached.
        """
        parent_doctype = parent_doctype or 'File'
        parent_name = parent_name or file_name

        hook_cmd = frappe.get_hooks().get("s3_key_generator")
        if hook_cmd:
            try:
                k = frappe.get_attr(hook_cmd[0])(
                    file_name=file_name,
                    parent_doctype=parent_doctype,
                    parent_name=parent_name
                )
                if k:
                    return k.rstrip('/').lstrip('/')
            except:
                pass

        file_name = file_name.replace(' ', '_')
        file_name = self.strip_special_chars(file_name)
        key = ''.join(
            random.choice(
                string.ascii_uppercase + string.digits) for _ in range(8)
        )

        today = datetime.datetime.now()
        year = today.strftime("%Y")
        month = today.strftime("%m")
        day = today.strftime("%d")

        doc_path = None

        if not doc_path:
            if self.folder_name:
                final_key = self.folder_name + "/" + year + "/" + month + \
                    "/" + day + "/" + parent_doctype + "/" + key + "_" + \
                    file_name
            else:
                final_key = year + "/" + month + "/" + day + "/" + \
                    parent_doctype + "/" + key + "_" + file_name
            return final_key
        else:
            final_key = doc_path + '/' + key + "_" + file_name
            return final_key

    def upload_files_to_s3_with_key(
            self, file_path, file_name, is_private, parent_doctype, parent_name
    ):
        """
        Uploads a new file to S3.
        Strips the file extension to set the content_type in metadata.
        """
        mime_type = magic.from_file(file_path, mime=True)
        key = self.key_generator(file_name, parent_doctype, parent_name)
        content_type = mime_type
        try:
            if is_private:
                self.S3_CLIENT.upload_file(
                    file_path, self.BUCKET, key,
                    ExtraArgs={
                        "ContentType": content_type,
                        "Metadata": {
                            "ContentType": content_type,
                            "file_name": quote(file_name, safe="")
                        }
                    }
                )
            else:
                self.S3_CLIENT.upload_file(
                    file_path, self.BUCKET, key,
                    ExtraArgs={
                        "ContentType": content_type,
                        "ACL": 'public-read',
                        "Metadata": {
                            "ContentType": content_type,

                        }
                    }
                )

        except boto3.exceptions.S3UploadFailedError:
            frappe.throw(frappe._("File Upload Failed. Please try again."))
        return key

    def delete_from_s3(self, key):
        """ Delete file from s3"""
        if self.s3_settings_doc.delete_file_from_cloud:
            try:
                self.S3_CLIENT.delete_object(
                    Bucket=self.s3_settings_doc.bucket_name,
                    Key=key
                )
            except ClientError:
                frappe.throw(frappe._("Access denied: Could not delete file"))

    def read_file_from_s3(self, key):
        """
        Function to read file from a s3 file.
        """
        return self.S3_CLIENT.get_object(Bucket=self.BUCKET, Key=key)

    def get_url(self, key, file_name=None):
        """
        Return url.

        :param bucket: s3 bucket name
        :param key: s3 object key
        """
        if self.s3_settings_doc.signed_url_expiry_time:
            self.signed_url_expiry_time = self.s3_settings_doc.signed_url_expiry_time # noqa
        else:
            self.signed_url_expiry_time = 120
        params = {
                'Bucket': self.BUCKET,
                'Key': key,

        }
        if file_name:
            params['ResponseContentDisposition'] = "inline; filename*=UTF-8''{}".format(
                quote(file_name, safe=''))

        url = self.S3_CLIENT.generate_presigned_url(
            'get_object',
            Params=params,
            ExpiresIn=self.signed_url_expiry_time,
        )

        return url


GENERATE_FILE_PATH = '/api/method/frappe_s3_attachment.controller.generate_file'


def get_s3_key(file_url, s3=None):
    """
    Return the s3 key a File's file_url points to, or None when the file
    is not stored on s3 by this app.
    """
    if not file_url:
        return None

    parsed = urlparse(file_url)
    if parsed.path == GENERATE_FILE_PATH:
        return parse_qs(parsed.query).get('key', [None])[0]

    if file_url.startswith(('http://', 'https://')):
        s3 = s3 or S3Operations()
        prefix = '{}/{}/'.format(s3.S3_CLIENT.meta.endpoint_url, s3.BUCKET)
        if file_url.startswith(prefix):
            return unquote(file_url[len(prefix):])

    return None


def get_files_for_key(key, exclude=None):
    """
    Names of all File rows backed by the given s3 key. Several rows can
    share one object, e.g. when Frappe copies an attachment.
    """
    filters = {'name': ('!=', exclude)} if exclude else {}
    candidates = frappe.get_all(
        'File',
        filters=filters,
        or_filters={
            'content_hash': key,
            'file_url': ('like', '%{}%'.format(key)),
        },
        fields=['name', 'file_url', 'content_hash'],
    )
    # the LIKE above is only a prefilter ("_" is a wildcard), match exactly
    return [
        f.name for f in candidates
        if f.content_hash == key or get_s3_key(f.file_url) == key
    ]


def file_upload_to_s3(doc, method):
    """
    File after_insert hook: move the uploaded local file to s3.
    """
    if getattr(doc.flags, "skip_s3_upload", False):
        return

    # Folder-type File records (e.g. the site's "Home" folder, created on
    # demand by make_home_folder()) have no file_url - nothing to upload.
    if doc.is_folder or not doc.file_url:
        return

    # Already on s3 or remote, e.g. a File row copied from another one
    # (amended docs, email/comment attachments). There is no local file.
    if not doc.file_url.startswith(('/files/', '/private/files/')):
        return

    path = doc.file_url
    site_path = frappe.utils.get_site_path()
    parent_doctype = doc.attached_to_doctype or 'File'
    parent_name = doc.attached_to_name
    ignore_s3_upload_for_doctype = set(frappe.local.conf.get('ignore_s3_upload_for_doctype') or [])
    ignore_s3_upload_for_doctype.update(['Data Import', 'Prepared Report'])
    if parent_doctype not in ignore_s3_upload_for_doctype:
        if not doc.is_private:
            file_path = site_path + '/public' + path
        else:
            file_path = site_path + path

        if not os.path.exists(file_path):
            return

        s3_upload = S3Operations()
        key = s3_upload.upload_files_to_s3_with_key(
            file_path, doc.file_name,
            doc.is_private, parent_doctype,
            parent_name
        )

        if doc.is_private:
            method = "frappe_s3_attachment.controller.generate_file"
            file_url = """/api/method/{0}?key={1}&file_name={2}""".format(
                method, key, quote(doc.file_name, safe=""))
        else:
            file_url = '{}/{}/{}'.format(
                s3_upload.S3_CLIENT.meta.endpoint_url,
                s3_upload.BUCKET,
                key
            )
        os.remove(file_path)
        frappe.db.sql("""UPDATE `tabFile` SET file_url=%s, folder=%s,
            old_parent=%s, content_hash=%s WHERE name=%s""", (
            file_url, 'Home/Attachments', 'Home/Attachments', key, doc.name))

        doc.file_url = file_url
        doc.content_hash = key

        # Only repoint the field this file was uploaded for, and only if it
        # still holds the local url (not every attachment is the image).
        if doc.attached_to_field and doc.attached_to_name and frappe.db.get_value(
            parent_doctype, parent_name, doc.attached_to_field
        ) == path:
            frappe.db.set_value(
                parent_doctype, parent_name, doc.attached_to_field, file_url,
                update_modified=False
            )

        frappe.db.commit()


@frappe.whitelist()
def generate_file(key=None, file_name=None):
    """
    Redirect to a short-lived signed url for a private s3 file.
    Only allowed if the user can read a File record backed by this key.
    """
    if key:
        if not any(
            frappe.has_permission('File', 'read', doc=name)
            for name in get_files_for_key(key)
        ):
            raise frappe.PermissionError

        s3_upload = S3Operations()
        signed_url = s3_upload.get_url(key, file_name)
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = signed_url
    else:
        frappe.local.response['body'] = "Key not found."
    return


def upload_existing_files_s3(name):
    """
    Function to upload all existing files.
    """
    file_doc_name = frappe.db.get_value('File', {'name': name})
    if file_doc_name:
        doc = frappe.get_doc('File', name)
        s3_upload = S3Operations()
        path = doc.file_url
        site_path = frappe.utils.get_site_path()
        parent_doctype = doc.attached_to_doctype or 'File'
        parent_name = doc.attached_to_name or doc.name
        if not doc.is_private:
            file_path = site_path + '/public' + path
        else:
            file_path = site_path + path

        # File exists?
        if not os.path.exists(file_path):
            return

        key = s3_upload.upload_files_to_s3_with_key(
            file_path, doc.file_name,
            doc.is_private, parent_doctype,
            parent_name
        )

        if doc.is_private:
            method = "frappe_s3_attachment.controller.generate_file"
            file_url = """/api/method/{0}?key={1}""".format(method, key)
        else:
            file_url = '{}/{}/{}'.format(
                s3_upload.S3_CLIENT.meta.endpoint_url,
                s3_upload.BUCKET,
                key
            )

        # Remove file from local.
        os.remove(file_path)

        frappe.db.sql(
            """UPDATE `tabFile` SET file_url=%s, folder=%s,
            old_parent=%s, content_hash=%s WHERE name=%s""",
            (file_url, "Home/Attachments", "Home/Attachments", key, doc.name),
        )
        frappe.db.commit()


def s3_file_regex_match(file_url):
    """
    Match the public file regex match.
    """
    return re.match(
        r'^(https:|/api/method/frappe_s3_attachment.controller.generate_file)',
        file_url
    )


@frappe.whitelist()
def migrate_existing_files():
    """
    Function to migrate the existing files to s3.
    """

    files_list = frappe.get_all(
        'File',
        fields=['name', 'file_url']
    )
    for file in files_list:
        if file['file_url']:
            if not s3_file_regex_match(file['file_url']):
                upload_existing_files_s3(file['name'])
    return True


def delete_from_cloud(doc, method):
    """
    File on_trash hook: delete the s3 object, unless another File row
    still uses it.
    """
    if doc.is_folder or not frappe.db.get_single_value(
        'S3 File Attachment', 'delete_file_from_cloud'
    ):
        return

    s3 = S3Operations()
    # Key from the url, not content_hash: local files keep a real content
    # hash there, which must never be sent to s3 as a key.
    key = get_s3_key(doc.file_url, s3)
    if not key or get_files_for_key(key, exclude=doc.name):
        return

    s3.delete_from_s3(key)


@frappe.whitelist()
def ping():
    """
    Test function to check if api function work.
    """
    return "pong"
