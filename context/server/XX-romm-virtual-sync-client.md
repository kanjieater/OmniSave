ROMM = **Virtual Sync Client (VSC)**, not physical device. Participates in snapshot pipeline under different capability model.

Forcing into "device" abstraction breaks:
* trust lifecycle (approve/revoke)
* connectivity semantics (online/offline)
* hardware constraints (storage, upload chunking, power state)

---

# OmniSave V1: ROMM as Virtual Sync Client (VSC) Spec

## 1. Core Model

Split "device" into two categories:

### A. Physical Device Client
* Switch, PC, handhelds — anything producing saves at edge

### B. Virtual Sync Client (NEW)
* ROMM, future integrations (Steam Cloud, PSN, etc.)

---

## 2. Why NOT treat ROMM as device?

As device, incorrectly inherits:
* device approval flows
* hardware trust semantics
* polling tied to physical uptime
* "offline device" failure models

ROMM instead:
* always logically available (or degraded)
* stateless from hardware perspective
* bidirectional bulk, not event-streamed

---

## 3. Top-Level Abstraction: "Sync Client"

Everything in snapshot exchange is Sync Client.

```ts id="sync_client_1"
type SyncClient =
  | PhysicalDeviceClient
  | VirtualSyncClient;
