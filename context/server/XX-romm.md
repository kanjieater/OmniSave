Right separation of concerns. Mixing metadata resolution + sync = can't reason about failure modes.

Lock as **standalone "Metadata Integration Proposal"** above sync system. ROMM = **game identity + library resolution service**. No syncing. No virtual client semantics. Just identity + mapping.

---

# 🎮 OmniSave V1: ROMM Metadata Integration Proposal

## 0. Purpose

OmniSave resolves:
* game identity
* metadata enrichment
* canonical grouping of saves under titles

via ROMM as external metadata authority.

> Strictly **read-only re metadata**. Does NOT participate in snapshot sync.

---

## 1. Core Principle (hard boundary)

> ROMM = **Metadata Authority Layer**, not Sync Participant.

### ROMM allowed:
* identify games
* resolve title names
* provide box art / icons
* group save containers under canonical games
* provide ROM/library structure

### ROMM NOT allowed:
* influence HEAD
* influence snapshot lineage
* trigger sync events
* act as device/client in sync graph

---

## 2. Metadata Resolution Pipeline

Every snapshot enters **Game Resolution Phase** before timeline commit.

```text
Device Save Upload
   ↓
Raw Snapshot Ingestion
   ↓
ROMM Metadata Lookup
   ↓
Game Binding Resolution
   ↓
Canonical Snapshot Creation
