# Resume Prompts

Quick prompts to get the AI assistant working again after it stops.

---

## Quick Resume (Default)

```
Continue working autonomously on the Visual Mapper project.

Read `docs/SESSION_SUMMARY.md` to see current progress and what's next.

You have full authority to fix, improve, and refactor. Don't stop to ask -
keep working through the priority queue until blocked or done.

Pick up where the last session left off and continue.
```

---

## Full Context Resume

Use this if the AI seems to have lost context or is a fresh session:

```
Resume autonomous work on Visual Mapper.

**Context:**
- Read `docs/SESSION_SUMMARY.md` for current progress
- Read `docs/AI_TEAM_PROMPT.md` for the full methodology
- Read `docs/TEAM_REVIEW_REPORT.md` if you need project overview
- Check `docs/plans/` for any in-progress plan files

**Your mission:**
Continue working through the priority queue. The SESSION_SUMMARY shows
what's done and what's next.

**Rules:**
- Work autonomously - don't ask for permission
- Fix issues, commit changes, move to next item
- Update SESSION_SUMMARY.md as you progress
- Create plan files in docs/plans/ for complex tasks
- Only stop if truly blocked or queue is empty

**Start now.** Check the session summary and continue from where it left off.
```

---

## Phase Complete

Use when a priority level is finished:

```
Priority [X] is complete. Continue to Priority [X+1].

Check `docs/SESSION_SUMMARY.md` for the current state and continue
working autonomously through the queue.

Update the session summary as you complete items. Keep going.
```

---

## Specific Task Resume

Use to focus on a specific issue:

```
Continue working on: [specific task]

Check `docs/SESSION_SUMMARY.md` for context, then focus on completing
this specific task. Once done, continue with the next item in the queue.

Work autonomously. Don't stop to ask - just fix it and move on.
```

---

## Unstick Prompt

Use if the AI seems stuck or keeps asking questions:

```
Stop asking questions. You have authority to make decisions.

Read `docs/SESSION_SUMMARY.md` and continue working. Pick the most
reasonable approach and implement it. If something doesn't work,
try a different approach.

The goal is progress, not perfection. Fix things, commit, move on.

Start working now.
```

---

## End of Day Summary Request

Use to get a summary before ending:

```
Before stopping, please:

1. Update `docs/SESSION_SUMMARY.md` with:
   - What you accomplished
   - What's in progress
   - What's blocked
   - Next steps for the next session

2. Commit any uncommitted changes

3. Provide a brief verbal summary of the session

Then you can stop.
```

---

## Fresh Start (New Feature/Task)

Use to start work on something new:

```
New task: [describe the task]

1. Create a plan file: `docs/plans/PLAN-[task-name].md`
2. Analyze the problem thoroughly before coding
3. Implement the solution
4. Update `docs/SESSION_SUMMARY.md`
5. Continue to next priority item

Work autonomously. Document your progress.
```

---

## Tips

- **AI keeps stopping?** Use the "Unstick Prompt"
- **Lost context?** Use "Full Context Resume"
- **Finished a phase?** Use "Phase Complete"
- **End of your day?** Use "End of Day Summary Request"
- **Starting fresh?** Use "Fresh Start"

The key phrases that keep it going:
- "Work autonomously"
- "Don't stop to ask"
- "Keep going"
- "Continue"
- "You have authority"
