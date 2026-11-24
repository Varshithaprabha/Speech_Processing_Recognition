"""Part B's core: both directions of the conversation, with Claude first and rules as fallback."""
from __future__ import annotations

from collections import deque

from . import config, llm, rules
from .messages import make_message

QUICK_REPLIES = [  # for the Deaf person to tap when signing isn't practical
    {"id": "yes", "text": "Yes.", "emotion": "neutral"},
    {"id": "no", "text": "No.", "emotion": "neutral"},
    {"id": "wait", "text": "Please wait a moment.", "emotion": "neutral"},
    {"id": "repeat", "text": "Please say that again, slowly.", "emotion": "question"},
    {"id": "write", "text": "Please write it down for me.", "emotion": "neutral"},
    {"id": "understand_not", "text": "I don't understand.", "emotion": "question"},
    {"id": "pain", "text": "I am in pain.", "emotion": "urgent"},
    {"id": "water", "text": "May I have some water, please?", "emotion": "question"},
    {"id": "washroom", "text": "Where is the washroom?", "emotion": "question"},
    {"id": "thanks", "text": "Thank you.", "emotion": "happy"},
]
QUICK_TRANSLATIONS = {   # so quick replies work offline in all three languages
    "hi": {"yes": "हाँ।", "no": "नहीं।", "wait": "कृपया एक पल रुकिए।", "repeat": "कृपया फिर से धीरे बोलिए।",
           "write": "कृपया इसे लिखकर दीजिए।", "understand_not": "मुझे समझ नहीं आया।", "pain": "मुझे दर्द हो रहा है।",
           "water": "क्या मुझे थोड़ा पानी मिल सकता है?", "washroom": "शौचालय कहाँ है?", "thanks": "धन्यवाद।"},
    "te": {"yes": "అవును.", "no": "కాదు.", "wait": "దయచేసి ఒక్క క్షణం ఆగండి.", "repeat": "దయచేసి మళ్ళీ నెమ్మదిగా చెప్పండి.",
           "write": "దయచేసి రాసి ఇవ్వండి.", "understand_not": "నాకు అర్థం కాలేదు.", "pain": "నాకు నొప్పిగా ఉంది.",
           "water": "కొంచెం నీళ్ళు ఇస్తారా?", "washroom": "బాత్రూమ్ ఎక్కడ ఉంది?", "thanks": "ధన్యవాదాలు."},
}
SOS = {
    "en": "Emergency! I am Deaf and I need help right now. Please call a doctor.",
    "hi": "आपातकाल! मैं बधिर हूँ और मुझे अभी मदद चाहिए। कृपया डॉक्टर को बुलाइए।",
    "te": "అత్యవసరం! నాకు వినపడదు, నాకు వెంటనే సహాయం కావాలి. దయచేసి డాక్టర్‌ను పిలవండి.",
}


class Conversation:
    def __init__(self):
        self.history: deque[dict] = deque(maxlen=12)
        self.listener_language = "en"          # language the hearing person speaks; signer sentences use it
        self.clips = config.avatar_vocab()

    # ------------------------------------------------------------- signer -> hearing
    @staticmethod
    def _faithful(glosses: list[str], sentence_en: str) -> bool:
        """The AI's sentence may not mention a concept the patient didn't sign (e.g. 'fever' for SICK)."""
        signed = set(glosses)
        said = set(rules.text_to_gloss(sentence_en, set(rules.SIGN_CONCEPTS))) - {"ME", "YOU"}
        if "HOW-ARE-YOU" in signed:
            said -= {"GOOD"}                              # "how are you feeling" / "I'm fine"
        if signed & {"GOOD", "BAD"}:
            said -= {"GOOD", "BAD"}                       # "not well" vs "well" is too fuzzy to check
        if "THANK-YOU" in signed:
            said -= {"GOOD"}
        if "TODAY" not in signed:
            said -= {"TODAY"}                             # "now", "today" are harmless additions
        extra = said - signed
        return not extra

    async def on_gloss(self, msg: dict) -> dict:
        """Fill `sentence` in a gloss message from sign_service."""
        glosses = msg.get("content", "").split()
        emotion = msg.get("emotion", "neutral")
        out = dict(msg)
        draft = rules.gloss_to_sentence(glosses, emotion)        # grounds the AI and is the fallback
        res = await llm.gloss_to_sentence(glosses, emotion, msg.get("words"), self.listener_language,
                                          list(self.history), draft)
        if res and not self._faithful(glosses, res["sentence_en"]):
            # small models sometimes copy earlier topics: retry once without history, then give up
            res = await llm.gloss_to_sentence(glosses, emotion, msg.get("words"), self.listener_language, [], draft)
            if res and not self._faithful(glosses, res["sentence_en"]):
                res = None
        if res:
            # sign_service saw the face; trust its emotion. The AI may only turn neutral into question.
            emo = res["emotion"] if emotion == "neutral" and res["emotion"] == "question" else emotion
            lang = "en" if res["sentence"].isascii() else self.listener_language   # model may skip translating
            out.update(sentence=res["sentence"], sentence_en=res["sentence_en"], emotion=emo,
                       language=lang, source=res["provider"], draft=draft)
        else:
            out.update(sentence=draft, sentence_en=draft, language="en", source="rules")
        if out["sentence"]:
            self.history.append(out)
        return out

    def quick_reply(self, reply_id: str) -> dict | None:
        q = next((r for r in QUICK_REPLIES if r["id"] == reply_id), None)
        if not q:
            return None
        lang = self.listener_language
        text = QUICK_TRANSLATIONS.get(lang, {}).get(reply_id, q["text"])
        m = make_message("signer", "quick_reply", reply_id, text, language=lang if text != q["text"] else "en",
                         emotion=q["emotion"], sentence_en=q["text"], source="quick_reply")
        self.history.append(m)
        return m

    def sos(self) -> dict:
        lang = self.listener_language
        m = make_message("signer", "sos", "SOS", SOS.get(lang, SOS["en"]), language=lang if lang in SOS else "en",
                         emotion="urgent", sentence_en=SOS["en"], source="sos")
        self.history.append(m)
        return m

    # ------------------------------------------------------------- hearing -> signer
    @staticmethod
    def _grounded(ai_gloss: list[str], original: str, english: str, allowed: set[str]) -> list[str]:
        """Keep the AI's sign order, but only signs whose words were actually said (in the original or in
        the English caption), and add back any it missed. Stops the avatar signing things nobody said."""
        evidence = rules.text_to_gloss(original, allowed) + rules.text_to_gloss(english, allowed)
        if not evidence:                                  # no keywords found at all: trust the AI
            return ai_gloss
        keep = [g for g in ai_gloss if g in evidence]
        keep += [g for g in dict.fromkeys(evidence) if g not in keep]
        greet = [g for g in rules.GREETINGS if g in keep]          # HELLO, HOW-ARE-YOU, THANK-YOU
        times = [g for g in keep if g in rules.TIMES]
        return greet + times + [g for g in keep if g not in greet and g not in times]

    async def on_hearing_text(self, text: str, language: str = "en", confidence: float = 1.0,
                              english_hint: str | None = None, type_: str = "speech") -> dict:
        """Hearing person's words -> caption + tone + avatar gloss/clips."""
        if language in config.LANG_NAMES:
            self.listener_language = language
        allowed = list(self.clips)
        res = await llm.text_to_gloss(text, language, allowed, list(self.history))
        if res:
            english, emotion, source = res["english"], res["emotion"], res["provider"]
            gloss = self._grounded(res["gloss"], text, english, set(allowed))
            if rules.tone(english) == "urgent":           # never miss an emergency
                emotion = "urgent"
        else:
            english = english_hint or text            # Whisper's translate pass, when non-English
            gloss = rules.text_to_gloss(english, set(allowed))
            emotion, source = rules.tone(english), "rules"
        clips = [{"gloss": g, "video": self.clips[g].get("video", f"{g}.mp4"),
                  "landmarks": self.clips[g].get("landmarks"), "duration": self.clips[g].get("duration")}
                 for g in gloss if g in self.clips]
        m = make_message("hearing", type_, text, english, language=language, emotion=emotion,
                         confidence=confidence, gloss=" ".join(gloss), clips=clips, source=source)
        self.history.append(m)
        return m
