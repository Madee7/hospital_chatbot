# Known Issues

> **Audience:** developers / ops  
> **Purpose:** known limitations and workarounds — update when fixed or newly confirmed

---

## Status legend

| Status | Meaning |
|:-------|:--------|
| **Open** | Confirmed; needs a fix or config change |
| **Planned** | Improvement already decided / in progress |
| **By design** | Expected behavior or platform constraint |

---

## Issue cards

### 1) GitHub Actions auto-deploy fails (SSH auth)

| Field | Detail |
|:------|:-------|
| **Status** | Open |
| **Area** | CI / Deploy |

**What happens**

- Workflow `Deploy to Windows server` fails on push/merge to `main`.
- Typical error: SSH handshake / authentication failure (`publickey`).

**Why**

- The Action cannot authenticate to the Windows server with the configured SSH secrets/key.

**Workaround**

1. Merge to `main` as usual.
2. On server: `git pull`
3. Run migrations if needed
4. `Restart-Service HospitalChatbotBackend`
5. See [`DEPLOY.md`](DEPLOY.md)

---

### 2) Doctor “carousel” is not a native WhatsApp carousel

| Field | Detail |
|:------|:-------|
| **Status** | Open / by design (platform constraint) |
| **Area** | Doctor browsing UX |

**What happens**

- Patients expect a left/right photo carousel like some chatbot builders.
- Default flow shows **separate sequential image cards** (scroll the chat), not one official WhatsApp carousel bubble.

**Why**

- Official WhatsApp **carousel templates** need an approved marketing/template setup.
- Session messages cannot freely send that native carousel type.
- Default `send_doctor_cards` sends up to **5** interactive image cards in sequence.

**Optional Flow path**

- With `USE_DOCTOR_FLOW=true` + Flow ID → WhatsApp Flows **ImageCarousel** + radio list.
- Meta Flows ImageCarousel is limited (max **3** images in current code comments).
- If Flow is disabled/fails → fallback to sequential cards.
- Setup: [`WHATSAPP_FLOW_SETUP.md`](WHATSAPP_FLOW_SETUP.md)

**Expectation**

- Treat sequential cards (or Flow ImageCarousel when enabled) as the supported UX.
- Specialty path loads a limited doctor set for cards (small code limit, e.g. 5).

---

### 3) “By doctor name” list can hide doctors beyond the first page/limit

| Field | Detail |
|:------|:-------|
| **Status** | Planned improvement |
| **Area** | Booking → by doctor name |

**What happens**

- **By doctor name** opens a WhatsApp list of doctors.
- Some active doctors may not appear if they fall outside the first-page/limit.
- The same doctor may still appear via **by specialty**.

**Why**

- WhatsApp list messages are capped at **10 rows**.
- Current code also requests a limited doctor set.
- Alphabetical ordering can push later names off the first page.

**Planned direction**

- Pagination and/or search-by-typed-name (not one unbounded list).

**Temporary workaround**

- Use **By specialty**, or type a doctor name if matching still finds them.

---

### 4) Local dashboard numbers may differ from server

| Field | Detail |
|:------|:-------|
| **Status** | By design |
| **Area** | Dashboard / environments |

**What happens**

- `localhost:8501` KPIs can differ from `http://196.219.86.38:8501/`.

**Why**

- Local and server usually use different databases/config.

**Workaround**

- Treat the **server** dashboard as the official source for production numbers.

---

## Template for new entries

```md
### N) Short title

| Field | Detail |
|:------|:-------|
| **Status** | Open | Planned | Fixed | By design |
| **Area** | ... |

**What happens**
- ...

**Why**
- ...

**Workaround**
- ...
```
