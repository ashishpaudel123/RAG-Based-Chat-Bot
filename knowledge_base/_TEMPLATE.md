---
# One knowledge record per file. Files starting with "_" or named README are not ingested.
id: citizenship.<category>.<topic>.001        # stable id; re-uploading the same id creates a new version
title: "<Short title in Nepali or English>"
source_type: act                 # constitution|act|amendment|regulation|directive|circular|official_notice|form|court_decision|dao_charter|local_notice|official_portal|secondary|faq|informal|other
authority_tier: 1                # optional; 1 = primary law ... 5 = informal (defaults from source_type)
issuing_authority: "<e.g. Nepal Law Commission / Ministry of Home Affairs / DAO Kathmandu>"
source_title: "<exact official document title, e.g. Nepal Citizenship Act, 2063>"
section: "<exact section/rule, e.g. दफा ३ / Section 3 / नियम ७>"
category: citizenship_by_descent # taxonomy category (spec §36)
jurisdiction: Nepal
district: null                   # set ONLY for district/office-specific practice
status: current                  # current|superseded|historical
effective_from: "<YYYY-MM-DD or YYYY-MM-DD BS>"
effective_until: null
source_url: "https://<official page or PDF>"
last_verified: "<YYYY-MM-DD when a person checked it against the source>"
verification_status: pending     # pending -> not searchable; change to verified after human review
language: [ne, en]
amendment_status: "<as amended by ... / unamended>"
confidence: high
user_questions:                  # how people actually ask (kept as metadata; also write them in the body)
  - "<नेपाली प्रश्न>"
  - "<roman nepali question>"
  - "<English question>"
---
# <Title in Nepali> (<Title in English>)

## सारांश (Summary)
<2-4 sentences in simple Nepali, then English. Only facts from the source.>

## कानुनी नियम (Legal rule)
<What the provision says; quote key wording from the source.>

## योग्यता (Eligibility)
- ...

## आवश्यक कागजात (Required documents)
- ...

## प्रक्रिया (Procedure)
1. ...

## निवेदन दिने ठाउँ (Authority / where to apply)
...

## दस्तुर र समय (Fees and time)
<Only if the source states them, with the source and date. Otherwise write: "स्रोतमा उल्लेख छैन (not stated in the source)".>

## विशेष अवस्था र अपवाद (Special cases and exceptions)
- ...

## सामान्य गल्ती (Common mistakes)
- ...

## स्रोत (Source)
<Source title, section/rule, URL, last verified date.>

## प्रयोगकर्ताले सोध्ने तरिका (How users ask)
- <नेपाली>, <roman nepali>, <English>, <mixed>
