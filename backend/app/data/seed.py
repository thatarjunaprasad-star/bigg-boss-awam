"""Seed data — Bigg Boss legends roster (public figures), fan-feed news, trivia bank.

All content is an unofficial fan project for entertainment purposes.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .db import Database

CONTESTANTS = [
    ("Sidharth Shukla", "The King of Hearts", "Season 13 · Winner", "Actor / Model"),
    ("Gauahar Khan", "The Elegant Tactician", "Season 7 · Winner", "Actor / Model"),
    ("Gautam Gulati", "The Entertainer Supreme", "Season 8 · Winner", "Actor"),
    ("Shweta Tiwari", "The Grounded Champion", "Season 4 · Winner", "Actor"),
    ("Rubina Dilaik", "The Kinar Kween", "Season 14 · Winner", "Actor"),
    ("Tejasswi Prakash", "The Naagin of the House", "Season 15 · Winner", "Actor"),
    ("MC Stan", "The Desi Hip-Hop Icon", "Season 16 · Winner", "Rapper"),
    ("Munawar Faruqui", "The Witty Wordsmith", "Season 17 · Winner", "Stand-up Comic"),
    ("Karan Veer Mehra", "The Comeback King", "Season 18 · Winner", "Actor"),
    ("Hina Khan", "Sher Khan of the House", "Season 11 · Finalist", "Actor"),
    ("Shehnaaz Gill", "Punjab's Katrina", "Season 13 · Finalist", "Actor / Singer"),
    ("Vikas Gupta", "The Mastermind", "Season 11 · Finalist", "Producer"),
]

NEWS = [
    ("Awam All-Stars: The Legend Meter Is Live",
     "The doors of the unofficial Awam house have opened. Twelve legends from across eighteen seasons enter the "
     "fan-voted arena, and the first Awam Polls are already shaking. Early pulse: the Season 13 contingent is "
     "out in force.",
     "House Pulse"),
    ("Eviction Watch: The Bottom Three Nobody Saw Coming",
     "Week one of the All-Star ladder has thrown up a shocker — two former winners are flirting with the bottom "
     "of the Awam ladder. The fandom is split, and the comments floor is a war zone of polite aristocratic fury.",
     "Eviction Watch"),
    ("Task Tracker: The Patience Ka Poster Task",
     "House legends were asked to hold a framed portrait absolutely still for six hours. Sparks flew, alliances "
     "cracked, and one mastermind quietly negotiated a tea-sharing pact mid-task. Ratings, as they say, went up.",
     "Task Tracker"),
    ("Style Files: The Gold Standard of the Awam House",
     "This season's unofficial dress code is black and champagne gold — and the legends have delivered. The "
     "Awam style desk has awarded its first Best Dressed scroll of the week. No spoilers, but the trophy case "
     "just got heavier.",
     "Style Files"),
    ("The Confession Room Diaries: Week One Whispers",
     "Sources close to the couch report late-night strategy sessions, one tearful monologue about chai, and a "
     "shocking reveal that a certain winner has never watched their own season back. The Awam gasped in unison.",
     "House Pulse"),
    ("Poll Pulse: A Photo-Finish at the Top",
     "The gap between the top two legends on the Awam ladder is down to a rounding error. Every vote counts, "
     "every rating writes history. The oracle suggests you make your choice before the ticker moves again.",
     "Awam Polls"),
    ("Task Tracker: The Trivia Gauntlet",
     "The house was divided into squads and quizzed on eighteen seasons of Bigg Boss history. The hip-hop "
     "contingent stunned everyone with encyclopedic recall of Season 4. Respect was handed out like mithai.",
     "Task Tracker"),
    ("Style Files: Monsoon of Sequins",
     "A mid-week task celebration turned into an unplanned fashion parade. The Awam style desk logs its "
     "second scroll of the week — awarded for what can only be described as 'regal chaos'.",
     "Style Files"),
    ("Eviction Watch: The Fandom Armies Assemble",
     "As the weekend approaches, fan clubs have switched on the engines. The oracle has one humble request: "
     "vote with your heart, rate with your conscience, and keep the discourse classy.",
     "Eviction Watch"),
    ("Behind The Eye: How Awam Voting Works",
     "Every session gets one vote per 24 hours and a five-star rating per legend. The ladder is pure Awam — "
     "no judges, no bias, only the people's oracle doing the arithmetic.",
     "Awam Polls"),
]

TRIVIA = [
    ("Who won the very first season of Bigg Boss (Hindi) in 2006?",
     ["Rahul Roy", "Carol Gracias", "Ravi Kishan", "Amit Sadh"], 0, "easy", "History",
     "Rahul Roy took the Season 1 crown; the show aired on Sony TV before moving to Colors."),
    ("Which superstar has hosted Bigg Boss (Hindi) every season since Season 4?",
     ["Shah Rukh Khan", "Salman Khan", "Aamir Khan", "Akshay Kumar"], 1, "easy", "Hosts",
     "Salman Khan's Weekend Ka Vaar became the show's signature from Season 4 onwards."),
    ("Sidharth Shukla won which season of Bigg Boss?",
     ["Season 11", "Season 12", "Season 13", "Season 14"], 2, "easy", "Winners",
     "Season 13 (2019) — one of the most-watched finales in the show's history."),
    ("Which contestant is lovingly called 'Punjab ki Katrina'?",
     ["Hina Khan", "Shehnaaz Gill", "Gauahar Khan", "Rubina Dilaik"], 1, "easy", "Nicknames",
     "Shehnaaz Gill's charm on Season 13 earned her the fandom-favourite title."),
    ("Gauahar Khan lifted the winner's trophy in which season?",
     ["Season 5", "Season 6", "Season 7", "Season 8"], 2, "medium", "Winners",
     "Season 7 (2013) — Gauahar beat Tanishaa Mukerji in the finale."),
    ("What is the iconic logo of Bigg Boss?",
     ["A golden crown", "A stylised eye", "A locked door", "A trophy"], 1, "easy", "History",
     "The watchful eye has watched over every season — nothing escapes the Bigg Boss eye."),
    ("Who was nicknamed 'The Mastermind' during Season 11?",
     ["Vikas Gupta", "Hina Khan", "Shilpa Shinde", "Priyank Sharma"], 0, "medium", "Nicknames",
     "Vikas Gupta's strategic gameplay earned him the house-wide title."),
    ("Which rapper won Bigg Boss Season 16?",
     ["Badshah", "MC Stan", "Divine", "Raftaar"], 1, "medium", "Winners",
     "MC Stan took home the Season 16 trophy — 'Shq pink hai' became house vocabulary."),
    ("Rubina Dilaik, the 'Kinar Kween', won which season?",
     ["Season 13", "Season 14", "Season 15", "Season 16"], 1, "medium", "Winners",
     "Season 14 (2020), where she entered with husband Abhinav Shukla."),
    ("Tejasswi Prakash won Season 15. What is her famous TV avatar?",
     ["Naagin", "Bahu", "Detective", "Doctor"], 0, "medium", "Careers",
     "Tejasswi headlined Naagin — a role that became her house nickname too."),
    ("Which stand-up comedian won Bigg Boss Season 17?",
     ["Munawar Faruqui", "Ankit Gupta", "Abhishek Kumar", "Samay Raina"], 0, "medium", "Winners",
     "Munawar Faruqui won Season 17 in 2024."),
    ("Karan Veer Mehra, the 'Comeback King', won which recent season?",
     ["Season 16", "Season 17", "Season 18", "Season 19"], 2, "hard", "Winners",
     "Karan Veer Mehra won Season 18 after also winning Khatron Ke Khiladi 14."),
    ("Gautam Gulati's 'We love Gauti' chants belong to which season?",
     ["Season 6", "Season 7", "Season 8", "Season 9"], 2, "medium", "History",
     "Season 8 — Gautam's persona and the 'Gauti' fandom became instant classics."),
    ("Hina Khan reached the Season 11 finale. What did fans call her?",
     ["Sher Khan", "Tigress", "Queen Bee", "Iron Lady"], 0, "hard", "Nicknames",
     "Hina's fierce Season 11 run earned her the 'Sher Khan' badge."),
    ("Which channel did Bigg Boss Hindi move to after Season 1?",
     ["Star Plus", "Colors", "Zee TV", "Sony Sab"], 1, "hard", "History",
     "From Season 2 onwards the show found its home on Colors."),
]


def seed(db: Database) -> None:
    if db.is_seeded():
        return
    rng = random.Random(20061103)  # Bigg Boss S1 premiere date — deterministic seed
    statements: list[tuple[str, tuple]] = []
    for name, tagline, season, profession in CONTESTANTS:
        base_votes = rng.randrange(2800, 9600)
        rating_count = rng.randrange(180, 520)
        rating_sum = round(rng.uniform(0.68, 0.92) * 5 * rating_count, 1)
        statements.append((
            "INSERT INTO contestants (name, tagline, season, profession, house_status, votes, rating_sum, rating_count) "
            "VALUES (?, ?, ?, ?, 'Legend', ?, ?, ?)",
            (name, tagline, season, profession, base_votes, rating_sum, rating_count),
        ))
    now = datetime.now(timezone.utc)
    for i, (title, body, category) in enumerate(NEWS):
        published = (now - timedelta(hours=len(NEWS) - i, minutes=rng.randrange(0, 50))).isoformat(timespec="seconds")
        statements.append((
            "INSERT INTO news (title, body, category, published_at) VALUES (?, ?, ?, ?)",
            (title, body, category, published),
        ))
    import json
    for question, options, answer_idx, difficulty, category, fun_fact in TRIVIA:
        statements.append((
            "INSERT INTO trivia (question, options, answer_idx, difficulty, category, fun_fact) VALUES (?, ?, ?, ?, ?, ?)",
            (question, json.dumps(options), answer_idx, difficulty, category, fun_fact),
        ))
    db.execute_many(statements)
