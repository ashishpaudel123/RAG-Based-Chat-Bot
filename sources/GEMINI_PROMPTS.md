# Gemini prompts for building the knowledge base

Prompt 1 (source inventory) is done: see `source_inventory.json` and the checklist in `README.md`.
Run the prompts below **after** you have downloaded the must-have PDFs into `sources/pdfs/`.

Workflow per batch:

```bash
# 1. Save Gemini's whole answer (copy it into a .txt file, or export it as .docx)
# 2. Split it into record files and check them
cd backend
python -m app.cli import-gemini ../sources/batches/batch1.txt --out ../knowledge_base
python -m app.cli check-records ../knowledge_base
# 3. Fix any ERROR lines (or ask Gemini to regenerate that record), then ingest
python -m app.cli ingest ../knowledge_base
# 4. Restart the backend, check each record against its PDF, click Verify in Admin -> Knowledge base
```

---

## Prompt 2: Master instructions (new chat; upload the PDFs and paste source_inventory.json)

```text
You are building the knowledge base for "Nepal Citizenship Assistant", a RAG chatbot. You will write KNOWLEDGE RECORDS
that are indexed and retrieved; the chatbot answers ONLY from these records, so accuracy and traceability matter more than length.

SOURCES: Use ONLY the PDFs I uploaded, and the official URLs in the source inventory JSON I pasted. Do not use memory, blogs or
your own earlier research report as evidence. If an uploaded PDF's text looks garbled (legacy Preeti font), read the page images.
IMPORTANT: Only use an amendment (for example the "Second Amendment Act 2082" or "Fourth Amendment Regulation 2082") if its
official text is among the uploaded PDFs. If a source is only mentioned in the inventory but not uploaded, do not state its
contents; write "स्रोत उपलब्ध छैन (source text not available)" instead.

ABSOLUTE RULES (never break these):
1. Never invent a legal provision, section/rule number, fee, form, office, processing time, deadline, required document or URL.
2. Every legal statement must name its exact source and section/rule (e.g. "नेपाल नागरिकता ऐन, २०६३, दफा ३(१)").
3. If a detail is not in the sources, write exactly: "स्रोतमा उल्लेख छैन (not stated in the source)".
4. Keep LAW (Act/Regulation/Constitution), PROCEDURE (directive/official process), LOCAL PRACTICE (a DAO's charter; always
   name the district and date) and INFERENCE (your conclusion; start with "अनुमान / Inference:") clearly separate.
5. Where the rule depends on facts (age, which parent is a citizen, place of birth, father identified or not, spouse's
   nationality), say so and give each case separately. Never write one generic answer for fact-dependent cases.
6. Mark old/replaced rules as status: superseded or historical with effective dates. Never present them as current.
   When the Act or Regulation was amended, describe the CURRENT amended rule and mention what changed and when.
7. Write in simple Nepali first, then English, like a helpful knowledgeable person, not a government PDF.
8. One record = one topic (e.g. "duplicate citizenship when lost"), 300–1200 words. Do not merge unrelated topics.
9. Supreme Court decisions: use source_type court_decision, authority_tier 1, and summarise only what the decision text says.

OUTPUT FORMAT: for each record output a line "FILE: <id>.md" and then ONE fenced markdown code block containing the complete
file, exactly in this structure (keep the YAML keys exactly; use null when unknown):

FILE: <id>.md
```markdown
---
id: citizenship.<category>.<topic>.<nnn>
title: "<नेपाली शीर्षक> (<English title>)"
source_type: <constitution|act|amendment|regulation|directive|circular|official_notice|form|court_decision|dao_charter|local_notice|official_portal|secondary>
authority_tier: <1-5>
issuing_authority: "<…>"
source_title: "<exact official title of the MAIN source>"
section: "<exact section/rule of the MAIN source, e.g. दफा ३ / नियम ४>"
category: <taxonomy category, e.g. citizenship_by_descent>
jurisdiction: Nepal
district: null
status: current
effective_from: "<date or null>"
effective_until: null
source_url: "<exact official URL from the inventory>"
source_document_id: "<id from the inventory, e.g. src-act-2063>"
last_verified: null
verification_status: pending
language: [ne, en]
amendment_status: "<…>"
confidence: <high|medium|low>
related_sources:
  - "<other source title + section used>"
user_questions:
  - "<नेपाली प्रश्न>"
  - "<another नेपाली phrasing>"
  - "<roman nepali, e.g. nagarikta harayo duplicate kasari banaune>"
  - "<noisy roman, e.g. nagrikta harayo k garne>"
  - "<English question>"
  - "<mixed, e.g. citizenship lost vayo k garne>"
---
# <नेपाली शीर्षक> (<English title>)

## सारांश (Summary)
## कानुनी नियम (Legal rule)
## योग्यता (Eligibility)
## आवश्यक कागजात (Required documents)
## प्रक्रिया (Procedure)
## निवेदन दिने ठाउँ (Authority / where to apply)
## दस्तुर र समय (Fees and time)
## विशेष अवस्था र अपवाद (Special cases and exceptions)
## सामान्य गल्ती र भ्रम (Common mistakes and misconceptions)
## अस्पष्ट वा स्रोतमा नभएका कुरा (Unclear / not in the source)
## स्रोत (Sources)
## प्रयोगकर्ताले सोध्ने तरिका (How users ask)
```

TAXONOMY (category values): citizenship_basics, citizenship_by_descent, citizenship_through_mother, birth_based_citizenship,
naturalized_citizenship, matrimonial_citizenship, children_and_minors, non_resident_nepali_citizenship, honorary_citizenship,
first_time_certificate, duplicate_and_replacement, lost_citizenship, damaged_citizenship, correction_and_amendment,
name_and_surname, marriage_and_divorce, foreign_spouse, dual_citizenship, renunciation, reacquisition,
citizenship_verification, citizenship_records, false_or_fraudulent_citizenship, ward_recommendation, dao_procedure,
area_administration, forms_and_schedules, documents_and_evidence, fees, processing_time, appeal_and_complaint,
national_identity_interaction, historical_law, faq_and_common_misconceptions.

For fraud topics: explain legal consequences only; never explain how to fabricate documents or avoid detection.

Reply "READY" and wait. I will then ask for records batch by batch.
```

## Prompt 3: Record batches (same chat, one batch per message)

```text
Write the knowledge records for these categories: <BATCH>.
Make one record per distinct topic/case (e.g. for citizenship_through_mother: father Nepali / father foreign / father unknown are
SEPARATE records). Follow every ABSOLUTE RULE and the exact OUTPUT FORMAT. After the records, list: (a) topics you could not cover
because the sources are silent, (b) any place where sources conflict, with both sources cited.
```

1. `citizenship_basics, citizenship_by_descent, citizenship_through_mother, birth_based_citizenship, historical_law`
2. `naturalized_citizenship, matrimonial_citizenship, foreign_spouse, children_and_minors, honorary_citizenship`
3. `non_resident_nepali_citizenship, dual_citizenship, renunciation, reacquisition, national_identity_interaction`
4. `first_time_certificate, duplicate_and_replacement, lost_citizenship, damaged_citizenship, forms_and_schedules, documents_and_evidence`
5. `correction_and_amendment (one record per correction type: name, surname, date of birth, place of birth, parent name, spouse name, address, gender, spelling, Nepali/English mismatch, citizenship type), name_and_surname, marriage_and_divorce`
6. `citizenship_verification, citizenship_records, false_or_fraudulent_citizenship, ward_recommendation, dao_procedure, area_administration, fees, processing_time, appeal_and_complaint, faq_and_common_misconceptions`
7. Supreme Court decisions (only if you uploaded their text): `one record per decision, category citizenship_through_mother`

If Gemini stops in the middle, reply "continue from FILE: <last id>".

## Prompt 4: District (local practice) records (same chat; upload the DAO citizen charters)

```text
Now write LOCAL PRACTICE records from the uploaded District Administration Office citizen charters and notices. One record per
district per service (first-time citizenship, duplicate, correction, marriage-based, NRN, …). Use the same OUTPUT FORMAT with:
source_type: dao_charter (or local_notice), authority_tier: 3, district: "<District name in English>", jurisdiction: "<District>",
issuing_authority: "District Administration Office, <District>", and the charter's date as effective_from.
Include: service name, documents the office lists, fee, time, responsible section, contact, URL.
State clearly in the summary that this is that office's published practice on that date and not national law.
If the charter is older than the 2079 First Amendment, say so in "Unclear / not in the source".
If two official pages give different fees or documents, record BOTH with their sources and say they conflict.
```

## Prompt 5: Spelling and Roman Nepali dictionary

```text
Create a spelling/romanization dictionary for a Nepali citizenship chatbot. Output ONLY a JSON object where each key is the
correct Devanagari term and the value is a list of variants people actually type: Roman Nepali spellings, common misspellings,
phonetic and speech-to-text errors, missing spaces, English equivalents and abbreviations. Cover at least 80 terms (नागरिकता,
वंशज, अंगीकृत, वैवाहिक, जन्मसिद्ध, गैरआवासीय, सम्मानार्थ, प्रतिलिपि, हराएको, च्यातिएको, सच्याउने, संशोधन, सिफारिस, वडा, गाउँपालिका,
नगरपालिका, जिल्ला प्रशासन कार्यालय, इलाका प्रशासन कार्यालय, प्रमुख जिल्ला अधिकारी, जन्मदर्ता, विवाहदर्ता, बसाइँसराइ, नाता प्रमाणित,
सनाखत, सर्जमिन मुचुल्का, आमा, बाबु, पति, पत्नी, नाबालिग, राष्ट्रिय परिचयपत्र, राहदानी, दस्तुर, कागजात, निवेदन, अनुसूची, परित्याग,
पुनः प्राप्ति, दोहोरो नागरिकता, थर, जन्ममिति, ठेगाना, लिङ्ग, बनाउने, निकाल्ने, कसरी, के के चाहिन्छ …).
Example: {"नागरिकता": ["nagarikta","nagrikta","nagarikataa","nagrita","citizenship","citizen ship"]}
```

Paste the result into the `"synonyms"` object in `backend/app/profiles/nepal_citizenship.json` (keep it valid JSON).

## Prompt 6: Evaluation question set (same chat as prompt 2, after the records exist)

```text
Using ONLY the records you wrote (use their exact `id` values), create a gold evaluation set. Output ONLY JSON:
{"version": "1.0", "description": "Nepal citizenship gold set", "questions": [ ... ]}
Each question: {"id": "<category>-<lang>-<nn>", "question": "", "language": "ne|en|roman_ne|mixed",
 "noise_level": "clean|medium|high", "expected_intent": "<intent>", "expected_sources": ["<record id>"],
 "expected_answer_facts": ["<2-4 short exact phrases copied from the record>"],
 "must_not_claim": ["<plausible but WRONG claims>"], "expect_clarification": true|false}
120+ questions; every category at least 3; about 35% ne, 30% roman_ne, 20% en, 15% mixed; about 30% medium/high noise;
15 incomplete questions with expect_clarification true and expected_sources []; 10 out-of-scope (expected_sources []);
10 district-specific; 10 historical; 10 law vs current office practice.
```

Save it as `evaluation/questions_citizenship.json`.

## Prompt 7: Self-audit (same chat, last)

```text
Audit every record you produced. For each record output one line: id | each legal claim checked against the uploaded source
(OK / WRONG / NOT FOUND) | any number, fee, date or section that is not verbatim in the source | fixes needed.
Then output corrected versions (same FILE: format) of any record that has a problem.
```
