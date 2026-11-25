# Comment Radar

Finds groups of accounts that act together in one post's comment section, and reports them with evidence.

## Language

### What we read

**Thread**:
All the comments and replies under one post (for now, one YouTube video), with the commenters' public profiles.
_Avoid_: Comment section (in code), video

**Comment**:
One top-level comment or reply in a thread.

**Account**:
The profile behind a comment (on YouTube, a channel). Shown only as a masked id.
_Avoid_: User, commenter (in code), author

**Masked id**:
A stable stand-in for an account (`acct_1a2b3c`), so groups can be described without naming anyone.

**New account**:
An account under 180 days old when it commented. Its comments are all stance-labelled.
_Avoid_: Fake account, bot (we can't know that)

**Established account**:
Any other account. A random sample of their comments is stance-labelled, as the baseline.

**Side**:
One position commenters take on what the video says (e.g. "The reinstatement is market manipulation"). Each video gets 2 to 4, from the Watcher.

**Stance**:
The side one comment takes, or off topic, promotion, or no side.

### What we find

**Pushed side**:
A side new accounts take far more often than established accounts (a statistical test), which can mean opinion steering.

**Steering group**:
The new accounts pushing a pushed side, outside other groups. A candidate group like any other.


**Candidate group**:
Accounts in one thread linked by direct evidence that they act together. A candidate, not a conclusion.
_Avoid_: Bot network, troll farm, fake accounts

**Link**:
Direct evidence between two accounts: their comments are near-copies, or young accounts crowd one stretch of a reply thread more than chance allows.

**Signal**:
A measured property of a candidate group (text similarity, burst, young accounts, creation cluster, same thread, sentiment uniformity), each a share from 0 to 1.

**Signal score**:
The 0-to-1 score the statistics give a candidate group, before any agent reviews it.

**Baseline**:
The same rates measured over the whole thread, so a group's signals can be judged against what is normal there.

**Organic comments**:
Comments not written by any candidate group.
_Avoid_: Real comments, genuine comments

### What we conclude

**Finding**:
The Investigator's case that a candidate group acts together, with evidence and a confidence.

**Defense**:
The strongest innocent explanation for a candidate group, and a verdict on it: keep, downgrade or dismiss.

**Confidence**:
How sure we are, after the Defense, that a group acts together.
_Avoid_: Probability (it is a judgement, not a calibrated probability)

**Verdict**:
The thread-level answer: coordinated activity found, possible coordination, or no clear coordination.
