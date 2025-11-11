# secops-dataexport-script
A python script that provides a CLI to export log data from Google SecOps using the [Data Export V2 (Enhanced) API](https://docs.cloud.google.com/chronicle/docs/reference/data-export-api-enhanced).

The SecOps Data Export API is used to export raw log data from Google SecOps to a Google Cloud Storage bucket.

## Features

* **Create Exports**: Initiate jobs with flexible lookback periods and log type filters.
* **Track Status**: Actively poll running jobs until they reach a terminal state (Success/Failure).
* **Manage Jobs**: List recent exports or cancel in-progress jobs[cite: 10].
* **Fetch Service Account**: Fetch the exact Chronicle Service Account that needs GCS permissions.

## Prerequisites

* **Python 3.6+**.
* **Google Cloud Service Account**: A service account with access to the SecOps/Chronicle API.
    * **Required Roles**: `Chronicle API Admin` (and potentially `Chronicle API Viewer` per documentation).
* **Target Bucket**: A Google Cloud Storage bucket to receive the data.

## Setup

### 1. Install Dependencies

```bash
pip install requests google-auth google-api-python-client google-auth-oauthlib python-dotenv google-auth-httplib2
```
### 2. Create Service Account Credentials

In the project linked to your SecOps instance, create a service account and generate authentication credentials.
* Create a service account with `Chronicle API Admin` (and potentially `Chronicle API Viewer`) roles
* Create a key and download as a json credential
> This credential is what you will use to authenticate with the Data Export API.

### 3. Create or Configure Google Cloud Storage Bucket
Create a storage bucket with the appropriate sotrage, retention, etc. policies. 
> The first time you run the script, you will need to grab the Google-managed service account and grant it access to this bucket.

### 4. Configure Environment Variables
Modify the `.env` file with relevant details:

```textproto
# --- Authentication ---
# Path to your Google Cloud service account JSON key
SECOPS_ACCOUNT_JSON="/{path}/{to}/{your}/sa-credential.json"

# Scope required for the Chronicle v1alpha API
SECOPS_SCOPES="https://www.googleapis.com/auth/cloud-platform"

# --- API Endpoint ---
# Base URL for the Chronicle API
SECOPS_API_BASE_URL="https://chronicle.us.rep.googleapis.com"

# --- SecOps Instance Details ---
# Your Google Cloud Project ID
CHRONICLE_PROJECT_ID="{your-secops-project-id}"

# The location of your Chronicle instance (e.g., "us")
CHRONICLE_LOCATION="us"

# Your Chronicle Instance ID (e.g. found in SIEM Settings > Profile, or in go/cccc)
CHRONICLE_INSTANCE_ID="{customer-instance-id}"

# Request timeout in seconds
SECOPS_REQUEST_TIMEOUT="60"

#--- Export Configuration ---
# The Google Cloud Storage bucket where data will be exported.
CHRONICLE_DATA_BUCKET="projects/{your-secops-project-id}/buckets/{your-gcs-bucket-name}"

```

## Usage

### FetchServiceAccountForDataExports (--fetch-sa)

> Before starting your first export job, you must grant Chronicle permission to write to your bucket.

Run the fetch command:

```bash
python export_script.py --fetch-sa
```

### CreateDataExport (`--create`)
By default, running the script without arguments will create a standard export (last 24 hours, all log types) and immediately start tracking it.

> Default: Last 1 day, all log types
```bash
python export_script.py --create
```


#### Customizing Exports:
Use `--days` to set the lookback period and `--log-types` (space-separated) to filter data.

> Export last 7 days of data
```bash
python export_script.py --create --days 7
```

> Export last 3 days of ONLY specific log types
```bash
python export_script.py --create --days 3 --log-types OKTA WINEVTLOG CROWDSTRIKE_EDR
```
---

### GetDataExport (`--track`)
If you have a long-running job that you want to check on, use the `--track` flag. It accepts either the short ID or the full resource path.

```bash
python export_script.py --track {export-id}
```
---

### ListDataExport (`--list`)
View a summary of recent data export jobs to see their IDs, current status, and creation times.

```bash
python export_script.py --list
```
---

### CancelDataExport (`--cancel`)
Stops an in-progress export job.

```bash
python export_script.py --cancel {export-id}
```
---

## Results
Data is exported to the GCS bucket in a directory structure that is organized by export id and the timestamp of the log data as reflected in SecOps:

```bash
{bucket-name}/{export-id}/{log-type-name}/{year}/{month}/{day}/{hour}/{minute}/{second}/{uid?}/{raw-log-data}
```

For example, an export of windows logs (WINEVTLOG) has the following file path:

```bash
secops-data-export-bucket/{export ID}/WINEVTLOG/2025/09/13/14/00/00/00001762552986167535/logdata-0.csv
```

## Troubleshooting
* **403 Forbidden**: Ensure your SECOPS_ACCOUNT_JSON service account has the required IAM roles in the Google Cloud project to access the Chronicle API.
  * Role: Chronicle API Admin
  * Role: Chronicle API Viewer (not sure if this is actually needed)
* **404 Not Found** (during tracking): The script automatically attempts to fix malformed IDs, but ensure you are using the ID from the same instance configured in your .env file.
* **Export stuck in FINISHED_FAILURE**: Check the Chronicle Service Account permissions on the GCS bucket (see "Initial Configuration").
