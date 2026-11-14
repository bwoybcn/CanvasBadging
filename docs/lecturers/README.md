# Creating and awarding micro-credentials (lecturer guide)

This guide is for lecturers, teaching assistants and course designers. You need no technical
knowledge. Everything happens inside your Canvas course.

## Before you start

1. In your Canvas course, open **Micro-Credentials** in the course menu. If you cannot see it,
   turn it on under **Settings → Navigation**, or ask your Canvas administrator.
2. The first time, you may see **Switch on micro-credentials for this course**. Choose it.
   OpenCredential then reads your students' progress from Canvas straight away, and again every
   30 minutes. You can switch it off later. Credentials already issued are not affected.
3. Your department needs an **issuer** (the body whose name appears on the badge, for example
   "Academic Skills Centre") that has been delegated to your course. If the wizard says there is
   none, ask your department administrator.

OpenCredential only reads Canvas. It never changes marks, submissions or modules.

## Create a badge

Choose **Badges → Create micro-credential**. The wizard has seven steps. You cannot move on
from a step until its problems are fixed, and each problem is explained.

Your work is saved as a draft as you go: from step 2 onwards, each time you choose **Next** or
**Back**, and when you leave the wizard. A line under the buttons says when it was last saved.
If you are interrupted, or your session ends, open **Badges**, choose the draft and then
**Edit draft** to carry on. Once the draft is saved its course and issuer are fixed; to change
them, delete the draft and start again.

Text boxes stop at the length a badge can hold and show a count as you get close. If the
server still refuses something, the message names the field and says what to change.

| Step | What you enter | Tips |
|---|---|---|
| 1. Course and issuer | The course and the issuer | Only issuers delegated to your course appear |
| 2. About the badge | Title, short description, full description, category, and what the badge shows: completing, participating or assessed proficiency | A "completion" badge cannot claim competency. Words such as "credit" or "credits" need a reviewer's explicit approval. |
| 3. Outcomes and criteria | Learning outcomes and the criteria in plain language | Learners and employers read the criteria on the public page |
| 4. Artwork | Upload a PNG or SVG, or build one from a template by choosing its two colours from a colour swatch, and write its alt text | Unsafe SVG content is removed. Alt text is required. If you were given a brand colour as a code such as #212b58, paste it in the box beside the swatch. |
| 5. Requirements | What a student must do: complete a module, complete several modules, submit an assignment, reach a minimum score, or have a lecturer confirm. Combine them with **all** or **any**. | Modules and assignments are picked from your Canvas course. A score counts only once the mark is **released** in Canvas. |
| 6. Awarding | Automatic, or a lecturer confirms each award | Your institution may require confirmation for badges that use marks |
| 7. Check and save | A summary of everything | **Save draft** keeps your last changes and opens the badge page |

### Preview

On the badge page, **Preview** shows the badge as a credential would look. It is clearly marked
**PREVIEW: NOT ISSUED AND NOT VERIFIABLE**, and nobody else can see it.

### Review and publish

1. **Submit for review.** Your department or institution reviewers get it in their **Review
   queue**. You cannot approve your own badge unless your area allows it. Some areas do not
   require review, or let you choose: the badge page says which applies. If you can choose, pick
   **Ask a colleague to review it first** or **Publish without review**; the second goes straight
   to **Approved** and administrators can see that nobody else checked it. Badges that claim
   assessed proficiency, or whose wording refers to credit or a qualification, always need review.
2. The reviewer works through a checklist (clarity, level, evidence, alignment, accessibility,
   consistency, terminology) and **approves** it, or **rejects** it with comments. A rejected
   badge goes back to draft.
3. Once it is approved, **Publish** it. From then on, students see it in **My badges** with its
   requirements, and their progress is checked.

A published badge cannot be edited, because credentials must always match what was published.
To change it, create a **new version**. Credentials already issued keep the version they were
issued under.

### Archive and restore

**Archive** stops a published badge being awarded and takes it out of students' lists of
badges to earn. Credentials already issued stay valid. Because that affects students, the
button asks first and says what will happen. To bring the badge back, open it from **Badges**
and choose **Restore this badge**: it goes live again exactly as it was published, with no new
review. **Delete draft** also asks first, because a deleted draft cannot be brought back.

## Follow your students' progress

**Course progress** shows every student against every published badge:

| You see | It means |
|---|---|
| Requirements met | Everything is done. An automatic badge is issued; otherwise it waits for you. |
| Not yet met | Something is still to do |
| Pending: mark not released | The student has a mark, but it is not released in Canvas yet. Nothing is awarded on unreleased marks. |
| Pending: Canvas data unavailable | Canvas could not be read. Nothing is awarded on missing data. |
| Pending: needs your confirmation | The badge needs you to confirm a requirement |
| Awaiting your confirmation | The requirements are met and the badge is lecturer-confirmed |
| Issued | The student has the credential |

The page shows when Canvas was last read successfully. **Refresh from Canvas** asks for a new
read. To spare Canvas, you can do this once every five minutes; if you try sooner, the page
tells you that the figures are from the earlier read. A warning appears if a badge refers to a
Canvas module or assignment that was removed or changed. Those requirements stay pending until
you update the badge.

## Confirm awards and make manual awards

**Awards to confirm** lists students whose requirements are met for lecturer-confirmed badges.
Confirm or decline each one.

To award a badge that is not earned through Canvas activity, use **Manual award**: choose the
student and write a **justification**. The justification is recorded and audited. Your
institution may require a second member of staff to confirm manual awards.

To award one badge to many people at once, for example everyone on a volunteering log or a
workshop register, use **Award a badge to a list**: choose the badge, paste student ID numbers or
university emails, write one justification, and select **Check the list**. You see who will get
it, who already has it and which entries match no student in the course (a typo, or someone who
has not enrolled yet). If students joined the course in Canvas today, select **Refresh the course
from Canvas**, wait a minute and check the list again. Then select **Award to N learners** (or
**Record for N learners** where a second member of staff must confirm each award).

## If something goes wrong

* **A credential was issued in error.** In **Course progress**, choose **Request revocation for <name>** on the issued cell, with a
  reason. An administrator approves the request. Revocation never deletes the credential, but
  every verifier will then show it as revoked, including for copies the student has downloaded.
* **Canvas was down.** Nothing is awarded on missing data. Once Canvas is back, the next refresh
  catches up.
* **An award has not turned into a credential.** Administrators see it under Failed issuance and
  can retry it safely; it can never be issued twice.

## What students see

Students see the badges in your course, what each requires, and their own progress. When they
earn a credential, they can download it, share a public link (off until they turn it on), and
add it to LinkedIn. See the [student guide](../students/README.md).

## Shared courses: badge teams

In a course that many staff share, such as a library or CPD course, switch on **Badge teams**
from the course home page in OpenCredential. Each badge is then edited and awarded only by its
owner and the colleagues they add on the badge's **Team** tab, either "edit and award" or
"award only". Other staff can still see the badge. Ask an administrator if badge teams need
switching off again. To pass a badge on, for example when you leave, use **Hand this badge to a
colleague** on its **Team** tab.
