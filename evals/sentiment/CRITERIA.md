# Sentiment labelling criteria

Label the **emotion the author shows**, not the opinion they hold. Sentiment answers "how emotionally is this written?"; the stance step already answers "which side is it on?". A calm opinion or accusation is neutral ("Failed military operation", "I still hope we will support Ukraine"); an angry one is negative.

| Label | Use when | Examples |
|---|---|---|
| positive | joy, praise, support, hope, celebration, thanks | "Welcome back Jensen!!!", "🎉🎉🎉", "Come on Ukrainians, you can win it" |
| negative | anger, insult, contempt, fear, grief, accusation, complaint | "This is fking fraud", "Dumb MAGA cult 😂" |
| neutral | facts, questions, news, links, calm opinions and accusations: no clear feeling | "More than the U.S. Civil War.", "Does this include North Korean soldiers?" |

Rules for hard cases:

1. **Sarcasm and mockery are negative** even when the words are calm: mockery is an emotion. Sarcasm counts by what it means, not by its words. "Which war? Is there a war? 😂" mocks, so it is negative.
2. **Mocking, taunting or insulting someone is negative**, even with 😂 or a happy word ("Lmao cry more 😂").
3. **Pure celebration is positive**, even if it is about the other side losing ("IT'S OVER MAGA 🤣🇺🇸"), as long as it has no insult.
4. **Laughing emoji alone (😂😂😂) is neutral**: we can't tell what it is laughing at. Hearts and 🎉 alone are positive (see rule 9).
5. **Promotion and scam praise is labelled by its literal tone** ("Marie Freeman explains investing so clearly" is positive). The scam is caught by the group signals, not by sentiment.
6. **Any language** gets the same rules. Translate first.
7. **Demands to remove, punish or stop someone are negative** ("Nvidia board needs to step down now", "Needs investigation"): a call for punishment carries anger.
8. **A hinted accusation is negative** ("THAT is Trump's Best Friend. Let us think about that....", "Epstein Files!!!"): trailing "....", "!!!" or "think about it" carry suspicion or anger.
9. **Emoji alone is neutral unless it is hearts or 🎉** (🌊🌊🌊 and 🚫🚫🚫 are neutral).
10. **Mixed tone**: pick the one the comment ends on or spends most words on.
