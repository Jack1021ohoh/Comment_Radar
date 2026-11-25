"""What each agent must return. The page and the run record read these fields, so changing one means
changing static/app.js too."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Pattern = Literal["opinion_steering", "promotion_reply_chain", "copy_paste_campaign", "coordinated_burst",
                  "new_account_cluster", "unclear"]
Purpose = Literal["steer_opinion", "promote_or_scam", "harass", "boost_engagement", "unclear"]


class Finding(BaseModel):
    """An Investigator's case that one candidate group acts together."""

    group_id: str
    pattern: Pattern = Field(description="The behaviour that best fits the evidence")
    headline: str = Field(description="One sentence on what the group did, about the group as a whole")
    evidence: list[str] = Field(description="2 to 5 facts from the tools, each with its number")
    purpose: Purpose = Field(description="steer_opinion: push a side of the video's subject or derail it; promote_or_scam: "
                                         "sell or lure people somewhere; harass: attack a person or group; boost_engagement: "
                                         "lift comments or the video itself; unclear")
    likely_purpose: str = Field(description="What the group seems to want, in a few words, e.g. 'make the deal look corrupt'")
    confidence: float = Field(description="0 to 1: how sure you are these accounts act together")


class Defense(BaseModel):
    """The Defense's best innocent reading of the same group, and whether it holds up."""

    group_id: str
    innocent_explanation: str = Field(description="The strongest innocent reading of the evidence")
    holds_up: bool = Field(description="True if the innocent reading explains the evidence as well as coordination does")
    verdict: Literal["keep", "downgrade", "dismiss"]
    confidence: float = Field(description="0 to 1: the group's confidence after your review")
    reason: str = Field(description="One or two sentences on why, citing numbers")


class Side(BaseModel):
    id: str = Field(description='"S1", "S2", ... in order')
    label: str = Field(description="The position in at most 8 words, as a commenter would hold it")
    description: str = Field(description="One sentence: what a comment on this side says")


class VideoBrief(BaseModel):
    """What the video shows and says, and the sides its viewers take."""

    summary: str = Field(description="2 or 3 sentences: what the video shows and says")
    claims: list[str] = Field(description="The video's 2 to 5 main claims or pieces of news")
    sides: list[Side] = Field(description="2 to 4 positions commenters take on the video's subject, together "
                                          "covering most opinions in the sample; not 'neutral' or 'off topic'")


class StanceLabel(BaseModel):
    n: int = Field(description="The comment's number in the list")
    stance: str = Field(description="A side id (S1, S2, ...), or off_topic, promotion or neutral")


class StanceLabels(BaseModel):
    labels: list[StanceLabel]


class Summary(BaseModel):
    headline: str = Field(description="One sentence answer: is there coordinated activity in this comment section?")
    summary: str = Field(description="Two or three sentences for a journalist, about groups, never individuals")
