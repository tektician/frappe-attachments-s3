<a href="https://zerodha.tech"><img src="https://zerodha.tech/static/images/github-badge.svg" align="right" /></a>

## Frappe S3 Attachment

Frappe app to make file upload automatically upload and read from s3.

> Tektician fork of [zerodha/frappe-attachments-s3](https://github.com/zerodha/frappe-attachments-s3),
> which gets few updates. It collects the useful upstream PRs and adds fixes on top.
> See [Changes in this fork](#changes-in-this-fork).

#### Features.

1. Upload both public and private files to s3.
2. Stream files from S3, when file is viewed everytime.
3. Lets you add S3 credentials
    (aws key, aws secret, bucket name, folder name) through ui and migrate existing
    files.
4. Deletes from s3 whenever a file is deleted in ui.
5. Files are uploaded categorically in the format.
    {s3_folder_path}/{year}/{month}/{day}/{doctype}/{file_hash}

#### Installation.

1. bench get-app https://github.com/tektician/frappe-attachments-s3.git
2. bench --site <site> install-app frappe_s3_attachment

#### Configuration Setup.

1. Open single doctype "s3 File Attachment"
2. Enter (Bucket Name, AWS key, AWS secret, S3 bucket Region name, Folder Name)
    Folder Name- folder name is the default folder path in s3.
    For S3-compatible storage (MinIO, Cloudflare R2, Hetzner, DigitalOcean Spaces, ...)
    also set Endpoint URL; leave it empty for AWS S3.
3. Migrate existing files lets all the existing files in private and public folders
    to be migrated to s3.
    The migration runs as background jobs (long queue) in batches of 500;
    per-file failures are written to the Error Log.
4. Delete From Cloud when selected deletes the file form s3 bucket whenever a file
    is deleted from ui. By default the Delete from cloud will be unchecked.
    An object is only deleted once no other File record uses it.
5. Set public-read ACL on public files (on by default) uploads public files with the
    `public-read` ACL. Buckets created on AWS since April 2023 have ACLs disabled and
    reject that. For such buckets, uncheck it and add the public-read bucket policy
    below. Public files are stored under a `public/` prefix (after the folder name,
    if set), so the policy exposes only public files and never private ones.
6. Until a bucket name is saved, uploads stay on local disk, so installing the app
    does not break uploads.
7. Attachments of Data Import, Prepared Report and any doctype listed in
    `ignore_s3_upload_for_doctype` (site config) stay on local disk. Code can also
    set `file_doc.flags.skip_s3_upload = True` before inserting a File.

#### Changes in this fork

Upstream PRs included:

- #71 AWS policy documentation (cherrycharan)
- #91 `pyproject.toml` `[project]` section (Sakshi-Greycube)
- #94, #99 non-ASCII file names, skip folders / Prepared Report, `skip_s3_upload` flag (DriveX)
- #76, #83 Endpoint URL for S3-compatible storage (ported)
- #95 read file content from s3, background migration (ported)
- #98, #29, #39 upload hook fixes, #81 encrypted secret (ideas ported)

Fixes on top:

- **Security:** `generate_file` checks that the user can read a File that uses the key
  before it signs a URL. Before, any logged-in user could download any private file
  by key.
- **Security:** the AWS secret is stored encrypted (Password field). A patch migrates
  the existing value.
- The File upload hook is no longer a whitelisted API method.
- Deleting a File no longer deletes an s3 object that other File records still use,
  and local files no longer send their content hash to s3 as a key.
- Migration repoints every File record that shares a local file before removing it.
- Packaging moved to flit; the `urllib3<2` pin that downgraded Frappe's urllib3 was removed.

### AWS Policies for Successful Configuration

To successfully upload and serve images to/from the S3 bucket, use the following policies:

#### S3 Bucket Policy

Replace the placeholders with your AWS Account ID and Bucket Name.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::<AWS_ACCOUNT_ID>:user/<YOUR_IAM_USER>"
            },
            "Action": [
                "s3:GetBucketLocation",
                "s3:ListBucket",
                "s3:GetObject"
            ],
            "Resource": [
                "arn:aws:s3:::<YOUR_BUCKET_NAME>",
                "arn:aws:s3:::<YOUR_BUCKET_NAME>/*"
            ]
        }
    ]
}
```
#### Public-read Policy (buckets with ACLs disabled)

Only needed when "Set public-read ACL on public files" is unchecked. Use
`<FOLDER_NAME>/public/*` if you set a folder name. Do **not** use `<YOUR_BUCKET_NAME>/*`,
because that would make private files public too.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadForPublicFiles",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::<YOUR_BUCKET_NAME>/public/*"
        }
    ]
}
```

The bucket's "Block public access" settings must allow public bucket policies.

#### IAM Policy
Attach this policy to your IAM user or role that Frappe uses to interact with S3:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "s3:*",
            "Resource": [
                "arn:aws:s3:::<YOUR_BUCKET_NAME>",
                "arn:aws:s3:::<YOUR_BUCKET_NAME>/*"
            ]
        }
    ]
}
```
#### CORS Policy
Set this CORS configuration for your S3 bucket to allow access from your Frappe application:
```json
[
    {
        "AllowedHeaders": ["*"],
        "AllowedMethods": ["GET", "POST", "PUT", "DELETE"],
        "AllowedOrigins": ["https://<YOUR_FRAPPE_APPLICATION_DOMAIN>"],
        "ExposeHeaders": ["ETag", "x-amz-meta-custom-header"],
        "MaxAgeSeconds": 3000
    }
]
```


### Explanation of the Combined Policies

1. **S3 Bucket Policy**:
   - Combines all necessary actions (`s3:GetBucketLocation`, `s3:ListBucket`, `s3:GetObject`) into a single policy statement for simplicity.
   - Specifies the principal (IAM user or role) that needs these permissions.
   - Applies the actions to both the bucket itself (`arn:aws:s3:::<YOUR_BUCKET_NAME>`) and all objects within the bucket (`arn:aws:s3:::<YOUR_BUCKET_NAME>/*`).

2. **IAM Policy**:
   - Provides full S3 access (`s3:*`) to the specified bucket and its objects.
   - Attach this policy to the IAM user or role that the Frappe app uses to manage S3.

3. **CORS Policy**:
   - Ensures that your Frappe application can interact with S3 by allowing necessary HTTP methods and headers for cross-origin requests.

### Usage

Replace placeholders with actual values:
- **`<AWS_ACCOUNT_ID>`**: Your AWS Account ID.
- **`<YOUR_IAM_USER>`**: The IAM user or role for the Frappe application.
- **`<YOUR_BUCKET_NAME>`**: Your S3 bucket name.
- **`<YOUR_FRAPPE_APPLICATION_DOMAIN>`**: The domain of your Frappe application.

By using these policies, you ensure that your Frappe app can successfully upload, read, and manage files in your S3 bucket.

#### License

MIT
