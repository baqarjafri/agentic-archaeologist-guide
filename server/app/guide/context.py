"""Turn requests from the phone, turn planning, and bounded context for the language model."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from app.guide.prompts import OUTPUT_RULES, master_prompt, turn_instruction
from app.packs import Pack, PackObject, Relation

MAX_LINKED = 2
MAX_UNSEEN = 2
MAX_RECENT = 3
MAX_SUMMARY_WORDS = 300
MAX_SUMMARY_CHARS = 2400
MAX_ANSWER_CHARS = 300
MAX_QUESTION_CHARS = 300  # spoken questions are short; this bounds the prompt whatever the phone sends
DOT = " · "
DEPTH = {"short": "keep it brief", "medium": "a little more detail", "long": "take time and go deeper"}
KEY_FACTS = (("what", "What it is"), ("when", "How old"), ("wow", "Most exciting"),
             ("significance", "Why it matters"), ("acquired", "How it got here"))

def _cut(limit: int) -> BeforeValidator:
    """Cut phone text to `limit` characters rather than refuse it, so one long question never blocks later turns."""
    return BeforeValidator(lambda value: value[:limit] if isinstance(value, str) else value)


Text = Annotated[str, _cut(4000)]


class Visit(BaseModel):
    object_id: str = Field(max_length=32)
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # "10:38", local time on the phone
    heard_parts: list[Annotated[int, Field(ge=0, le=99)]] = Field(default_factory=list, max_length=100)
    questions: list[Text] = Field(default_factory=list, max_length=200)


class Exchange(BaseModel):
    question: Text
    answer: Text


class Profile(BaseModel):
    motivation: str = Field("curious", pattern=r"^[a-z][a-z -]{0,39}$")  # plain words only: it is not quoted in the prompt
    depth: Literal["short", "medium", "long"] = "short"


class TurnRequest(BaseModel):
    type: Literal["turn"] = "turn"
    kind: Literal["tell", "ask", "carry_on"]
    object_id: str = Field(max_length=32)
    question: Annotated[str | None, _cut(2000)] = None
    part_index: int | None = None
    visits: list[Visit] = Field(default_factory=list, max_length=200)
    recent: list[Exchange] = Field(default_factory=list, max_length=50)
    connections_made: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=200)
    profile: Profile = Field(default_factory=Profile)

    @model_validator(mode="after")
    def _an_ask_has_a_question(self) -> TurnRequest:
        if self.kind == "ask" and not (self.question or "").strip():
            raise ValueError("an ask needs a question")
        return self


@dataclass(frozen=True)
class LinkedPiece:
    relation: Relation
    other: PackObject
    visit: Visit


@dataclass(frozen=True)
class UnseenLink:
    relation: Relation
    other: PackObject


@dataclass(frozen=True)
class TurnPlan:
    kind: Literal["tell", "ask", "carry_on"]
    obj: PackObject
    part_index: int | None
    part_count: int
    next_part: int | None
    heard: frozenset[int]
    linked: tuple[LinkedPiece, ...]
    connection: LinkedPiece | None
    unseen: tuple[UnseenLink, ...]

    @property
    def part_title(self) -> str | None:
        return self.obj.story[self.part_index].title if self.part_index is not None else None

    @property
    def finished(self) -> bool:
        """A tell or carry-on with no part left to tell."""
        return self.kind != "ask" and self.part_index is None


def _clean(text: str) -> str:
    """Phone text goes inside quotes in the prompt: keep it on one line, so it cannot open a section or close its quotes."""
    return " ".join(text.split()).replace('"', "'")


def _heard(req: TurnRequest, part_count: int) -> frozenset[int]:
    current = next((v for v in reversed(req.visits) if v.object_id == req.object_id), None)
    return frozenset(p for p in current.heard_parts if p < part_count) if current else frozenset()


def plan_turn(req: TurnRequest, pack: Pack) -> TurnPlan:
    obj = pack.objects.get(req.object_id)
    if obj is None:
        raise ValueError(f"unknown object {req.object_id}")
    heard = _heard(req, len(obj.story))
    next_part = next((i for i in range(len(obj.story)) if i not in heard), None)
    part_index: int | None = None
    if req.kind in ("tell", "carry_on"):
        valid = req.part_index is not None and 0 <= req.part_index < len(obj.story)
        part_index = req.part_index if valid else next_part
    order = {v.object_id: i for i, v in enumerate(req.visits)}  # the phone appends visits in the order they happen
    visits = {v.object_id: v for v in req.visits}
    linked = sorted(
        (LinkedPiece(rel, pack.objects[rel.other(obj.id)], visits[rel.other(obj.id)])
         for rel in pack.relations_of(obj.id) if rel.other(obj.id) in visits),
        key=lambda lp: order[lp.other.id], reverse=True,
    )[:MAX_LINKED]
    connection = None
    if req.kind == "tell" and not heard and part_index == 0:
        connection = next((lp for lp in linked if lp.relation.key not in req.connections_made), None)
    unseen = tuple(UnseenLink(rel, pack.objects[rel.other(obj.id)])
                   for rel in pack.relations_of(obj.id) if rel.other(obj.id) not in visits)[:MAX_UNSEEN]
    return TurnPlan(kind=req.kind, obj=obj, part_index=part_index, part_count=len(obj.story), next_part=next_part,
                    heard=heard, linked=tuple(linked), connection=connection, unseen=unseen)


def _link_passages(relation: Relation, other: PackObject) -> list[str]:
    """What the model sees of a linked piece: the link's passages, then up to three more from the other piece's first part."""
    first_part = other.story[0].passage_ids if other.story else ()
    return list(relation.passage_ids) + [pid for pid in first_part if pid not in relation.passage_ids][:3]


def context_ids(pack: Pack, plan: TurnPlan) -> set[str]:
    """Every passage ID the model is shown this turn; a citation outside this set is treated as unknown."""
    ids = {p.id for p in plan.obj.passages}
    for lp in plan.linked:
        ids.update(_link_passages(lp.relation, lp.other))
    if plan.finished:
        for u in plan.unseen:
            ids.update(u.relation.passage_ids)
    return {pid for pid in ids if pid in pack.passages}


def _passage_lines(pack: Pack, ids: list[str] | tuple[str, ...]) -> list[str]:
    # The ID follows the text, just as the output rules ask the model to write it.
    return [f"{pack.passages[pid].text} [{pid}]" for pid in ids if pid in pack.passages]


def _object_block(pack: Pack, obj: PackObject, heard: frozenset[int]) -> str:
    lines = [f"{obj.title} ({obj.id}). {DOT.join(obj.meta)}"]
    if obj.highlights:
        lines.append("Key facts (lead with these):")
        for heading, label in KEY_FACTS:
            facts = _passage_lines(pack, obj.highlights.get(heading, ()))
            if facts:
                lines.append(f"{label}: " + " ".join(facts))
    lines.append("Passages:")
    lines += _passage_lines(pack, [p.id for p in obj.passages])
    lines.append("Story parts:")
    for i, part in enumerate(obj.story):
        state = " (already heard)" if i in heard else ""
        lines.append(f"{i + 1}. {part.title}{state}: " + ", ".join(part.passage_ids))
    return "\n".join(lines)


def _linked_block(pack: Pack, lp: LinkedPiece, made: bool) -> str:
    heard = len({p for p in lp.visit.heard_parts if p < len(lp.other.story)})
    note = " (link already made)" if made else ""
    lines = [f"{lp.other.title} ({lp.other.id}), seen at {lp.visit.time}, heard {heard} of {len(lp.other.story)} parts{note}. "
             f"Link: {lp.relation.theme}.", "Link passages (both pieces):"]
    lines += _passage_lines(pack, lp.relation.passage_ids)
    extra = [pid for pid in _link_passages(lp.relation, lp.other) if pid not in lp.relation.passage_ids]
    if extra:
        lines.append(f"From the start of the {lp.other.title}'s story:")
        lines += _passage_lines(pack, extra)
    return "\n".join(lines)


def _unseen_block(pack: Pack, u: UnseenLink) -> str:
    lines = [f"{u.other.title} ({u.other.id}), not yet seen. Link: {u.relation.theme}.", "Link passages (both pieces):"]
    lines += _passage_lines(pack, u.relation.passage_ids)
    return "\n".join(lines)


def _visit_summary(pack: Pack, req: TurnRequest) -> str:
    lines = []
    for v in req.visits:
        obj = pack.objects.get(v.object_id)
        if obj is None:
            continue
        questions = list(v.questions)
        if req.kind == "ask" and v.object_id == req.object_id and questions and questions[-1] == req.question:
            questions = questions[:-1]  # the question being asked now is not part of the past
        heard = len({p for p in v.heard_parts if p < len(obj.story)})
        bits = [f"heard {heard} of {len(obj.story)} parts"]
        if questions:
            bits.append("asked " + "; ".join(f'"{_clean(q)[:MAX_QUESTION_CHARS]}"' for q in questions[-2:]))
        marker = " (current)" if v.object_id == req.object_id else ""
        lines.append(f"{v.time} {obj.title}{marker}: " + ", ".join(bits))
    if not lines:
        return "This is the first piece of the visit."
    kept, words, chars = [], 0, 0
    for line in reversed(lines):  # keep the most recent lines within the budget
        words += len(line.split())
        chars += len(line)
        if words > MAX_SUMMARY_WORDS or chars > MAX_SUMMARY_CHARS:
            break
        kept.append(line)
    return "\n".join(reversed(kept)) or "(The earlier visit is too long to list.)"


def build_messages(req: TurnRequest, pack: Pack, plan: TurnPlan) -> list[dict]:
    sections = ["CURRENT PIECE", _object_block(pack, plan.obj, plan.heard)]
    if plan.linked:
        sections.append("PIECES SEEN EARLIER THAT THE MUSEUM LINKS TO THIS ONE")
        sections += [_linked_block(pack, lp, lp.relation.key in req.connections_made) for lp in plan.linked]
    if plan.finished and plan.unseen:
        sections.append("PIECES NOT YET SEEN THAT THE MUSEUM LINKS TO THIS ONE")
        sections += [_unseen_block(pack, u) for u in plan.unseen]
    sections += ["THE VISIT SO FAR", _visit_summary(pack, req)]
    recent = req.recent[-MAX_RECENT:]
    if recent:
        sections.append("RECENT EXCHANGES ABOUT THIS PIECE (your earlier answers, shown without their citations; "
                        "cite every fact you state now)")
        sections += [f'Visitor: "{_clean(x.question)[:MAX_QUESTION_CHARS]}"\nGuide: "{_clean(x.answer)[:MAX_ANSWER_CHARS]}"'
                     for x in recent]
    sections += ["VISITOR", f"Motivation: {_clean(req.profile.motivation)}. "
                            f"Preferred depth: {req.profile.depth} ({DEPTH[req.profile.depth]})."]
    question = _clean(req.question)[:MAX_QUESTION_CHARS] if req.question else None
    sections += ["TASK", turn_instruction(plan, question)]
    return [
        {"role": "system", "content": master_prompt(pack.venue) + "\n\n" + OUTPUT_RULES},
        {"role": "user", "content": "\n\n".join(sections)},
    ]
