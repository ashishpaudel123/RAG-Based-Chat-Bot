# Source inventory

`source_inventory.json` lists the official sources for the Nepal citizenship knowledge base (spec §18).
It was produced by Gemini Deep Research and **reviewed but not yet verified**: Claude Code could not open the
government websites from its environment, so every entry still needs a person to check it.
`gemini_research_report.md` is Gemini's narrative report. Use it only to understand the topic; never cite it
as evidence.

## How to use this folder

1. Work through the checklist below, starting with the **critical** rows. For each source:
   open the URL, confirm the title, date and amendment status, and fix the JSON if anything differs
   (set `review.url_checked` / `review.verified_by_human` to `true`).
2. Download the official PDF into `sources/pdfs/<source_document_id>.pdf`. These are the files you upload to
   Gemini with prompt 2.
3. **Preeti font check:** open each PDF, copy a line of Nepali text and paste it into Notepad. Garbage like
   `gful/stf` instead of `नागरिकता` means a legacy font; tell Gemini to "read the page images" for that file.
4. Find the **missing sources** listed at the end.

You need at least the five **must-have** sources before running prompt 2:
the consolidated Constitution, the consolidated Citizenship Act (including the 2079 First Amendment),
the consolidated Citizenship Regulation with Schedules, the Distribution Directive, and 1–2 DAO citizen charters.

## Checklist

| Done | Priority | ID | Source | Type | URL | What to check |
|---|---|---|---|---|---|---|
| [ ] | **critical** | `src-act-amend1-2079` | Nepal Citizenship (First Amendment) Act, 2079 | amendment (tier 1) | — (find it) | Find the official text: Nepal Law Commission (recent Acts) or Nepal Gazette 2080. Or use the consolidated Act that already includes it. |
| [ ] | **critical** | `src-act-amend2-2082` | Nepal Citizenship (Second Amendment) Act, 2082 | amendment (tier 1) | https://dop.gov.np/content/12736/citizenship-act-2082/ | UNCONFIRMED: verify in the Nepal Gazette (rajpatra.dop.gov.np) that this Act exists and its exact date. The House of Representatives was dissolved around 12 September 2025 (Bhadra 2082), so an Act published on 2082-06-05 needs checking. amendment_status 'current consolidated text' is wrong for an amending Act; it amends the 2063 Act. Gemini did not quote any provision from it; do not write records from it until the official text is in hand. |
| [ ] | **critical** | `src-reg-amend4-2082` | Nepal Citizenship (Fourth Amendment) Regulation, 2082 | amendment (tier 1) | https://dop.gov.np/category/sankhya-2082/?page=8 | source_url is a Gazette LIST page, not the document. Find the exact PDF link. Its description depends on the unconfirmed Second Amendment Act 2082; verify both together. |
| [ ] | **high** | `src-const-2072` | Constitution of Nepal | constitution (tier 1) | https://lawcommission.gov.np/content/13437/nepal-s-constitution/ | Confirm the linked text includes BOTH amendments (2072 first amendment and 2077 second amendment); download the consolidated Nepali text. |
| [ ] | **high** | `src-act-2063` | Nepal Citizenship Act, 2063 | act (tier 1) | https://lawcommission.gov.np/content/12939/12939-nepal-citizenship-act-2063/ | This entry is the ORIGINAL 2063 text. Download the latest consolidated text (संशोधनसहित) that includes the 2079 First Amendment; the original alone is outdated. Gemini notes Preeti/scanned PDF: check that text copies correctly; otherwise let Gemini read page images. |
| [ ] | **high** | `src-reg-2063` | Nepal Citizenship Regulation, 2063 | regulation (tier 1) | https://lawcommission.gov.np/content/12656/12656-nepal-citizenship-regulation/ | ORIGINAL 2063 text. Get the consolidated Regulation including all amendments (1st, 2nd, 3rd 2080, 4th 2082). The 1st and 2nd Regulation amendments are missing from this inventory. |
| [ ] | **high** | `src-directive-2063` | Citizenship Certificate Distribution Directive, 2063 | directive (tier 1) | https://moha.gov.np/en/post/na-gara-kata-pa-rama-naepata-ra-va-taranae-ka-ra-yava-thha-na-ra-tha-sha-ka | Publication date 2068-04-18 for a '2063' directive suggests an amended version; confirm which version the PDF is. Preeti font PDF: check text extraction. |
| [ ] | **high** | `src-dao-bhaktapur-charter` | Citizen Charter - DAO Bhaktapur | dao_charter (tier 3) | https://daobhaktapur.moha.gov.np/office-layout/647 | Charter from 2076 (2019) predates the 2079 amendment: check for a newer charter; older fees/documents may be outdated (spec §20). |
| [ ] | **high** | `src-dao-panchthar-charter` | Citizen Charter - DAO Panchthar | dao_charter (tier 3) | https://daopanchthar.moha.gov.np/en/page/na-gara-ka-bda-pata-ra-11 | Charter from 2075 (2019) predates the 2079 amendment: check for a newer version. |
| [ ] | **high** | `src-sc-8557` | Sabina Damai v. Government of Nepal (Decision No. 8557) | court_decision (tier 1) | https://nkp.gov.np/full_detail/124 | URL nkp.gov.np/full_detail/124 looks suspicious for decision no. 8557: confirm the page shows this case. Supreme Court precedents are binding (Constitution Art. 128(4)); kept at authority tier 1. |
| [ ] | **medium** | `src-act-amend1-ord-2078` | Nepal Citizenship (First Amendment) Ordinance, 2078 | amendment (tier 1) | https://lawcommission.gov.np/content/12384/12384-nepal-citizenship-first-amend/ | Ordinance only (lapsed/replaced). Keep as historical; do not use as current law. |
| [ ] | **medium** | `src-reg-amend3-2080` | Nepal Citizenship (Third Amendment) Regulation, 2080 | amendment (tier 1) | https://moha.gov.np/en/post/na-pa-l-na-gara-kata-ta-sa-ra-sa-sha-thhana-na-yama-val-2 | Dates disagree (Gazette 2080-06-04 vs MOHA 2080-06-09); record the Gazette date. |
| [ ] | **medium** | `src-dao-ktm-charter` | Citizen Charter - DAO Kathmandu | dao_charter (tier 3) | https://daokathmandu.moha.gov.np/en/page/citizen-charter-23 | No date: note the date shown on the charter page; treat as local practice of DAO Kathmandu only. |
| [ ] | **medium** | `src-dao-lalitpur-charter` | Citizen Charter - DAO Lalitpur | dao_charter (tier 3) | https://daolalitpur.moha.gov.np/service/390 | No date: note the date shown on the page. |
| [ ] | **medium** | `src-dao-lalitpur-nrn-notice` | Non-Resident Nepali Citizenship Notice | local_notice (tier 3) | https://daolalitpur.moha.gov.np/assets/163/Suchana_NRN_20231019_0001.pdf/file | Check the date in the PDF (file name suggests 2023-10-19). |
| [ ] | **medium** | `src-dao-kaski-charter` | Duplicate Citizenship Certificate - DAO Kaski | dao_charter (tier 3) | https://daokaski.moha.gov.np/service/646 | Verify the claim about records destroyed by fire before 2047-01-17 directly on the page. |
| [ ] | **medium** | `src-dao-morang-charter` | Citizen Charter - DAO Morang | dao_charter (tier 3) | https://daomorang.moha.gov.np/assets/72/%E0%A4%A8%E0%A4%BE%E0%A4%97%E0%A4%B0%E0%A4%BF%E0%A4%95_%E0%A4%B5%E0%A4%A1%E0%A4%BE%E0%A4%AA%E0%A4%A4%E0%A5%8D%E0%A4%B0.pdf/file | No date: note the date in the PDF. |
| [ ] | **medium** | `src-donidcr-mother-circular` | Circular regarding NID details registration of citizens holding citizenship via mother | circular (tier 2) | https://donidcr.gov.np/content/412/circular-regarding-registration-of-national-identity-card/ | Verify date 2082-11-26 and the circular text. |
| [ ] | **medium** | `src-sc-9627` | Sajda Sapkota v. Government of Nepal (Decision No. 9627) | court_decision (tier 1) | https://nkp.gov.np/full_detail/8670 | Confirm decision date and the URL. |
| [ ] | **medium** | `src-sc-9687` | Srijan Kharel (Deepti Gurung) v. Government of Nepal (Decision No. 9687) | court_decision (tier 1) | https://nkp.gov.np/full_detail/8730 | Confirm decision date and the URL. |
| [ ] | **medium** | `src-sc-9841` | Uma Bhattarai v. DAO Morang (Decision No. 9841) | court_decision (tier 1) | https://nkp.gov.np/full_detail/8892 | Confirm decision date and the URL. |
| [ ] | **low** | `src-dao-ktm-notice-amend1` | Citizenship Notice (2080-03-10) | local_notice (tier 3) | https://daokathmandu.moha.gov.np/post/citizenship-14 | Local notice; good evidence of practice after the 2079 amendment. |
| [ ] | **low** | `src-aao-tikapur` | Duties and Rights of Area Administration Office, Tikapur | official_portal (tier 2) | https://aaotikapur.moha.gov.np/page/iil-ka-pa-rasha-sana-ka-ra-ya-lyaka-ka-mahara | Describes duties only; not a source for fees/documents. |
| [ ] | **low** | `src-aao-pharping` | Nepali Citizenship Information - AAO Pharping | official_portal (tier 2) | https://aaopharping.moha.gov.np/page/about-nepali-citizenship | — |
| [ ] | **low** | `src-donidcr-faq` | National ID Frequently Asked Questions | official_portal (tier 2) | https://donidcr.gov.np/pages/abboyed-asked-questions--rational-identity-10/ | Title has a typo in the URL; confirm the page opens. |

## Missing sources

- [ ] Nepal Citizenship (First Amendment) Act, 2079 official text (or consolidated Act including it)
- [ ] Nepal Citizenship (First and Second Amendment) Regulations (not listed)
- [ ] Consolidated Nepal Citizenship Regulation, 2063 with all amendments and Schedules (अनुसूची) 1-11
- [ ] MOHA circular(s) on implementing the 2079 First Amendment
- [ ] Newer citizen charters for DAO Bhaktapur and Panchthar (listed ones are from 2075/2076)

## Problems found in Gemini's output

- **Reported to exist (text still needed):** the "Nepal Citizenship (Second Amendment) Act, 2082" (published 2082-06-05)
  needs confirming in the Nepal Gazette. The House of Representatives was dissolved around 12 September 2025, so
  an Act dated after that is unusual. The Fourth Amendment Regulation 2082 depends on the same claim. Do not
  write any knowledge record from either one until you have the official text.
- **Wrong link:** the Fourth Amendment Regulation URL points to a list page in the Gazette, not to the document.
- **Outdated base texts:** the Act and Regulation entries point to the *original* 2063 texts. The knowledge
  base must use the consolidated (amended) versions, or each amendment separately.
- **Missing key source:** the First Amendment Act 2079 (the most important recent change) has no official text
  in the inventory. I added it from Gemini's own table.
- **Old local charters:** the Bhaktapur (2076) and Panchthar (2075) charters predate the 2079 amendment.
- **Date conflicts:** the Third Amendment Regulation 2080 shows two different dates; use the Gazette date.
- **Court decisions:** Supreme Court precedents are binding (Constitution Art. 128(4)), so they stay at
  authority tier 1. Confirm each NKP URL; the one for decision 8557 looks suspicious.

## PDFs received (2026-10-02)

| File | What it is | Text |
|---|---|---|
| `src-act-2063.pdf` | Citizenship Act 2063, Himali font, amended only up to the 2069 ordinance (**no 2079 First Amendment**) | `text/src-act-2063.txt` |
| `src-reg-2063.pdf` | Older Regulation text (Preeti) | `text/src-reg-2063.txt` |
| `src-reg-2063-consolidated.pdf` | Regulation consolidated up to 2078 (Kalimati; garbled text layer) | `text/src-reg-2063-consolidated.raw.txt` |
| `src-reg-2063-english.pdf` | Old English translation of the Rules (first amendment only) | not used for records |
| `src-directive-2063.pdf` | Distribution Directive 2063 (Preeti, 72 pp) | `text/src-directive-2063.txt` |
| `src-toli-directive-2070.pdf` | Distribution Team (Toli) Directive 2070 (Preeti) | `text/src-toli-directive-2070.txt` |

Preeti/Himali PDFs were converted with `tools/convert_pdf_text.py` (needs `pymupdf` and `npttf2utf`).
The 21 records in `knowledge_base/citizenship/` were written from these texts and are all `pending`.

**Gazette references received (2026-10-02, no texts yet):** First Amendment Act 2079 (reported as
Gazette Vol. 73; "79" was the Act year), Second Amendment Act 2082 (Extraordinary Issue 27,
2082-06-05), Third Amendment Regulation 2080 (Gazette No. 28, 2080-06-04), Fourth Amendment Regulation 2082
(Gazette No. 55, 2082-09-21). These confirm the sources exist, but records need the actual text.

**Still needed (PDFs):** the four amendment texts above (or a consolidated Act and Regulation that include
them), the Constitution Part 2, and the DAO citizen charters. The DAO fees/timing record was written from a
summary and must be checked against a charter before it is verified.

## Excerpts received (2026-10-02, second batch)

Quoted text was supplied for Constitution Art. 10-11, Act s.3(4)/3(5) as amended in 2079, and the Bhaktapur/Sunsari
charters. It is used in the records (marked "user-supplied excerpt") and must still be checked against the official text.
Not used:
- **Second Amendment Act 2082:** only a description, no text.
- ~~"Fourth Amendment Regulation 2082" quotes~~ **Correction (2026-10-02):** I wrongly said these were 2078 rules.
  The Gazette text (below) shows the Fourth Amendment did replace rule 3(3ख)(ङ) and rule 3(6), and added National ID
  number fields to the forms. The user's excerpt was right.
- **Act s.8क (surname/address):** not seen in any text; confirm first.

## Research pack 2082/2083 (2026-10-02)

`research_pack_2082.md` (from the user's .docx) gives the official URLs of the Second Amendment Act 2082
(Act No. 08, Ministry of Law PDF), the Fourth Amendment Rules 2082 (Department of Printing page), the DAO Kathmandu
charter PDF and the MoHA NRN forms. These hosts are blocked from Claude's environment, so the PDFs still need to be
downloaded into `sources/pdfs/`. Its description of the 2082 Act (s.3(4क), 5(3)(ग), 5(5क), 5(5ख), 8क(1क), 18, 21(3क),
22क) was added as a warning to the six records it affects; nothing was quoted from it. Its 50 test questions
were added to the evaluation set (`rw-*`).

## Official texts received (2026-10-02, third batch)

| File | What it is | Text |
|---|---|---|
| `src-act-amend2-2082.pdf` | Second Amendment Act 2082 (Act No. 08, 2082-06-05), Ministry of Law PDF | `text/src-act-amend2-2082.txt` (some letters garbled) |
| `src-reg-amend4-2082.pdf` | Fourth Amendment Rules 2082, Gazette Khanda 75 No. 55 (2082-09-21), 38-page scan | `text/src-reg-amend4-2082.txt` (manual transcription) |
| `src-moha-nrn-forms-8ga/8gha/8cha.pdf` | MoHA NRN forms: application, commitment, oath | `text/src-moha-nrn-forms.txt` |

The 2082 warnings in the records were replaced with the actual provisions. New records: `mother.born_abroad`,
`minor_id_card`, `parent_name_omission`, `nrn`.

## First Amendment Act 2079 received (2026-10-02, fourth batch)

`src-act-amend1-2079.pdf`: Nepal Gazette Khanda 73, Extraordinary 6 (2080-02-17), Act No. 1 of 2080, 10-page scan;
manual transcription in `text/src-act-amend1-2079.txt`. It gave the NRN section 7क, the new s.3(3)-(8), 8(3क), 8(4)
(two citizens + one local official at the sarjamin), 8क (choose mother's or father's surname; gender identity),
21(3क)-(3घ), and repealed s.4. **Correction:** the earlier user excerpt of s.3(4) left out "before 3 Asoj 2072".
The DAO Kathmandu charter could not be downloaded (server error).

## Constitution Part 2 and "Third Amendment 2080" text (2026-10-02, fifth batch)

- **Constitution Part 2 (Art. 10-15)** text supplied in chat, saved to `text/src-const-2072-part2.txt` and used in
  `citizenship.constitution.part2.001` and as the constitutional basis in six topic records. Art. 11(3)-(5) and 14 match
  the 2079 Act Gazette wording.
- **"Third Amendment Regulation 2080 main provisions": not used.** They conflict with the official texts: the procedure
  for children of birth citizens is rule 3(3क) (2078), the self-declaration schedule is 4क (not "1क"), and NRN uses
  rule 8क with Schedules 8ग/8घ/8च (official MoHA forms), not "rule 22क / Schedules 11क, 11ग". The text also has "...".
