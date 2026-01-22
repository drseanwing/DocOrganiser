# n8n Workflows - Visual Flow Diagram

## System Integration Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     DOCUMENT ORGANIZER WORKFLOW                          │
└─────────────────────────────────────────────────────────────────────────┘

┌──────────────┐
│   OneDrive/  │
│  SharePoint  │
│              │
│  Source      │
│  Folder      │
└──────┬───────┘
       │
       │ 1. Download Request
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  WORKFLOW 1: Download (workflow_download.json)                        │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [Manual/Schedule] → [Get OAuth Token] → [Create Job]               │
│         │                                        │                   │
│         ▼                                        ▼                   │
│  [List Folder Contents] ← ← ← ← ← ← ← ← ← [Pagination]             │
│         │                                                            │
│         ▼                                                            │
│  [Build Complete File List (Recursive)]                             │
│         │                                                            │
│         ▼                                                            │
│  [Split Into Batches (10 files)]                                    │
│         │                                                            │
│         ▼                                                            │
│  [Download Files] ──┐                                               │
│         │           │ Loop until all downloaded                     │
│         └───────────┘                                               │
│         │                                                            │
│         ▼                                                            │
│  [Create ZIP Archive]                                               │
│         │                                                            │
│         ▼                                                            │
│  [Save to /data/input/source_{jobId}.zip]                           │
│         │                                                            │
│         ▼                                                            │
│  [Update Job Status: 'downloaded']                                  │
│         │                                                            │
└─────────┼────────────────────────────────────────────────────────────┘
          │
          │ Webhook Trigger
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  WORKFLOW 2: Trigger (workflow_trigger.json)                         │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [Webhook Trigger] → [Validate Payload]                             │
│         │                                                            │
│         ▼                                                            │
│  [Verify ZIP File Exists]                                           │
│         │                                                            │
│         ▼                                                            │
│  [Update Job: 'processing']                                         │
│         │                                                            │
│         ▼                                                            │
│  [Check Trigger Method]                                             │
│    ├─ HTTP ──→ [Call Container API]                                │
│    └─ File ──→ [Create .ready file]                                │
│         │                                                            │
│         ▼                                                            │
│  [Respond to Webhook]                                               │
│                                                                       │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
                                │ Container starts processing
                                ▼
                    ┌────────────────────────┐
                    │  DOCKER CONTAINER      │
                    │  (Document Processor)  │
                    ├────────────────────────┤
                    │                        │
                    │  1. Extract ZIP        │
                    │  2. Index Files        │◄─┐
                    │  3. Detect Duplicates  │  │
                    │  4. Version Control    │  │ Progress
                    │  5. Organize Structure │  │ Callbacks
                    │  6. Create Report      │  │
                    │  7. Package Output ZIP │  │
                    │                        │  │
                    └────────────┬───────────┘  │
                                 │              │
                                 │ Webhooks     │
                                 ▼              │
┌──────────────────────────────────────────────────────────────────────┐
│  WORKFLOW 4: Webhook Receiver (workflow_webhook.json)                │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [Webhook: /processing-callback]                                     │
│         │                                                            │
│         ▼                                                            │
│  [Parse Payload] → [Route by Event Type]                            │
│         │               │                                            │
│         ▼               ├─ 'processing_started' → [Update Status]   │
│    [Log Event]          │                                            │
│                         ├─ 'phase_complete' → [Update Progress]     │◄┘
│                         │     (25% → 50% → 75% → 90%)               │
│                         │                                            │
│                         ├─ 'review_required' → [Check Auto-Approve] │
│                         │     ├─ YES → [Approve Processing]         │
│                         │     └─ NO  → [Send Review Email]          │
│                         │                                            │
│                         ├─ 'processing_complete' ──────────┐        │
│                         │                                   │        │
│                         └─ 'processing_failed' → [Log] → [Email]    │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                                 │
                                 │ Completion Webhook
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│  WORKFLOW 3: Upload (workflow_upload.json)                           │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [Webhook: /processing-complete]                                     │
│         │                                                            │
│         ▼                                                            │
│  [Get Job Details from DB]                                          │
│         │                                                            │
│         ▼                                                            │
│  [Get OAuth Token]                                                  │
│         │                                                            │
│         ▼                                                            │
│  [Determine Upload Strategy]                                        │
│         │                                                            │
│         ├─ Strategy: 'extract' ──────────────┐                      │
│         │                                     │                      │
│         │  [Extract ZIP]                     │                      │
│         │       │                             │                      │
│         │       ▼                             │                      │
│         │  [Create Folder Structure]         │                      │
│         │       │                             │                      │
│         │       ▼                             │                      │
│         │  [Prepare Files]                   │                      │
│         │       │                             │                      │
│         │       ▼                             │                      │
│         │  [Split Into Batches (5 files)]    │                      │
│         │       │                             │                      │
│         │       ▼                             │                      │
│         │  [Upload Files] ──┐                │                      │
│         │       │           │ Loop           │                      │
│         │       └───────────┘                │                      │
│         │       │                             │                      │
│         │       ▼                             │                      │
│         │  [Aggregate Results] ──────────────┘                      │
│         │                                                            │
│         └─ Strategy: 'zip-only' ─────────────┐                      │
│                                               │                      │
│              [Upload ZIP File]               │                      │
│                    │                          │                      │
│                    └──────────────────────────┘                      │
│                    │                                                 │
│                    ▼                                                 │
│         [Update Job: 'completed']                                   │
│                    │                                                 │
│                    ▼                                                 │
│         [Cleanup Temp Files]                                        │
│                    │                                                 │
│                    ▼                                                 │
│         [Check Send Notification]                                   │
│            ├─ YES → [Send Email]                                    │
│            └─ NO  → [Skip]                                          │
│                    │                                                 │
│                    ▼                                                 │
│         [Respond to Webhook]                                        │
│                                                                      │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           │ Files uploaded
                           ▼
                    ┌──────────────┐
                    │   OneDrive/  │
                    │  SharePoint  │
                    │              │
                    │ Reorganized  │
                    │   Folder     │
                    └──────────────┘


═══════════════════════════════════════════════════════════════════════
                          DATA FLOW SUMMARY
═══════════════════════════════════════════════════════════════════════

1. User triggers download (manual or scheduled)
   └─► Workflow 1 downloads source folder as ZIP

2. ZIP saved to /data/input/
   └─► Workflow 2 triggers Docker container processing

3. Container processes files (Index → Dedup → Version → Organize)
   ├─► Sends progress callbacks to Workflow 4
   └─► Creates output ZIP at /data/output/

4. Container sends completion callback
   └─► Workflow 3 uploads results back to cloud

5. Job marked as completed in database
   └─► Notification sent to user


═══════════════════════════════════════════════════════════════════════
                       WEBHOOK ENDPOINTS
═══════════════════════════════════════════════════════════════════════

POST /webhook/trigger-processing
  → Triggers Workflow 2 (from Workflow 1)
  → Payload: { jobId, zipPath, fileCount }

POST /webhook/processing-callback
  → Triggers Workflow 4 (from Container)
  → Payload: { event, job_id, timestamp, ... }
  → Events: processing_started, phase_complete, review_required,
            processing_complete, processing_failed

POST /webhook/processing-complete
  → Triggers Workflow 3 (from Workflow 4)
  → Payload: { job_id, output_path, stats }


═══════════════════════════════════════════════════════════════════════
                     DATABASE STATE TRANSITIONS
═══════════════════════════════════════════════════════════════════════

Status Flow:
  pending 
    ↓ (Workflow 1 starts)
  downloading
    ↓ (ZIP created)
  downloaded
    ↓ (Workflow 2 triggered)
  processing
    ↓ (Container working)
  review_required / approved
    ↓ (If approved)
  executing
    ↓ (Changes applied)
  packaging
    ↓ (ZIP created)
  uploading
    ↓ (Workflow 3 complete)
  completed

  (Any step can transition to 'failed' on error)


═══════════════════════════════════════════════════════════════════════
                     ERROR HANDLING FLOWS
═══════════════════════════════════════════════════════════════════════

Download Failure:
  [Download Error] → [Update Job: 'failed'] → [Log Error]

Processing Failure:
  [Container Error] → [Webhook: failed event] → 
  [Update Job: 'failed'] → [Email Notification]

Upload Failure:
  [Upload Error] → [Update Job: 'failed'] → 
  [Keep Files] → [Email Notification]

Network/API Failures:
  [Error] → [Retry (3x with backoff)] → 
  [Success] OR [Final Failure] → [Log & Notify]


═══════════════════════════════════════════════════════════════════════
