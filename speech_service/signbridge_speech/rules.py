"""Offline fallback (no API key / no internet). English only, template based.

gloss_to_sentence(["ME","HOT","YESTERDAY","TODAY"])  -> "I've had a fever since yesterday."
text_to_gloss("Did you take your medicine today?")  -> ["TODAY", "YOU", "MEDICINE"], "question"
"""
from __future__ import annotations

import re

SIGN_CONCEPTS = ["HELLO", "HOW-ARE-YOU", "THANK-YOU", "ME", "YOU", "DOCTOR", "HOSPITAL", "SICK", "HOT", "GOOD",
                 "BAD", "MEDICINE", "TODAY", "TOMORROW", "YESTERDAY", "MOTHER", "FATHER", "FAMILY"]
GREETINGS = {"HELLO": "Hello.", "HOW-ARE-YOU": "How are you?", "THANK-YOU": "Thank you."}
TIMES = {"YESTERDAY", "TODAY", "TOMORROW"}
# subject words -> (English, person: 1 = I, 2 = you/plural, 3 = he/she/it)
SUBJECTS = {"ME": ("I", 1), "YOU": ("you", 2), "MOTHER": ("my mother", 3), "FATHER": ("my father", 3),
            "FAMILY": ("my family", 3), "DOCTOR": ("the doctor", 3), "MEDICINE": ("the medicine", 3)}

# predicate -> tense -> (I-form, you/plural-form, he/she-form)
PRED = {
    "SICK": {"present": ("am sick", "are sick", "is sick"), "past": ("was sick", "were sick", "was sick"),
             "perfect": ("have been sick", "have been sick", "has been sick"), "future": ("will be sick",) * 3},
    "HOT": {"present": ("have a fever", "have a fever", "has a fever"), "past": ("had a fever",) * 3,
            "perfect": ("have had a fever", "have had a fever", "has had a fever"),
            "future": ("may have a fever",) * 3},
    "BAD": {"present": ("feel unwell", "feel unwell", "feels unwell"), "past": ("felt unwell",) * 3,
            "perfect": ("have been feeling unwell", "have been feeling unwell", "has been feeling unwell"),
            "future": ("may feel unwell",) * 3},
    "GOOD": {"present": ("feel better", "feel better", "feels better"), "past": ("felt better",) * 3,
             "perfect": ("have been feeling better", "have been feeling better", "has been feeling better"),
             "future": ("will feel better",) * 3},
    "MEDICINE": {"present": ("need medicine", "need medicine", "needs medicine"), "past": ("took medicine",) * 3,
                 "perfect": ("have been taking medicine", "have been taking medicine", "has been taking medicine"),
                 "future": ("will need medicine",) * 3},
    "HOSPITAL": {"present": ("need to go to the hospital", "need to go to the hospital", "needs to go to the hospital"),
                 "past": ("went to the hospital",) * 3,
                 "perfect": ("have been in the hospital", "have been in the hospital", "has been in the hospital"),
                 "future": ("will go to the hospital",) * 3},
    "DOCTOR": {"present": ("need a doctor", "need a doctor", "needs a doctor"), "past": ("saw a doctor",) * 3,
               "perfect": ("have seen a doctor", "have seen a doctor", "has seen a doctor"),
               "future": ("will see the doctor",) * 3},
}
# When the subject is a thing (the medicine), GOOD/BAD mean "is working / isn't working".
THING_PRED = {"GOOD": {"present": "is helping", "past": "helped", "perfect": "has been helping", "future": "will help"},
              "BAD": {"present": "is not helping", "past": "did not help", "perfect": "has not been helping",
                      "future": "will not help"}}
TIME_SUFFIX = {"past": " yesterday", "perfect": " since yesterday", "future": " tomorrow", "present": ""}


def _tense(times: list[str]) -> tuple[str, str]:
    t = set(times)
    if "YESTERDAY" in t and "TODAY" in t:
        return "perfect", ""
    if "YESTERDAY" in t:
        return "past", ""
    if "TOMORROW" in t:
        return "future", ""
    return "present", " today" if "TODAY" in t else ""


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _invert(clause: str) -> str:
    """'you are the doctor' -> 'are you the doctor' (only for be/have/will/can)."""
    m = re.match(r"^(.+?) (am|are|is|was|were|have|has|will) (.+)$", clause)
    if not m:
        return clause
    subj, aux, rest = m.groups()
    if aux in ("have", "has") and not rest.startswith(("been", "had", "seen")):
        return f"do{'es' if aux == 'has' else ''} {subj} have {rest}"
    return f"{aux} {subj} {rest}"


def gloss_to_sentence(glosses: list[str], emotion: str = "neutral") -> str:
    glosses = [g.upper() for g in glosses if g]
    out: list[str] = []
    rest = []
    for g in glosses:                                     # greetings become their own sentences
        (out.append(GREETINGS[g]) if g in GREETINGS else rest.append(g))
    question = emotion == "question"
    if rest:
        times = [g for g in rest if g in TIMES]
        words = [g for g in rest if g not in TIMES]
        tense, today = _tense(times)
        preds = [g for g in words if g in PRED or g in THING_PRED]
        subs = [g for g in words if g in SUBJECTS and g not in preds]
        # a noun with no predicate after it: DOCTOR/MEDICINE/HOSPITAL as needs ("ME DOCTOR" = I need a doctor)
        if "ME" in subs or not subs:
            subject_words = [g for g in subs if g in ("ME", "YOU", "MOTHER", "FATHER", "FAMILY")]
        else:
            subject_words = subs
        if not subject_words and "MEDICINE" in words and any(p in THING_PRED for p in preds):
            subject_words = ["MEDICINE"]
        preds = [p for p in preds if p not in subject_words]
        unknown = [g for g in words if g not in SUBJECTS and g not in PRED and g not in THING_PRED]

        if not preds and not times and subject_words and subject_words != ["ME"]:
            names = _join([SUBJECTS[s][0] for s in subject_words])
            if emotion == "urgent":
                out.append(f"Please call {names}!")
            elif question and subject_words == ["YOU"]:
                out.append("Are you okay?")
            elif question and "DOCTOR" in words and "YOU" in words:
                out.append("Are you the doctor?")
            else:
                out.append(_cap(names) + ".")
        elif question and set(words) == {"YOU", "DOCTOR"}:
            out.append("Are you the doctor?")
        else:
            if not subject_words:
                subject_words = ["ME"]
            subj = _join([SUBJECTS[s][0] for s in subject_words])
            person = 2 if len(subject_words) > 1 else SUBJECTS[subject_words[0]][1]
            if not preds:                                 # e.g. "ME TODAY": just time
                preds = ["BAD"] if emotion == "urgent" else []
            if subject_words == ["MEDICINE"]:
                verb = _join([THING_PRED[p][tense] for p in preds if p in THING_PRED]) or "is here"
            else:
                verb = _join([PRED[p][tense][person - 1] for p in preds if p in PRED]) or "am here"
            clause = f"{subj} {verb}{TIME_SUFFIX[tense]}{today}"
            if unknown:
                clause += " (" + " ".join(u.lower() for u in unknown) + ")"
            if question:
                clause = _invert(clause)
            if not question:
                clause = re.sub(r"^I have (been|had|seen)", r"I've \1", clause).replace("I am ", "I'm ")
            clause = _cap(clause)
            end = "?" if question else ("!" if emotion == "urgent" else ".")
            out.append(clause + end)
    return " ".join(out) if out else ""


# ---------------------------------------------------------------- hearing person -> avatar gloss

KEYWORDS = [  # (regex on lower-cased English, gloss)
    (r"\bhow are you\b|\bhow do you feel\b|\bhow are you feeling\b", "HOW-ARE-YOU"),
    (r"\b(hello|hi|hey|namaste|good morning|good evening)\b", "HELLO"),
    (r"\b(thank you|thanks|thank)\b", "THANK-YOU"),
    (r"\b(i|me|my|mine|i'm|i've|we|us|our)\b", "ME"),
    (r"\b(you|your|yours|you're|you've)\b", "YOU"),
    (r"\b(doctor|doctors|dr|nurse|physician)\b", "DOCTOR"),
    (r"\b(hospital|clinic|ward|admit|admitted|emergency room)\b", "HOSPITAL"),
    (r"\b(sick|ill|unwell|pain|hurt|hurts|ache|aching|vomit|vomiting|injury|disease)\b", "SICK"),
    (r"\b(fever|hot|temperature|burning)\b", "HOT"),
    (r"\b(good|fine|better|well|okay|ok|great|normal)\b", "GOOD"),
    (r"\b(bad|worse|serious|not well)\b", "BAD"),
    (r"\b(medicine|medicines|tablet|tablets|pill|pills|drug|medication|syrup|injection|dose)\b", "MEDICINE"),
    (r"\b(yesterday|last night)\b", "YESTERDAY"),
    (r"\b(today|now|tonight|this morning)\b", "TODAY"),
    (r"\b(tomorrow)\b", "TOMORROW"),
    (r"\b(mother|mom|mum|amma|maa)\b", "MOTHER"),
    (r"\b(father|dad|papa|nanna)\b", "FATHER"),
    (r"\b(family|relatives|parents)\b", "FAMILY"),
]
# Hindi / Telugu words (romanised, as people type or Whisper writes them) for offline use.
KEYWORDS += [
    (r"\b(namaste|namaskar|namaskaram)\b", "HELLO"),
    (r"\b(dhanyavaad|dhanyavad|shukriya|dhanyavaadalu)\b", "THANK-YOU"),
    (r"\b(mera|meri|mujhe|nenu|naaku)\b", "ME"),         # not "main"/"hum": clash with English
    (r"\b(aap|aapko|aapka|aapki|tum|tumhe|meeru|meeku|neeku|nuvvu)\b", "YOU"),
    (r"\b(daktar|vaidya)\b", "DOCTOR"),
    (r"\b(aspatal|haspatal|aasupatri|asupatri)\b", "HOSPITAL"),
    (r"\b(bimaar|bimar|dard|takleef|noppi|anarogyam)\b", "SICK"),
    (r"\b(bukhar|bukhaar|jwaram|jvaram)\b", "HOT"),
    (r"\b(accha|achha|theek|thik|baagundi|bagundi|manchi)\b", "GOOD"),
    (r"\b(kharab|bura|buri|baaledu|baledu)\b", "BAD"),
    (r"\b(dawai|dawa|dava|goli|mandu|mandulu)\b", "MEDICINE"),
    (r"\b(aaj|abhi|ivvala|ee roju|ippudu)\b", "TODAY"),
    (r"\b(ninna)\b", "YESTERDAY"),
    (r"\b(repu)\b", "TOMORROW"),
    (r"\b(maa|mummy|maata)\b", "MOTHER"),
    (r"\b(pita|pitaji|naanna|nanna)\b", "FATHER"),
    (r"\b(parivaar|parivar|kutumbam)\b", "FAMILY"),
]
# Native script (no \b: word boundaries don't work with Indic combining marks).
KEYWORDS += [(p, g) for p, g in [
    ("नमस्ते|నమస్కారం", "HELLO"), ("धन्यवाद|शुक्रिया|ధన్యవాదాలు", "THANK-YOU"),
    ("डॉक्टर|डाक्टर|డాక్టర్|వైద్యుడు", "DOCTOR"), ("अस्पताल|ఆసుపత్రి|హాస్పిటల్", "HOSPITAL"),
    ("बीमार|दर्द|నొప్పి|అనారోగ్య", "SICK"), ("बुखार|జ్వరం", "HOT"), ("दवा|दवाई|మందు", "MEDICINE"),
    ("आज|ఈరోజు|ఈ రోజు", "TODAY"), ("నిన్న", "YESTERDAY"), ("రేపు", "TOMORROW"),
    ("माँ|मां|అమ్మ", "MOTHER"), ("पिता|पापा|నాన్న", "FATHER"), ("परिवार|కుటుంబం", "FAMILY"),
    ("आप|तुम|మీరు|నువ్వు", "YOU"), ("मैं|मुझे|मेरा|मेरी|నేను|నాకు", "ME"),
]]
# Hindi "kal"/"कल" means both yesterday and tomorrow: decided by the verb tense in text_to_gloss.
KAL = r"\bkal\b|कल"
URGENT = r"\b(emergency|urgent|urgently|immediately|quick|quickly|help|bleeding|danger|serious|now!)"
HAPPY = r"\b(thank|thanks|great|congratulations|good news|happy|recovered)\b"
QUESTION = r"\?\s*$|^(what|when|where|why|how|who|which|do|does|did|is|are|can|could|will|have|has|should)\b"


ANGRY = (r"\b(angry|stupid|nonsense|shut up|how dare|ridiculous|unacceptable|idiot|useless|fed up|"
         r"what is wrong with you|stop wasting|bakwas|pagal|gussa|kopam)\b")


def tone(text: str) -> str:
    t = text.lower().strip()
    if re.search(URGENT, t):
        return "urgent"
    letters = [c for c in text if c.isalpha() and c.isascii()]
    shouting = len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) > 0.7
    if re.search(ANGRY, t) or shouting or "!!" in t:
        return "angry"
    if re.search(QUESTION, t):
        return "question"
    if re.search(HAPPY, t):
        return "happy"
    return "neutral"


def text_to_gloss(text: str, allowed: set[str]) -> list[str]:
    """English -> gloss words the avatar has clips for, in ISL-ish order (time words first)."""
    t = text.lower()
    found: list[tuple[int, str]] = []
    for pattern, gloss in KEYWORDS:
        if gloss not in allowed:
            continue
        for m in re.finditer(pattern, t):
            found.append((m.start(), gloss))
    for m in re.finditer(KAL, t):
        future = re.search(r"\b(ga|gi|ge|aana|aaiye|aayenge|jaana)\b|गा|गी|गे", t)
        g = "TOMORROW" if future else "YESTERDAY"
        if g in allowed:
            found.append((m.start(), g))
    found.sort()
    seq: list[str] = []
    for _, g in found:
        if g == "GOOD" and "HOW-ARE-YOU" in seq:          # "how are you feeling" doesn't also need GOOD
            continue
        if g == "YOU" and seq and seq[-1] in ("HOW-ARE-YOU", "THANK-YOU"):
            continue
        if not seq or seq[-1] != g:
            seq.append(g)
    # drop duplicates, keep first
    dedup = list(dict.fromkeys(seq))
    greet = [g for g in GREETINGS if g in dedup]
    times = [g for g in dedup if g in TIMES]
    return greet + times + [g for g in dedup if g not in TIMES and g not in GREETINGS]


# ---------------------------------------------------------------- smart replies & summary (offline)

def suggest_replies(last_speaker_msg: dict | None) -> list[str]:
    """3-4 replies for the Deaf user to tap, from the tone and signs of what the speaker just said."""
    if not last_speaker_msg:
        return ["Hello.", "I am Deaf. Please be patient with me.", "Please write it down for me.", "Thank you."]
    gloss = set(last_speaker_msg.get("gloss", "").split())
    emo = last_speaker_msg.get("emotion", "neutral")
    if emo == "urgent":
        return ["Okay, I understand.", "Please help me.", "Please call my family.", "Please say that again."]
    if emo == "question":
        out = []
        if "HOT" in gloss:
            out += ["Yes, I have a fever.", "No, I don't have a fever."]
        elif "MEDICINE" in gloss:
            out += ["Yes, I took my medicine.", "No, I didn't take it."]
        elif "SICK" in gloss or "BAD" in gloss:
            out += ["Yes, I feel unwell.", "No, I feel better now."]
        elif "HOW-ARE-YOU" in gloss:
            out += ["I'm not feeling well.", "I'm fine, thank you."]
        else:
            out += ["Yes.", "No."]
        return out + ["I don't know.", "Please say that again."]
    if emo == "angry":
        return ["I'm sorry.", "Please be patient with me.", "Please write it down for me."]
    return ["Okay.", "Thank you.", "I don't understand.", "Please write it down for me."]


def summarize(lines: list[dict]) -> str:
    """Plain summary when no AI is available: counts + the most important lines."""
    if not lines:
        return "No conversation yet."
    signed = [l for l in lines if l["from"] == "signer"]
    spoken = [l for l in lines if l["from"] == "speaker"]
    urgent = [l["text"] for l in lines if l["emotion"] == "urgent"]
    parts = [f"Conversation with {len(signed)} message(s) from the Deaf person and {len(spoken)} from the hearing person."]
    if signed:
        parts.append("The Deaf person said: " + " ".join(l["text"] for l in signed[:6]))
    if urgent:
        parts.append("Urgent: " + " ".join(urgent[:3]))
    return " ".join(parts)
