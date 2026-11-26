# Framework hardening change log

One entry per stage of the approved plan (audit doc, 25 Nov 2026). Branch: `framework-hardening`.
Full rollback at any time: `git checkout baseline-2026-11-25`. India stays in today's `config/`, `state/` and `runs/` folders.

## Gates
- **Offline gate** (every stage): `.venv/bin/python -m pytest -q` must stay at >= 177 passed, 0 failed, 0 skipped.
- **Live Golden gate** (stages that touch Nexus behaviour, only with authorisation): run the Golden cases, compare with
  `runs/golden/` (frozen 25 Nov 2026, see `runs/golden/manifest.json`). A field that was MATCH/PASS in the baseline and is
  anything else now blocks the stage. Environment failures (NOT_RECEIVED, session, timeout) are reported apart and re-run.

## Stage 0 - Safeguard (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `.gitignore` (new), `requirements.lock.txt` (new), `README.md` (install line), this file (new); `runs/golden/` (local only, not in git) |
| Reason | Audit C1, M7, M8: reproducible start, stop committing customer data, pinned versions |
| Baseline commit | `308aa41`, tag `baseline-2026-11-25`: the checker fixes of 20-23 Nov (select_parent wait, read_parents retry, loader-aware clicks, AMF ids in delete, live page on start) |
| Existing behaviour affected | None: no code changed in this stage |
| `.gitignore` | Ignores `.env`, `secrets/`, `state/`, `.venv/`, caches, `runs/`, `samples/`, `knowledge_base/`. Files already tracked stay tracked (history untouched); removing them from the repo is a separate decision |
| Golden baseline | `runs/golden/2026-11-20/` (21 cases) and `runs/golden/2026-11-19/` (REG-001, SEA-REG-002): 30 files, read-only, SHA-256 in `manifest.json` |
| Database | Backup `state/backup/agent_20261125_stage0.db`; schema unchanged |
| Tests | Offline gate: see the stage 0 commit message |
| Rollback | `git revert <stage 0 commit>`; `runs/golden/` can be deleted, nothing reads it yet |

## Stage 1 - Config check and start-up banner (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `nexus_agent/config.py` (`ConfigError`, `REQUIRED_SETTINGS`, `REQUIRED_UAT_SELECTORS`, `Config.config_dir`, `.tenant`, `.problems()`, `.validate()`, `.banner()`), `nexus_agent/__main__.py` (validate + banner right after the config is built), `tests/test_config.py` (new, 6 tests), `README.md` |
| Reason | Audit H5: a missing key failed mid-run with a KeyError; nothing showed which tenant, Nexus, database or runs folder a run used |
| Existing behaviour affected | None for a valid config. The banner goes to **stderr**, so stdout is unchanged: `cases` (18 lines), `bugs --list` (1,347 lines) and `history` (1,206 lines) were byte-identical to the baseline tag. `Config()` used directly (tests, modules) does not validate, as before |
| New behaviour | Every `./nx` command prints `[nexus-agent] tenant=... profile=... nexus=... config=... db=... runs=...` on stderr; a broken config stops with exit 2 and lists every problem at once. `tenant` defaults to `india` when settings has no `tenant:` key (India's settings.yaml is not changed) |
| Tests | Offline gate: see the stage 1 commit message. Live Golden gate: not needed (no Nexus behaviour changed) |
| Rollback | `git revert <stage 1 commit>` |

## Stage 2 - Tenant layout (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `nexus_agent/config.py` (`DEFAULT_TENANT`, `available_tenants`, `tenant_config_dir`, `Config(tenant=...)`, isolation checks), `nexus_agent/__main__.py` (`--tenant`), `run_regression.sh` (`--tenant`, log folder and recipient from the tenant's config), `nexus_agent/casedoc.py` (workbook folder from settings), `tests/test_tenant_isolation.py` (new, 10 tests), `regression_prompts/EXECUTE_CMD.md` |
| Reason | Audit H1: one database, session and runs folder for everything |
| Layout | India (default, or `--tenant india`): today's `config/`, `state/`, `runs/`, nothing moved. Any other tenant: `config/<name>/` with `tenant: <name>`; its `state_dir`, `runs_dir` and `session_file` must sit in a `<name>` folder, else the run stops. `--tenant` and `--config` together are refused. No Dubai or Japan config is created in this stage |
| Shared on purpose | `state/ocr_cache` (keyed by the page image itself, holds no tenant result), `secrets/` OAuth client (each tenant names its own token files in settings) |
| Existing behaviour affected | None for India: `./nx --tenant india cases` = `./nx cases` (stdout identical); `run_regression.sh` dry-run of all 23 cases lists the same 32 emails as the 23 Nov 2026 dry-run, logs still go to `runs/_logs`, the "SENDING to ..." line names the same mailbox (now read from config). A dry-run still ends with exit 1, as before |
| Tests | Offline gate: see the stage 2 commit message. Live Golden gate: pending your authorisation |
| Rollback | `git revert <stage 2 commit>` |

## Stage 3 - India rules moved to settings (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `nexus_agent/directbl.py` (`INDIA_RULES`, `rules_for`, `evaluate(..., rules=)`, tenant point-1 title, `summary` ordering), `nexus_agent/validate.py` (`INDIA_MASTER_SPLIT_NOTE`, `known_cause_note`, `root_causes(..., master_split_note=)`), `config/settings.yaml` (new `direct_bl:` block and `validation.known_root_causes`, India's current values), `tests/test_tenant_rules.py` (new, 7 tests) |
| Rules moved | Direct BL destination country / name / expected text and excluded consignees (were `"IN"` and `("FLYJAC", "LOGISTEED")` in code); the REG-006 developer note in the "Probable root cause" box. `hawb_pattern` and `airport_names` were already in settings: unchanged |
| Reason | Audit H2: India's rules applied to every tenant silently |
| India | Values written explicitly into `config/settings.yaml`; built-in India defaults kept as a fallback. 15 input combinations give rows, summary and report text identical to `baseline-2026-11-25`; point-1 sections and fields equal the frozen Golden report of 20 Nov 2026 |
| Other tenants | Use only their own `direct_bl:` (nothing merged from India). Without it, the destination and consignee points are NOT_RUN with the reason; no root-cause note unless they set one |
| Fixed on the way | The point-1 row "Identified as Direct BL" now carries the tenant's point-1 title too (identical for India) |
| Tests | Offline gate: see the stage 3 commit message. Live Golden gate: due (stages 2 and 3), pending your authorisation |
| Rollback | `git revert <stage 3 commit>` |

## Quality-gate step 1 - `./nx golden` (2026-11-25)
Plan: "Regression Quality Gate: Bug Patterns and Test Strategy" (approved 25 Nov 2026), step 1.
| Item | Detail |
| --- | --- |
| Files | `nexus_agent/golden.py` (new), `nexus_agent/__main__.py` (`golden` command), `tests/test_golden.py` (new, 10 tests), `regression_prompts/EXECUTE_CMD.md` |
| What | Compares a run's reports (mapping, all field checks, AMF drafts, Direct BL) with the frozen baseline per Golden case. REGRESSION / NOT CHECKED / MISSING block (FAIL, exit 1); ENVIRONMENT (not received, read ERROR) gives INCOMPLETE (exit 3); IMPROVED, KNOWN and NEW FINDING are reported. The baseline is checked against its SHA-256 manifest first; a changed file stops the gate |
| Checked on real data | 20 Nov 2026 reports: 0 regressions (SEA-REG-002 missing that day, REG-001 not received); 19 + 20 Nov: INCOMPLETE, only REG-001 |
| Existing behaviour affected | None (new read-only command) |
| Tests | Offline gate: see the commit message |
| Rollback | `git revert <commit>` |

## Run time: one Nexus search pass per run (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `nexus_agent/cleanup.py` (per-run search cache in `preflight`; `remember_preflight`, `fresh_clear`; rows carry their search filter), `nexus_agent/__main__.py` (suite reuses a fresh CLEAR preflight), `config/settings.yaml` (`local_docs.preflight_reuse_minutes: 60`), `tests/test_preflight_reuse.py` (new, 3 tests) |
| Reason | A run searched every bill up to three times (delete, preflight, the send's own check), and the 7 AMF cases repeat 13 shared bills: about 40 to 50 minutes of a 2.5-hour run |
| Safety | Only a CLEAR result is reused, only within 60 minutes, and only if nothing of that case was sent since; any other case is searched again. `0` or no setting = always search (old behaviour). The per-run cache returns exactly the rows a fresh search would |
| Tests | Offline gate: see the commit message |
| Rollback | `git revert <commit>`, or set `preflight_reuse_minutes: 0` |

## Run report: every checked case with its screenshots (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `nexus_agent/runreport.py` (`_traces` any parent; `build` adds `missing`, `drafts`, `directbl`; HTML sections for them), `nexus_agent/__main__.py` (`validate-drafts` / `validate-directbl` rewrite the report), `tests/test_runreport_sections.py` (new) |
| Problem | Screenshots were taken only from a trace with a House viewer screenshot (a Manifest-first case has none: AMF-007 showed 0); not-received cases, AMF drafts and Direct BL results were not in the report, and the report was written before those checks ran |
| Now | Viewer screenshots from any parent; a section with the not-received screenshot for each case missing from Pre-Alerts; AMF drafts and Direct BL sections with every point and their screenshots; a check that could not find its pre-alert says so as a possible lookup problem |
| 25 Nov report | Regenerated from the existing files: 24 case sections, 0 broken image links; nothing re-run in Nexus |
| Tests | Offline gate: 214 passed |
| Rollback | `git revert <commit>` |

## Tenant login: one user, one Org Code per tenant (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `nexus_agent/nexus/session.py` (`org_from_cookies`, `WrongOrganisation`, `active_org`, `assert_org`, login with Org Code), `nexus_agent/config.py` (banner `org=`; non-India tenants must set `nexus.organisation_code`), `config/settings.yaml` (`login_path: /auth/logIn`, `organisation_code: UNI`), `config/selectors.uat.yaml` (login fields `#orgId`, `#username`, `#password`, submit), `tests/test_tenant_login.py` (new, 9 tests) |
| Why | India, Dubai and Japan share one Nexus URL and one test user; only the Org Code on the login form differs, so a saved session alone cannot tell tenants apart |
| How | The session's ID token carries `custom:organization_code`. Every UI run checks it against the tenant's `organisation_code`; a missing, expired or other-organisation session is signed in again with the tenant's Org Code (NEXUS_USER / NEXUS_PASSWORD from `.env`), checked, then saved to that tenant's session file only. Without credentials, a wrong organisation stops the run. The mock (no Org Code field) is not checked |
| India | Organisation UNI, read from the India session in use; live check 25 Nov 2026: signed in, UNI = UNI |
| Tests | Offline gate: 223 passed |
| Rollback | `git revert <commit>` |

## Dubai and Japan tenants signed in (2026-11-25)
| Item | Detail |
| --- | --- |
| Commit | `0da47d8`: `config/dubai` (Org Code LAE), `config/japan` (LJP); sign-in handles 'Choose where to go' -> Sentinel Nexus, Proceed when shown, or a direct landing in Nexus; guards stop sends / bug logging / Drive uploads while a tenant value is TO-BE-PROVIDED |
| Credentials | Shared test user in `.env` (not in git, never logged) |
| Live check | All three organisations sign in; sessions saved per tenant; India (UNI), Dubai (LAE) and Japan (LJP) sessions all stay valid side by side without re-login |
| Still to provide per tenant | recipient mailbox, bug sheet, Drive evidence folder, case workbooks and samples, Direct BL rules, branch airports |
| Tests | Offline gate: 226 passed |

## Samples grouped per tenant (2026-11-25)
| Item | Detail |
| --- | --- |
| Layout | `samples/india/` (all 109 India sample files, moved with `git mv`: tracking unchanged), `samples/dubai/`, `samples/japan/`, each with `_inbox/` |
| Files | `config/settings.yaml` (`testsuite.samples_dir: samples/india`), `nexus_agent/testsuite.py` (the SAMPLE_MISSING message names the tenant's folder), tests pointed at `samples/india` |
| India unchanged | `./nx cases` finds every sample; an offline dry-run of the 23 daily cases lists the same 32 emails with no SAMPLE_MISSING |
| Tests | Offline gate: 226 passed, 0 skipped |
| Rollback | `git revert <commit>` |

## Document says is never blank: precise extraction for the whole framework (2026-11-26)
| Item | Detail |
| --- | --- |
| Rule | Every checked field shows the value extracted from the document; "no value found in the document" when there is none; never blank (all tenants, whole framework) |
| Files | `nexus_agent/docextract.py` (new: labelled values, value forms, matching line, NO_VALUE, fill_blanks), `nexus_agent/docvalue.py` (small boxes read by position: heading must start its cell in capitals, value directly under it in its column, rejects terms text / heading rows / bracketed notes), `nexus_agent/sea_check.py` (page map `_pages.json`; every row gets the document value and where it was read), safety net in `master_check.write_report`, `mhfields`, `drafts_check`; tests `tests/test_docextract.py`, `tests/test_sea.py` |
| Checked on a real bill (SEA-REG-009 sample) | Port of Discharge MUNDRA, INDIA; Place of Delivery PATLI, INDIA; Port of Loading FREDERICIA, DENMARK; Vessel ONE RELIABILITY 020E; Place of issue AARHUS; Bill No ONEYAARG05243800; Move Type FCL / FCL CY / CY; Voyage: no value found (printed inside the vessel box) |
| Verdicts | Unchanged (shown values only); deciding verdicts on the extracted value is a separate step, gated by the Golden baseline |
| Japan | `_pages.json` per sample: exact Master / House pages; 008's Master from 009's document, 003's Houses from the telex release |
| Tests | 234 passed |

## Several Houses in one pre-alert: validate the sample's House, report the extra one (2026-11-26)
| Item | Detail |
| --- | --- |
| Problem | Checkers took the FIRST House row / viewer parent. In IPA/11/2026-27 (SEA-JPN-001) the first House was an extra, empty House made from the MBL's terms page, so the real House GFSLHKG/NGO26003 was never validated and its "bugs" were the extra House's empty fields |
| Rule | Validate the House whose bill is the sample's HBL (or printed on the sample's House pages, punctuation ignored); every other House (empty bill or not in the sample) is a FAIL row "Pre-alert · additional House" with its bill, parties, pages and status |
| Files | new `nexus_agent/house_pick.py`; used by `sea_check.py`, `house_check.py`, `mhfields.py` (no crash on 'House 1'), `directbl.py`, `master_check.py`; tests `tests/test_house_pick.py` |
| Extraction | Seal No never the container number; location codes (HKG / JP) say the document prints the port name instead of matching a random cell |
| Tests | 250 passed |

## Field-level precision + Japan test data corrections (2026-11-26)
| Item | Detail |
| --- | --- |
| Strict layer | `nexus_agent/strict_check.py` in every Sea check: a field must be inside ITS OWN box (blank box with a Nexus value = REVIEW, value from another box = FAIL; text bills only); a party must be the same party (name at the start of its box, legal words / branch suffix ignored: CONTEC ≠ TAIWAN CONTEC, EVEX GLOBAL FREIGHT ≠ GLOBAL FREIGHT SOLUTION); Shipper and Consignee on one Party ID while the bill prints two parties = FAIL. Only makes rows stricter |
| Label check | `nexus_agent/label_check.py`: a sample labelled with one document type whose printed title is another is listed before any run |
| Japan workbook | SEA-JPN-002/102, 005/105, 008/108: the files filed as "DEBIT NOTE" print INVOICE -> expected Invoice -> House (files renamed). 006/106 keep the real Debit Note / Credit Note -> Master (rule: Debit Note always under Master) |
| Found by it | IPA/11 shared Party ID CONCOLITM, IPA/11 Master Shipper EVEX vs GLOBAL FREIGHT SOLUTION, IPA/12 SERVIMEX vs SERPA, blank Place of Delivery boxes filled by Nexus (IPA/12, IPA/14) |
| Tests | 258 passed |

## Japan rule: invoice with LOGISTEED EXPRESS = Debit Note -> Master (2026-11-26)
| Item | Detail |
| --- | --- |
| Rule (user) | A document titled INVOICE that has LOGISTEED EXPRESS anywhere on it, or that starts with LOGISTEED, is a Debit Note and belongs to the Master. Replaces the "Invoice -> House" correction above for 002/102, 005/105, 008/108 |
| Nexus | Does not implement it yet (shows Invoice under House). Reported as KNOWN ("Nexus feature not implemented"), not FAIL, no new sheet bug; `validation.agent_debit_note_gap: fail` once Nexus has the feature |
| Files | new `nexus_agent/debit_rule.py`; `pdf_split.sea_page_labels` (such pages = DEBITNOTE); `validate.compare` (`gaps` -> KNOWN, KNOWN passes); `docs_check` (Debit Note not under Master -> fields checked on the House Invoice panel + KNOWN type row); `label_check` (DEBIT NOTE label right for such invoices); `local_sender.individual_type` ('DEBIT NOTE' in a file name = DEBITNOTE); `config/japan/settings.yaml` (`agent_bill_to: [LOGISTEED EXPRESS]`, `agent_bill_starts: [LOGISTEED]`, `agent_debit_note_gap: known`) |
| Japan workbook | 002/102, 005/105, 008/108 back to Debit Note -> Master; 008/108 has two (Airlog invoice 3014590 and the profit-share invoice 3014750); files renamed "DEBIT NOTE - ..." |
| Not affected | SEA-JPN-001 commercial invoice (to CONTEC) stays Invoice -> House; 006/106 real debit note unchanged; India has no names configured (rule off) |
| Tests | 264 passed (`tests/test_debit_rule.py`) |

## Split-document check (2026-11-26)
| Item | Detail |
| --- | --- |
| Found by eye | IPA/12/2026-27: the 4-page MAERSK booking amendment had 1 page linked as SHIPPERDOC under the House and 3 pages left in Unmatched Documents as SHIPPERDOC (Japan sheet Sl 20). Missed because the mapping check drops Unmatched groups whose label is linked somewhere (meant for the viewer repeating linked documents) |
| Check | `validate.split_documents(parents)`, run before that filter: a label both linked and in Unmatched with a different page count = FAIL "document split: n page(s) linked under <parent>, m more left in Unmatched; all n+m pages should be one document". The same page count is still read as a repeat (a 1+1 split is not caught) |
| Applies to | every UAT mapping check (Air and Sea, all tenants) |
| Tests | 266 passed (`tests/test_split_documents.py`) |

## LOGISTEED rule widened + Master Document XML check (2026-11-26)
| Item | Detail |
| --- | --- |
| Rule | Japan sheet Sl 19 (Enhancement, Yamini): any LOGISTEED party (partial match: LOGISTEED EXPRESS, Logisteed India Private Limited ...) on an INVOICE = Debit Note -> Master. `agent_bill_to: [LOGISTEED]`. Same 7 sample documents as before; no India / Dubai sample matches |
| XML check | new `nexus_agent/doc_xml_check.py` + `./nx check-doc-xml --cases <CASE> [--xml folder]`: every 'NEXUS PUSH DOC' XML of the Consol (ForwardingConsol) is read; a Debit Note attached (PDF titled DEBIT NOTE, an INVOICE with a LOGISTEED party, or Nexus type / file name saying Debit Note) = FAIL. The PDFs inside the XML are read, so a debit note pushed as 'INV' is caught. NOT_RUN without pushed files (the agent never pushes) |
| Checked on | the India reference Master Document XML (PASS, 1 MBL); a scratch copy with the IPA/12 SERPA invoice added as 'INV' (FAIL, as expected) |
| Tests | 269 passed (`tests/test_doc_xml_check.py`) |
