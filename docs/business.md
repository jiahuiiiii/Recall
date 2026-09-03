# Recall: An AI Relationship Assistant for Sales Teams

## Overview

Recall helps salespeople turn informal conversations into organised, actionable customer relationships.

After a networking event, sales meeting, or casual introduction, a salesperson can immediately record a voice memo such as:

> “I met Sarah from GIC. She is hiring for a quant infrastructure role and asked me to send her the Kestrel product deck next week.”

Recall converts this unstructured memo into a structured contact record, remembers what was actually said, detects the follow-ups that were promised, and helps ensure those promises are kept.

## The Problem

Salespeople break promises they fully intended to keep, because:

- Follow-ups happen too late.
- Contact details and conversation context are not properly recorded.
- Important promises are forgotten.
- Existing contacts are accidentally duplicated.
- CRM systems are too time-consuming to update immediately after an event.
- Salespeople do not know which follow-up actions are most urgent.

The problem is not simply remembering who someone is. It is maintaining the relationship and acting at the right time.

## The Solution

Recall is a voice-first relationship memory for sales professionals.

Immediately after meeting someone, the salesperson records a short voice memo. Recall then:

1. Transcribes the voice recording.
2. Extracts the person, company, role, needs, interests, and commitments.
3. Determines whether the person is a new lead or an existing contact.
4. Asks a clarification question if the identity or information is uncertain.
5. Stores the information in a persistent relationship history.
6. Detects promised follow-up actions.
7. Creates a calendar reminder after user confirmation.
8. Drafts a personalised follow-up message.

## Example Workflow

A salesperson records:

> “I met Alex from Deloitte at the technology conference. He was interested in our data platform and asked me to send a demo link on Friday. I think I may have met him before, but I’m not sure.”

Recall may respond:

> “Is this the same Alex from Deloitte you met at the NUS networking event?”

After the user confirms, Recall updates the existing contact instead of creating a duplicate. It then identifies the commitment:

> “You promised to send Alex a demo link on Friday. Add a reminder to your calendar?”

Once confirmed, the calendar reminder is created and Recall prepares a follow-up draft using the conversation context.

## What Makes Recall Different

Recall is more than a voice-to-CRM tool.

Its key innovation is uncertainty-aware relationship memory. Instead of confidently making a potentially incorrect decision, Recall knows when it is unsure and asks the most useful clarification question.

For example, if two contacts have similar names, Recall does not automatically merge them. It evaluates the possible candidates and selects the question that would provide the most information.

This helps prevent:

- Incorrect contact merges.
- Duplicate customer records.
- Forgotten promises.
- Irrelevant or hallucinated customer information.

The system follows the principle:

> The model proposes; code verifies.

The AI extracts and interprets information, while deterministic logic handles identity matching, ambiguity detection, commitment extraction, and calendar confirmation.

## Freemium Business Model

Recall can begin as a personal relationship assistant and gradually become a professional sales productivity platform.

### Free Plan

The free plan helps users build the habit of recording conversations:

- Up to 50 contacts.
- Limited voice memos per month.
- Basic contact extraction.
- Basic duplicate detection.
- Limited clarification questions.
- Basic follow-up drafts.
- Calendar reminders with confirmation.
- Personal relationship timeline.

### Professional Plan

Once users have built a valuable relationship memory, they can upgrade for professional usage:

- Higher or unlimited contact capacity.
- More voice recordings.
- Full relationship history and search.
- Automatic commitment detection.
- Advanced follow-up tracking.
- Calendar integration.
- Web-based contact enrichment.
- Data export and backup.
- Priority processing.

The upgrade trigger is based on accumulated value rather than an arbitrary paywall:

> “Recall has remembered 47 people for you. Upgrade to continue building your professional relationship memory.”

Users should still be able to view and export their existing data even if they reach the free-plan limit.

### Team Plan

For sales teams, Recall can expand into a shared workspace with:

- Shared customer records.
- Lead ownership.
- Team follow-up visibility.
- Sales activity tracking.
- CRM integrations such as HubSpot or Salesforce.
- Administrative controls.
- Team-level analytics.

## Hackathon MVP

The MVP should focus on one complete and convincing scenario:

1. A salesperson records a post-event voice memo.
2. Recall extracts the person, what they need, and what was promised to them.
3. Recall identifies an existing contact or asks a clarification question.
4. Recall detects a specific promise.
5. The user confirms a calendar reminder.
6. Recall generates a personalised follow-up draft.
7. The relationship timeline is updated.

This demonstrates a clear outcome, and it is deliberately phrased as the outcome for
the person on the other side of the conversation:

> You keep the promises you made.

That is a sales result and a decent one at the same time, which is why it is the framing
used throughout. Recall is never positioned as a way to extract value from contacts
later; the pitch is that the follow-up you promised actually arrives.

## Long-Term Vision

Recall can become a lightweight relationship operating system for sales professionals.

It starts with remembering people, then helps users understand their relationships, prioritise follow-ups, and consistently act on their commitments.

The long-term vision is:

> Every meaningful business conversation becomes remembered, understood, and followed up at the right time.
