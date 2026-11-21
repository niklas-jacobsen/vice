"""Golden dataset: a synthetic knowledge worker's notes, and ambient events over them.

Design choices that make the set hard rather than flattering:
  * Event wording never reuses a note's wording for the fact, and never contains the answer.
  * Every entity has several notes about *other* attributes, plus chatter that names the
    entity and states nothing. These are the hard negatives the relevance judge must reject.
  * About 40% of facts were revised over time. All versions are `relevant_ids`; only the
    newest is in `required_ids`. Conflict resolution is graded on that difference.
  * 40% of events warrant no retrieval, half of them while naming a known entity.

Everything is seeded and reproducible:  python -m vice_ai.eval.dataset
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import ROOT
from ..types import AmbientEvent, Block

DATA_DIR = ROOT / "data" / "golden"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
SEED = 20261113

PROJECTS = ["Atlas", "Borealis", "Cobalt", "Driftwood", "Ember", "Fathom", "Granite", "Halcyon",
            "Juniper", "Kestrel", "Lumen", "Meridian"]
PEOPLE = ["Priya Raman", "Tomas Lindqvist", "Aiko Tanaka", "Dele Okafor", "Marta Kowalczyk", "Jonah Reyes",
          "Sana Mirza", "Callum Fraser", "Ines Duarte", "Wei Zhang", "Rosa Benedetti", "Emeka Nwosu",
          "Hanna Virtanen", "Luis Ortega", "Noor Haddad", "Oskar Brandt", "Yuki Morita", "Farah Siddiqui",
          "Gideon Adler", "Leilani Kahale"]
VENDORS = ["Northwind Hosting", "Brightline Analytics", "Pagewell", "Corvid Security", "Tessera Payments",
           "Lanternmail", "Quillbase", "Stackharbor", "Opaline Design", "Ferrous CI"]

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def _date(r: random.Random, lo=20, hi=240) -> str:
    d = NOW + timedelta(days=r.randint(lo, hi))
    return f"{MONTHS[d.month - 1]} {d.day}"


def _person(r): return r.choice(PEOPLE)
def _money(r, lo, hi, step): return f"${r.randrange(lo, hi, step):,}"


# attribute -> (value generator, note templates, query phrasings)
# {e} is the entity, {v} the value, {p} a bystander's first name. Queries never contain {v}.
PROJECT_ATTRS = {
    "launch_date": (lambda r: _date(r), [
        "{e} launch is now set for {v}.",
        "Planning call: we agreed {e} goes live on {v}.",
        "{p} confirmed with marketing that {e} will be released {v}.",
    ], ["when does {e} ship?", "Need the go-live day for {e} for the board deck.",
        "what date did we commit to for the {e} release", "remind me when {e} is supposed to be out the door"]),
    "owner": (_person, [
        "{v} is the lead on {e} from here on.",
        "Reorg note: {e} now reports up through {v}.",
        "{e} decisions go through {v}.",
    ], ["who's running {e}?", "who do I ask to sign off on {e} changes", "Who has the final say on {e} these days?"]),
    "database": (lambda r: r.choice(["PostgreSQL 16", "MySQL 8", "DynamoDB", "CockroachDB", "MongoDB 7", "SQLite"]), [
        "{e} stores its data in {v}.",
        "Architecture review: {e} persistence layer is {v}.",
        "{p} finished moving {e} onto {v}.",
    ], ["what db is {e} on", "which datastore backs {e}?", "writing a migration for {e}, what engine am I targeting"]),
    "region": (lambda r: r.choice(["us-east-1", "eu-west-1", "ap-southeast-2", "us-west-2", "eu-central-1", "ca-central-1"]), [
        "{e} is deployed to {v}.",
        "Infra note: production for {e} runs out of {v}.",
        "{e} workloads were placed in {v} for latency reasons.",
    ], ["where is {e} hosted", "which AWS region does {e} run in?", "need to open a firewall rule for {e}, where does prod live"]),
    "budget": (lambda r: _money(r, 40_000, 400_000, 5_000), [
        "Finance approved {v} for {e} this fiscal year.",
        "{e} has {v} to spend, per the allocation memo.",
        "{p} got the {e} allocation signed: {v}.",
    ], ["how much money does {e} have", "what's the approved spend for {e}?", "can {e} afford another contractor, what were we allocated"]),
    "standup": (lambda r: f"{r.choice(['9:15', '9:30', '10:00', '10:30', '14:00'])} on {r.choice(['Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays'])} and {r.choice(['Fridays', 'Thursdays'])}", [
        "{e} standup happens at {v}.",
        "The {e} team meets {v}.",
        "{p} moved the {e} check-in to {v}.",
    ], ["when's the {e} sync", "what time does the {e} team meet?", "trying to book over the {e} standup, when is it"]),
    "oncall": (_person, [
        "{v} is carrying the pager for {e} this quarter.",
        "Rotation update: {v} takes incidents for {e}.",
        "If {e} breaks out of hours, {v} gets the alert.",
    ], ["who's on call for {e}", "{e} is throwing 500s, who do I page?", "who handles {e} incidents right now"]),
    "freeze": (lambda r: _date(r, 5, 120), [
        "Code freeze for {e} starts {v}.",
        "No merges to {e} main after {v}.",
        "{p} announced the {e} change freeze begins {v}.",
    ], ["when do we stop merging into {e}", "is there a freeze coming up on {e}?", "last day to land a PR on {e}?"]),
}

PERSON_ATTRS = {
    "role": (lambda r: r.choice(["staff engineer", "product manager", "design lead", "data scientist", "engineering manager",
                                 "security analyst", "solutions architect", "QA lead", "technical writer", "finance partner"]), [
        "{e} works as a {v}.",
        "Intro call: {e} joined us as {v}.",
        "{e} was promoted and is now a {v}.",
    ], ["what does {e} do here?", "what's {e}'s job title", "introducing {e} in an email, how should I describe their position"]),
    "timezone": (lambda r: r.choice(["Lisbon", "Singapore", "Toronto", "Nairobi", "Auckland", "Denver", "Berlin", "São Paulo", "Seoul"]), [
        "{e} is based in {v}.",
        "{e} relocated and now works from {v}.",
        "Heads-up: {e} keeps {v} hours.",
    ], ["where is {e} located?", "what timezone is {e} in", "is it too late to call {e} right now"]),
    "diet": (lambda r: r.choice(["vegetarian", "vegan", "gluten-free", "allergic to shellfish", "allergic to tree nuts", "pescatarian", "lactose intolerant"]), [
        "{e} is {v}.",
        "For team dinners: {e} mentioned being {v}.",
        "Catering form says {e} is {v}.",
    ], ["booking dinner with {e}, anything they can't eat?", "does {e} have food restrictions", "ordering lunch for {e}, what should I avoid"]),
    "contact": (lambda r: r.choice(["Slack DMs", "a phone call", "email only", "Signal", "calendar invites, no ad-hoc pings", "text message"]), [
        "{e} prefers to be reached by {v}.",
        "{e} asked that we use {v} for anything urgent.",
        "Best way to get {e}: {v}.",
    ], ["how do I get hold of {e} quickly", "what's the best channel for {e}?", "should I email or message {e}"]),
    "manager": (_person, [
        "{e} reports to {v}.",
        "{e}'s manager is {v} as of the reorg.",
        "{v} took over as {e}'s line manager.",
    ], ["who is {e}'s boss?", "who do I send {e}'s review feedback to", "who approves time off for {e}"]),
    "leave": (lambda r: f"{_date(r, 10, 150)} for {r.choice(['one week', 'two weeks', 'ten days', 'a month'])}", [
        "{e} is out from {v}.",
        "{e} booked leave starting {v}.",
        "Calendar: {e} away beginning {v}.",
    ], ["when is {e} on holiday?", "is {e} around next month or are they off", "need {e} for a review, when are they out"]),
}

VENDOR_ATTRS = {
    "plan": (lambda r: r.choice(["Starter", "Team", "Business", "Enterprise", "Scale"]), [
        "We are on the {v} plan with {e}.",
        "{e} account was moved to the {v} tier.",
        "{p} switched our {e} subscription to {v}.",
    ], ["what tier are we on with {e}?", "which {e} package do we pay for", "does our {e} subscription include SSO, what level do we have"]),
    "renewal": (lambda r: _date(r, 15, 330), [
        "{e} contract renews on {v}.",
        "Renewal date for {e}: {v}.",
        "{p} extended {e}; next renewal falls on {v}.",
    ], ["when is the {e} contract up?", "how long until we have to renegotiate {e}", "deadline to cancel {e} before it auto-renews?"]),
    "cost": (lambda r: _money(r, 200, 9_000, 50) + " per month", [
        "{e} costs us {v}.",
        "Invoice check: {e} bills {v}.",
        "After the price change {e} runs {v}.",
    ], ["how much are we paying {e}?", "what's the {e} bill these days", "what do we spend on {e}"]),
    "rep": (lambda r: r.choice(["Dana Whitfield", "Marcus Oyelaran", "Sofia Lindgren", "Theo Nakamura", "Bianca Russo", "Henrik Aalto", "Maya Goldberg"]), [
        "Our account manager at {e} is {v}.",
        "{e} assigned {v} as our rep.",
        "For {e} escalations, talk to {v}.",
    ], ["who's our contact at {e}?", "who do I escalate to at {e}", "need to email {e} about an outage credit, who is our rep"]),
    "seats": (lambda r: f"{r.randrange(5, 200, 5)} seats", [
        "We hold {v} on {e}.",
        "{e} licence count is {v}.",
        "{p} trimmed our {e} licence to {v}.",
    ], ["how many {e} licences do we have", "do we have spare seats on {e}?", "onboarding three people, what's our {e} seat limit"]),
}

# One-off personal facts: (subject label, value generator, note templates, queries)
PERSONAL = [
    ("dentist", lambda r: f"{_date(r, 3, 90)} at {r.choice(['8:40', '11:15', '15:30'])}", ["Dentist appointment booked for {v}.", "Rescheduled the dentist to {v}."],
     ["when is my dentist appointment", "do I have the dentist coming up?"]),
    ("landlord", lambda r: r.choice(["Mr. Abernathy", "Ms. Calloway", "the Verhoeven agency"]), ["Landlord is {v}; rent questions go there.", "The flat is now managed by {v}."],
     ["who do I contact about the broken boiler in the flat", "who is my landlord again"]),
    ("lease", lambda r: _date(r, 60, 330), ["Apartment lease runs until {v}.", "Signed the extension: lease now ends {v}."],
     ["when does my lease end?", "how long before I need to renew the flat"]),
    ("passport", lambda r: f"{r.choice(MONTHS)} {r.choice([2027, 2028, 2031])}", ["Passport expires {v}.", "New passport arrived, valid to {v}."],
     ["is my passport still valid for the trip", "when does my passport run out"]),
    ("gym_locker", lambda r: f"number {r.randint(10, 240)}", ["Gym locker is {v}.", "Got moved to gym locker {v}."],
     ["which locker is mine at the gym", "gym locker?"]),
    ("car_service", lambda r: _date(r, 5, 120), ["Car is booked in for its service on {v}.", "Garage moved the service to {v}."],
     ["when is the car going in to the garage", "car service date?"]),
    ("school_pickup", lambda r: r.choice(["15:10", "15:25", "16:00"]), ["School pickup is at {v} this term.", "Pickup time changed to {v} from next week."],
     ["what time do I collect the kids from school", "school run timing?"]),
    ("client_dinner", lambda r: r.choice(["Osteria Lume", "The Copper Finch", "Sakana House", "Maison Verre"]), ["For client dinners I use {v}.", "Switched my go-to client dinner spot to {v}."],
     ["where do I usually take clients to eat", "need a restaurant for the client dinner, what's my usual place"]),
    ("airline", lambda r: r.choice(["Icelandair", "KLM", "Air New Zealand", "TAP"]), ["Frequent flyer status is with {v}.", "Moved my miles over to {v}."],
     ["which airline do I have status with", "booking flights, who do I collect miles with"]),
    ("physio", lambda r: r.choice(["Dr. Okonkwo", "Dr. Hallberg", "Dr. Petrakis"]), ["Physiotherapist is {v}.", "Started seeing {v} for physio instead."],
     ["who is my physio", "need to rebook physiotherapy, who am I seeing"]),
    ("vet", lambda r: f"{_date(r, 5, 100)}", ["Vet check-up for Biscuit is on {v}.", "Vet moved Biscuit's check-up to {v}."],
     ["when is Biscuit's vet visit", "when does the dog see the vet"]),
    ("accountant", lambda r: r.choice(["Halloran & Pike", "Ines at Ledgerline", "Castellan Tax"]), ["Taxes are handled by {v}.", "Changed accountant to {v}."],
     ["who does my taxes", "who do I send the tax forms to"]),
    ("insurance", lambda r: _date(r, 20, 300), ["Home insurance renews {v}.", "Insurer pushed the home policy renewal to {v}."],
     ["when is the home insurance due", "house insurance renewal?"]),
    ("conference", lambda r: f"{r.choice(['Lisbon', 'Austin', 'Kyoto', 'Tallinn'])}, {_date(r, 30, 200)}", ["Speaking at the infra conference in {v}.", "Conference talk confirmed: {v}."],
     ["where and when is my conference talk", "when am I travelling for the conference"]),
    ("parking", lambda r: f"bay {r.choice('ABCDEF')}{r.randint(1, 60)}", ["Office parking spot is {v}.", "Facilities reassigned me to {v}."],
     ["where do I park at the office", "my parking bay?"]),
]

FILLER = {
    "project": [
        "Long thread about the {e} logo; nobody could agree and it was parked.",
        "{e} retro: the team felt the sprint was overloaded and morale dipped.",
        "{p} gave a nice demo of the new {e} onboarding flow.",
        "Customer call about {e} went well; they liked the dashboards.",
        "Brainstormed names for the {e} mascot over lunch.",
        "{e} docs are a mess, someone should tidy the README.",
        "{p} thinks {e} needs better error messages.",
        "Read through the {e} design doc again; the caching section is thin.",
        "The {e} offsite was fun, great food.",
        "Slides for the {e} all-hands are half done.",
    ],
    "person": [
        "Coffee with {e}; talked about hiking in the Dolomites.",
        "{e} recommended a book on distributed systems.",
        "{e} gave sharp feedback on my draft, very helpful.",
        "{e} ran the workshop today and it went smoothly.",
        "Ran into {e} at the climbing gym.",
        "{e} is training for a half marathon.",
        "{e} told a great story about their first job.",
        "{e} and I disagreed about tabs versus spaces again.",
    ],
    "vendor": [
        "{e} sent another marketing newsletter.",
        "Sat through a {e} webinar; mostly a sales pitch.",
        "{e} status page showed a brief blip this morning.",
        "{p} complained that the {e} dashboard is slow.",
        "{e} released a redesign of their settings screen.",
        "Swag box from {e} arrived: stickers and a mug.",
    ],
}

NOISE_PARTS = [
    ("Ran {n} km along the {place}; legs felt {adj}.", {"n": list(range(4, 22)), "place": ["canal", "river path", "coast road", "park loop", "old railway line"], "adj": ["heavy", "great", "stiff", "light", "tired"]}),
    ("Tried a recipe for {dish}; next time use less {ing}.", {"dish": ["miso aubergine", "lamb tagine", "sourdough focaccia", "dal makhani", "shakshuka", "mushroom risotto", "fish tacos"], "ing": ["salt", "chilli", "garlic", "oil", "lemon", "cumin"]}),
    ("Reading notes, {book}: {thought}.", {"book": ["a history of cartography", "a novel set in Trieste", "an essay collection on attention", "a biography of a lighthouse keeper", "a primer on type theory"], "thought": ["the middle chapters drag", "the argument about scale is the best part", "worth rereading the introduction", "the footnotes are better than the text", "not convinced by the conclusion"]}),
    ("Errand list: {a}, {b}, {c}.", {"a": ["post the parcel", "buy lightbulbs", "return library books", "pick up dry cleaning"], "b": ["get keys cut", "refill prescription", "buy birthday card", "drop off recycling"], "c": ["water the plants", "call the plumber", "fix the bike tyre", "descale the kettle"]}),
    ("Idea: {idea}. Probably {verdict}.", {"idea": ["a browser extension that hides comment sections", "a tiny app for tracking houseplant watering", "a newsletter about obscure maps", "a script that renames screenshots by content", "a board game about tidal rivers"], "verdict": ["not worth the time", "worth a weekend", "already exists", "too niche", "fun but pointless"]}),
    ("Weather was {w}; spent the {part} {doing}.", {"w": ["grim", "glorious", "foggy", "windy", "muggy"], "part": ["morning", "afternoon", "evening"], "doing": ["repotting herbs", "sorting old photos", "fixing the fence", "at the market", "napping", "painting the hallway"]}),
    ("Watched a {kind} about {topic}; {take}.", {"kind": ["documentary", "lecture", "short film"], "topic": ["deep-sea vents", "Roman concrete", "bird migration", "the history of zero", "glassblowing"], "take": ["surprisingly moving", "too long", "learned a lot", "beautifully shot", "fell asleep halfway"]}),
    ("{who} came round for {meal}; we {did} until {when}.", {"who": ["My sister", "The neighbours", "An old flatmate", "My cousins", "Friends from choir", "The book club"], "meal": ["brunch", "dinner", "tea", "a barbecue"], "did": ["played cards", "argued about films", "looked at holiday photos", "planned a camping trip", "watched the match"], "when": ["late", "the rain stopped", "the kids got tired", "midnight"]}),
    ("Fixed the {thing} with {tool}; took {dur} and {result}.", {"thing": ["leaking tap", "squeaky door", "wobbly shelf", "bike brakes", "garden gate", "desk lamp"], "tool": ["a borrowed wrench", "some epoxy", "a video tutorial", "duct tape", "new washers"], "dur": ["ten minutes", "an hour", "all afternoon"], "result": ["it held", "it is still not right", "I felt smug", "I should have called someone"]}),
    ("General note on {subj}: {tip}.",{"subj": ["code review", "writing design docs", "running meetings", "estimating work", "onboarding"], "tip": ["smaller is better", "say the conclusion first", "write the agenda down", "double the first guess", "pair on day one", "ask what would change your mind"]}),
]

NOISE_EVENTS = [
    "lol ok see you then", "sounds good, thanks!", "https://en.wikipedia.org/wiki/Knapsack_problem",
    "for (let i = 0; i < items.length; i++) { total += items[i].price; }", "def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)",
    "The quick brown fox jumps over the lazy dog.", "SELECT id, name FROM users WHERE active = true ORDER BY name;",
    "git rebase -i HEAD~3", "Traceback (most recent call last):\n  File \"app.py\", line 12, in <module>\nKeyError: 'user'",
    "Photosynthesis converts light energy into chemical energy stored in glucose.", "npm install --save-dev typescript",
    "It was the best of times, it was the worst of times.", "haha that's brilliant", "on my way, 5 min",
    "TODO: refactor this function", "background-color: rgba(34, 34, 34, 0.8);", "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    "The mitochondria is the powerhouse of the cell.", "docker compose up -d --build", "curl -X POST https://api.example.com/v1/items -d '{\"name\": \"test\"}'",
    "Happy birthday!! Hope you have a wonderful day", "A monad is just a monoid in the category of endofunctors.",
    "2 cups flour, 1 tsp baking soda, a pinch of salt", "Meeting adjourned, thanks everyone.", "nice one, well done",
    "Water boils at 100 degrees Celsius at sea level.", "console.log('here');", "interface Props { title: string; onClose: () => void }",
    "In 1969, humans first landed on the Moon.", "brb grabbing coffee", "This page intentionally left blank.",
    "if err != nil { return fmt.Errorf(\"read failed: %w\", err) }", "ok cool", "Sorry, I was on mute.",
    "The capital of Australia is Canberra.", "chmod +x deploy.sh && ./deploy.sh", "what a game last night",
    "kubectl get pods -n default", "Roses are red, violets are blue.", "Please find the agenda attached.",
    "An apple a day keeps the doctor away.", "<div class=\"container\"><p>Hello</p></div>", "can't wait for the weekend",
    "The Treaty of Westphalia was signed in 1648.", "export PATH=\"$HOME/bin:$PATH\"", "Thanks, received.",
    "yep, agreed", "Error: connect ECONNREFUSED 127.0.0.1:5432", "Stir occasionally until the onions are translucent.",
    "README updated with install steps.", "Good morning all, hope everyone had a nice weekend.", "That makes sense to me.",
    "import numpy as np\nimport pandas as pd", "E = mc^2 relates mass and energy.", "left a comment on the doc",
    "The train to the airport leaves every twenty minutes.", "LGTM, ship it", "noted, will do", "Typo fixed in the heading.",
    "pls ignore my last message",
]

HARD_NEG = {
    "project": ["{e} demo went great today!", "Great job on {e}, everyone.", "I finished the {e} slides.", "{e} is such a good codename.",
                "Just pushed my {e} branch.", "The {e} retro is done, notes are in the doc.", "Loved the {e} offsite photos."],
    "person": ["Thanks {e}, that works!", "{e} is hilarious.", "Great talk today, {e}.", "Congrats to {e} on the marathon!",
               "{e} just walked in.", "Say hi to {e} for me.", "{e} already replied, all sorted."],
    "vendor": ["Forwarding the {e} newsletter, nothing urgent.", "{e} has a new logo, apparently.", "The {e} webinar was dull.",
               "Got another {e} promo email.", "{e} sent stickers again."],
}

WRAPPERS = {
    "clipboard": ["{q}", "hey — {q}", "> {q}\n\ncan you take this one?", "From the thread: \"{q}\"", "quick one: {q}"],
    "palette": ["{q}"],
    "file_drop": ["Dropped file: {slug}_notes.txt\n---\nOpen question: {q}", "Dropped file: agenda_{slug}.md\n---\n1. {q}\n2. AOB",
                  "Dropped file: {slug}_followups.txt\n---\nTODO: answer \"{q}\""],
}


@dataclass
class GoldEvent:
    id: str
    source: str
    text: str
    ts: float
    warrants_retrieval: bool
    relevant_ids: list[str] = field(default_factory=list)  # every note stating a needed fact, any version
    required_ids: list[str] = field(default_factory=list)  # only the current version of each needed fact
    kind: str = ""
    split: str = ""

    def to_event(self) -> AmbientEvent:
        return AmbientEvent(self.id, self.source, self.text, self.ts)


def build(seed: int = SEED):
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    r = random.Random(seed)
    blocks: list[dict] = []
    facts: list[dict] = []  # {entity, etype, attr, queries, versions: [block ids oldest..newest]}

    def add_block(text: str, days_ago: float) -> str:
        cid = f"c{len(blocks):04d}"
        ts = (NOW - timedelta(days=days_ago, minutes=r.randint(0, 600))).timestamp()
        blocks.append({"id": cid, "text": text, "ts": ts, "tokens": len(enc.encode(text))})
        return cid

    def first(name: str) -> str:
        return name.split()[0]

    def add_fact(entity, etype, attr, gen, templates, queries):
        n_versions = r.choices([1, 2, 3], weights=[60, 30, 10])[0]
        values: list[str] = []
        while len(values) < n_versions:
            v = gen(r)
            if v not in values and v != entity:
                values.append(v)
        # Oldest first. Gaps between versions vary from days to months.
        ages = sorted((r.uniform(3, 500) for _ in range(n_versions)), reverse=True)
        ids = []
        for v, age in zip(values, ages):
            t = r.choice(templates)
            ids.append(add_block(t.format(e=entity, v=v, p=first(r.choice([p for p in PEOPLE if p != entity]))), age))
        facts.append({"entity": entity, "etype": etype, "attr": attr, "queries": queries, "versions": ids})

    for etype, entities, attrs in (("project", PROJECTS, PROJECT_ATTRS), ("person", PEOPLE, PERSON_ATTRS), ("vendor", VENDORS, VENDOR_ATTRS)):
        for e in entities:
            for attr, (gen, templates, queries) in attrs.items():
                add_fact(e, etype, attr, gen, templates, queries)
            for t in r.sample(FILLER[etype], k=min(6, len(FILLER[etype]))):
                add_block(t.format(e=e, p=first(r.choice([p for p in PEOPLE if p != e]))), r.uniform(1, 500))
    for subj, gen, templates, queries in PERSONAL:
        n = r.choice([1, 2])
        values: list[str] = []
        while len(values) < n:
            v = gen(r)
            if v not in values:
                values.append(v)
        ages = sorted((r.uniform(3, 400) for _ in range(n)), reverse=True)
        ids = [add_block(templates[i if i < len(templates) else -1].format(v=v), age) for i, (v, age) in enumerate(zip(values, ages))]
        facts.append({"entity": subj, "etype": "personal", "attr": subj, "queries": queries, "versions": ids})

    seen_noise: set[str] = set()
    target = 1500
    for _ in range(200_000):
        if len(blocks) >= target:
            break
        tmpl, slots = r.choice(NOISE_PARTS)
        text = tmpl.format(**{k: r.choice(v) for k, v in slots.items()})
        if text not in seen_noise:
            seen_noise.add(text)
            add_block(text, r.uniform(1, 500))

    # ---- events ----
    events: list[GoldEvent] = []

    def add_event(text, source, warrants, kind, relevant=(), required=()):
        ts = (NOW - timedelta(minutes=r.randint(0, 5000))).timestamp()
        events.append(GoldEvent(f"e{len(events):04d}", source, text, ts, warrants, sorted(relevant), sorted(required), kind))

    def render(fact) -> str:
        q = r.choice(fact["queries"])
        return q.format(e=fact["entity"]) if fact["etype"] != "personal" else q

    def wrap(q: str, source: str, slug: str) -> str:
        return r.choice(WRAPPERS[source]).format(q=q, slug=slug.lower().replace(" ", "_"))

    sources = ["clipboard"] * 5 + ["palette"] * 3 + ["file_drop"] * 2
    multi = [f for f in facts if len(f["versions"]) > 1]
    single = [f for f in facts if len(f["versions"]) == 1]
    r.shuffle(multi), r.shuffle(single)

    for f in multi[:70] + single[:70]:  # one-fact events, half on revised facts
        src = r.choice(sources)
        add_event(wrap(render(f), src, f["entity"]), src, True, "revised_fact" if len(f["versions"]) > 1 else "single_fact",
                  f["versions"], f["versions"][-1:])

    by_entity: dict[str, list] = {}
    for f in facts:
        if f["etype"] != "personal":
            by_entity.setdefault(f["entity"], []).append(f)
    ents = list(by_entity)
    r.shuffle(ents)
    for e in ents[:40]:  # two facts about one entity
        a, b = r.sample(by_entity[e], 2)
        src = r.choice(["clipboard", "file_drop"])
        q = f"{render(a)} Also: {render(b)}"
        add_event(wrap(q, src, e), src, True, "two_facts", a["versions"] + b["versions"], [a["versions"][-1], b["versions"][-1]])

    for text in r.sample(NOISE_EVENTS, 60):
        add_event(text, r.choice(["clipboard"] * 4 + ["palette"]), False, "noise")
    pools = [("project", PROJECTS), ("person", PEOPLE), ("vendor", VENDORS)]
    seen: set[str] = set()
    while sum(e.kind == "entity_no_need" for e in events) < 60:
        etype, names = r.choice(pools)
        name = r.choice(names)
        text = r.choice(HARD_NEG[etype]).format(e=first(name) if etype == "person" else name)
        if text not in seen:
            seen.add(text)
            add_event(text, "clipboard", False, "entity_no_need")

    # Stratified 50/50 split: thresholds are fitted on `cal`, reported on `test`.
    for kind in {e.kind for e in events}:
        group = [e for e in events if e.kind == kind]
        r.shuffle(group)
        for i, e in enumerate(group):
            e.split = "cal" if i % 2 == 0 else "test"
    # block id -> fact id, for grading conflict judgments (two versions of one fact conflict).
    fact_of = {cid: f"{f['etype']}:{f['entity']}:{f['attr']}" for f in facts for cid in f["versions"]}
    return blocks, events, fact_of


def load_facts(path: Path = DATA_DIR) -> dict[str, str]:
    return json.loads((path / "facts.json").read_text())


def write(out: Path = DATA_DIR) -> None:
    blocks, events, fact_of = build()
    out.mkdir(parents=True, exist_ok=True)
    (out / "blocks.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in blocks))
    (out / "events.jsonl").write_text("".join(json.dumps(asdict(e), ensure_ascii=False) + "\n" for e in events))
    (out / "facts.json").write_text(json.dumps(fact_of, indent=0))
    pos = sum(e.warrants_retrieval for e in events)
    print(f"{len(blocks)} blocks, {len(events)} events ({pos} warrant retrieval, {len(events) - pos} do not) -> {out}")
    for kind in sorted({e.kind for e in events}):
        print(f"  {kind:16s} {sum(e.kind == kind for e in events)}")


def load(path: Path = DATA_DIR) -> tuple[list[Block], list[GoldEvent]]:
    blocks = [Block(**json.loads(l)) for l in (path / "blocks.jsonl").read_text().splitlines()]
    events = [GoldEvent(**json.loads(l)) for l in (path / "events.jsonl").read_text().splitlines()]
    return blocks, events


if __name__ == "__main__":
    write()
